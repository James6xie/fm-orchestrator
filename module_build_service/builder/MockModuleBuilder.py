# -*- coding: utf-8 -*-
# Copyright (c) 2016  Red Hat, Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# Written by Jan Kaluža <jkaluza@redhat.com>


import logging
import os
import koji
import kobo.rpmlib
import pipes
import platform
import re
import subprocess
import threading

from module_build_service import conf, log, Modulemd
import module_build_service.scm
import module_build_service.utils
import module_build_service.scheduler
import module_build_service.scheduler.consumer

from module_build_service.builder.base import GenericBuilder
from module_build_service.builder.utils import (
    create_local_repo_from_koji_tag,
    execute_cmd,
    find_srpm,
    get_koji_config
)
from module_build_service.builder.KojiModuleBuilder import KojiModuleBuilder

from module_build_service import models

logging.basicConfig(level=logging.DEBUG)


class MockModuleBuilder(GenericBuilder):
    backend = "mock"
    # Global build_id/task_id we increment when new build is executed.
    _build_id_lock = threading.Lock()
    _build_id = 1
    _config_lock = threading.Lock()

    # Load mock config file template
    for cf in conf.mock_config_file:
        try:
            with open(cf) as f:
                mock_config_template = f.read()
            break
        except IOError:
            pass
    else:
        raise IOError("None of {} mock config files found."
                      .format(conf.mock_config_file))

    # Load yum config file template
    for cf in conf.yum_config_file:
        try:
            with open(cf) as f:
                yum_config_template = f.read()
            break
        except IOError:
            pass
    else:
        raise IOError("None of {} yum config files found."
                      .format(conf.yum_config_file))

    @module_build_service.utils.validate_koji_tag('tag_name')
    def __init__(self, owner, module, config, tag_name, components):
        self.module_str = module.name
        self.module = module
        self.tag_name = tag_name
        self.config = config
        self.groups = []
        self.yum_conf = MockModuleBuilder.yum_config_template
        self.koji_session = None

        # Auto-detect arch (if possible) or fallback to the configured one
        if conf.arch_autodetect:
            arch_detected = platform.machine()
            if arch_detected:
                self.arch = arch_detected
            else:
                log.warning("Couldn't determine machine arch. Falling back "
                            "to configured arch.")
                self.arch = conf.arch_fallback
        else:
            self.arch = conf.arch_fallback
        log.info("Machine arch setting: {}".format(self.arch))

        # Create main directory for this tag
        self.tag_dir = os.path.join(self.config.mock_resultsdir, tag_name)
        if not os.path.exists(self.tag_dir):
            os.makedirs(self.tag_dir)

        # Create "results" sub-directory for this tag to store build results
        # and local repository.
        self.resultsdir = os.path.join(self.tag_dir, "results")
        if not os.path.exists(self.resultsdir):
            os.makedirs(self.resultsdir)

        # Create "config" sub-directory.
        self.configdir = os.path.join(self.tag_dir, "config")
        if not os.path.exists(self.configdir):
            os.makedirs(self.configdir)

        # Generate path to mock config and add local repository there.
        self._add_repo("localrepo", "file://" + self.resultsdir, "metadata_expire=1\n")

        # Remove old files from the previous build of this tag but only
        # before the first build is done, otherwise we would remove files
        # which we already build in this module build.
        if MockModuleBuilder._build_id == 1:
            # Remove all RPMs from the results directory, but keep old logs.
            for name in os.listdir(self.resultsdir):
                if name.endswith(".rpm"):
                    os.remove(os.path.join(self.resultsdir, name))

            # Remove the old RPM repository from the results directory.
            if os.path.exists(os.path.join(self.resultsdir, "repodata/repomd.xml")):
                os.remove(os.path.join(self.resultsdir, "repodata/repomd.xml"))

            # Remove old config files from config directory.
            for name in os.listdir(self.configdir):
                os.remove(os.path.join(self.configdir, name))

        log.info("MockModuleBuilder initialized, tag_name=%s, tag_dir=%s" %
                 (tag_name, self.tag_dir))

    @property
    def module_build_tag(self):
        # Workaround koji specific code in modules.py
        return {"name": self.tag_name}

    def _createrepo(self, include_module_yaml=False):
        """
        Creates the repository using "createrepo_c" command in the resultsdir.
        """
        log.debug("Creating repository in %s" % self.resultsdir)
        path = self.resultsdir
        repodata_path = os.path.join(path, "repodata")

        # Remove old repodata files
        if os.path.exists(repodata_path):
            for name in os.listdir(repodata_path):
                os.remove(os.path.join(repodata_path, name))

        # We pass an explicit package list to createrepo_c, otherwise, it will
        # walk the target directory recursively, instead of just finding the
        # files at the toplevel.
        pkglist = os.path.join(path, "pkglist")
        pkglist_f = open(pkglist, "w")

        # Generate the mmd the same way as pungi does.
        m1 = models.ModuleBuild.query.filter(models.ModuleBuild.name == self.module_str).one()
        m1_mmd = m1.mmd()
        artifacts = Modulemd.SimpleSet()

        rpm_files = [f
                     for f in os.listdir(self.resultsdir)
                     if f.endswith(".rpm")]

        if rpm_files:
            output = subprocess.check_output(['rpm',
                                              '--queryformat',
                                              '%{NAME} %{EPOCHNUM} %{VERSION} %{RELEASE} %{ARCH}\n',
                                              '-qp'] + rpm_files,
                                             cwd=self.resultsdir,
                                             universal_newlines=True)
            nevras = output.strip().split('\n')
            if len(nevras) != len(rpm_files):
                raise RuntimeError("rpm -qp returned an unexpected number of lines")

            for rpm_file, nevra in zip(rpm_files, nevras):
                name, epoch, version, release, arch = nevra.split()

                if m1.last_batch_id() == m1.batch:
                    # If RPM is filtered-out, do not add it to artifacts list.
                    if name in m1_mmd.get_rpm_filter().get():
                        continue

                pkglist_f.write(rpm_file + '\n')
                artifacts.add('{}-{}:{}-{}.{}'.format(name, epoch, version, release, arch))

        pkglist_f.close()
        m1_mmd.set_rpm_artifacts(artifacts)

        # Generate repo.
        execute_cmd(['/usr/bin/createrepo_c', '--pkglist', pkglist, path])

        # ...and inject modules.yaml there if asked.
        if include_module_yaml:
            mmd_path = os.path.join(path, "modules.yaml")
            m1_mmd.dump(mmd_path)
            execute_cmd(['/usr/bin/modifyrepo_c', '--mdtype=modules', mmd_path, repodata_path])

    def _add_repo(self, name, baseurl, extra=""):
        """
        Adds repository to Mock config file. Call _write_mock_config() to
        actually write the config file to filesystem.
        """
        self.yum_conf += "[%s]\n" % name
        self.yum_conf += "name=%s\n" % name
        self.yum_conf += "baseurl=%s\n" % baseurl
        self.yum_conf += extra
        self.yum_conf += "enabled=1\n\n"

    def _load_mock_config(self):
        """
        Loads the variables which are generated only during the first
        initialization of mock config. This should be called before
        every _write_mock_config otherwise we overwrite Mock
        repositories or groups ...
        """

        # We do not want to load old file from previous builds here, so if
        # this is the first build in this module, skip the load completely.
        if MockModuleBuilder._build_id == 1:
            return

        with MockModuleBuilder._config_lock:
            infile = os.path.join(self.configdir, "mock.cfg")
            with open(infile, 'r') as f:
                # This looks scary, but it is the way how mock itself loads the
                # config file ...
                config_opts = {}
                code = compile(f.read(), infile, 'exec')
                # pylint: disable=exec-used
                exec(code)

                self.groups = config_opts["chroot_setup_cmd"].split(" ")[1:]
                self.yum_conf = config_opts['yum.conf']

    def _write_mock_config(self):
        """
        Writes Mock config file to local file.
        """

        with MockModuleBuilder._config_lock:
            config = str(MockModuleBuilder.mock_config_template)
            config = config.replace("$root", "%s-%s" % (self.tag_name,
                                                        str(threading.current_thread().name)))
            config = config.replace("$arch", self.arch)
            config = config.replace("$group", " ".join(self.groups))
            config = config.replace("$yum_conf", self.yum_conf)

            # We write the most recent config to "mock.cfg", so thread-related
            # configs can be later (re-)generated from it using _load_mock_config.
            outfile = os.path.join(self.configdir, "mock.cfg")
            with open(outfile, 'w') as f:
                f.write(config)

            # Write the config to thread-related configuration file.
            outfile = os.path.join(self.configdir, "mock-%s.cfg" %
                                   str(threading.current_thread().name))
            with open(outfile, 'w') as f:
                f.write(config)

    def buildroot_connect(self, groups):
        self._load_mock_config()
        self.groups = list(set().union(groups["build"], self.groups))
        log.debug("Mock builder groups: %s" % self.groups)
        self._write_mock_config()

    def buildroot_prep(self):
        pass

    def buildroot_resume(self):
        pass

    def buildroot_ready(self, artifacts=None):
        return True

    def buildroot_add_dependency(self, dependencies):
        pass

    def buildroot_add_artifacts(self, artifacts, install=False):
        self._createrepo()

        # TODO: This is just hack to install module-build-macros into the
        # buildroot. We should really install the RPMs belonging to the
        # right source RPM into the buildroot here, but we do not track
        # what RPMs are output of particular SRPM build yet.
        for artifact in artifacts:
            if artifact and artifact.startswith("module-build-macros"):
                self._load_mock_config()
                self.groups.append("module-build-macros")
                self._write_mock_config()

        from module_build_service.scheduler.consumer import fake_repo_done_message
        fake_repo_done_message(self.tag_name)

    def tag_artifacts(self, artifacts):
        pass

    def buildroot_add_repos(self, dependencies):
        self._load_mock_config()
        for tag in dependencies:
            # If tag starts with mock_resultdir, it means it is path to local
            # module build repository.
            if tag.startswith(conf.mock_resultsdir):
                repo_name = os.path.basename(tag)
                if repo_name.startswith("module-"):
                    repo_name = repo_name[7:]
                repo_dir = tag
                baseurl = "file://" + repo_dir
            else:
                repo_name = tag
                koji_config = get_koji_config(self.config)
                koji_session = koji.ClientSession(koji_config.server, opts=koji_config)
                repo = koji_session.getRepo(repo_name)
                if repo:
                    baseurl = koji.PathInfo(topdir=koji_config.topurl).repo(repo["id"], repo_name)
                    baseurl = '{0}/{1}/'.format(baseurl, self.arch)
                else:
                    repo_dir = os.path.join(self.config.cache_dir, "koji_tags", tag)
                    create_local_repo_from_koji_tag(self.config, tag, repo_dir,
                                                    [self.arch, "noarch"])
                    baseurl = "file://" + repo_dir
                # Check to see if there are any external repos tied to the tag
                for ext_repo in koji_session.getTagExternalRepos(repo_name):
                    self._add_repo(ext_repo["external_repo_name"], ext_repo["url"])
            self._add_repo(repo_name, baseurl)
        self._write_mock_config()

    def _send_build_change(self, state, source, build_id):
        try:
            nvr = kobo.rpmlib.parse_nvr(source)
        except ValueError:
            nvr = {"name": source, "release": "unknown", "version": "unknown"}

        # build_id=1 and task_id=1 are OK here, because we are building just
        # one RPM at the time.
        msg = module_build_service.messaging.KojiBuildChange(
            msg_id='a faked internal message',
            build_id=build_id,
            task_id=build_id,
            build_name=nvr["name"],
            build_new_state=state,
            build_release=nvr["release"],
            build_version=nvr["version"]
        )
        module_build_service.scheduler.consumer.work_queue_put(msg)

    def _save_log(self, resultsdir, log_name, artifact_name):
        old_log = os.path.join(resultsdir, log_name)
        new_log = os.path.join(resultsdir, artifact_name + "-" + log_name)
        if os.path.exists(old_log):
            os.rename(old_log, new_log)

    def _purge_useless_logs(self):
        """
        Remove empty or otherwise useless log files
        """
        for logf in os.listdir(self.resultsdir):

            log_path = os.path.join(self.resultsdir, logf)

            # Remove empty files
            if os.path.isfile(log_path) and os.path.getsize(log_path) == 0:
                os.remove(log_path)

            # Remove other files containing useless information
            elif logf.endswith('-srpm-stdout.log'):
                with open(log_path) as f:
                    data = f.read(4096)
                    if re.match("Downloading [^\n]*\n\n\nWrote: [^\n]", data):
                        os.remove(log_path)

    def build_srpm(self, artifact_name, source, build_id, builder):
        """
        Builds the artifact from the SRPM.
        """
        state = koji.BUILD_STATES['BUILDING']

        # Use the mock config associated with this thread.
        mock_config = os.path.join(self.configdir,
                                   "mock-%s.cfg" % str(threading.current_thread().name))

        # Open the logs to which we will forward mock stdout/stderr.
        mock_stdout_log = open(os.path.join(self.resultsdir,
                                            artifact_name + "-mock-stdout.log"), "w")
        mock_stderr_log = open(os.path.join(self.resultsdir,
                                            artifact_name + "-mock-stderr.log"), "w")

        srpm = artifact_name
        resultsdir = builder.resultsdir
        try:
            # Initialize mock.
            execute_cmd(["mock", "-v", "-r", mock_config, "--init"],
                        stdout=mock_stdout_log, stderr=mock_stderr_log)

            # Start the build and store results to resultsdir
            builder.build(mock_stdout_log, mock_stderr_log)
            srpm = find_srpm(resultsdir)

            # Emit messages simulating complete build. These messages
            # are put in the scheduler's work queue and are handled
            # by MBS after the build_srpm() method returns and scope gets
            # back to scheduler.main.main() method.
            state = koji.BUILD_STATES['COMPLETE']
            self._send_build_change(state, srpm, build_id)

            with open(os.path.join(resultsdir, "status.log"), 'w') as f:
                f.write("complete\n")
        except Exception as e:
            log.error("Error while building artifact %s: %s" % (artifact_name,
                                                                str(e)))

            # Emit messages simulating complete build. These messages
            # are put in the scheduler's work queue and are handled
            # by MBS after the build_srpm() method returns and scope gets
            # back to scheduler.main.main() method.
            state = koji.BUILD_STATES['FAILED']
            self._send_build_change(state, srpm,
                                    build_id)
            with open(os.path.join(resultsdir, "status.log"), 'w') as f:
                f.write("failed\n")

        mock_stdout_log.close()
        mock_stderr_log.close()

        self._save_log(resultsdir, "state.log", artifact_name)
        self._save_log(resultsdir, "root.log", artifact_name)
        self._save_log(resultsdir, "build.log", artifact_name)
        self._save_log(resultsdir, "status.log", artifact_name)

        # Copy files from thread-related resultsdire to the main resultsdir.
        for name in os.listdir(resultsdir):
            os.rename(os.path.join(resultsdir, name), os.path.join(self.resultsdir, name))

        # Depending on the configuration settings, remove/keep useless log files
        if conf.mock_purge_useless_logs:
            self._purge_useless_logs()

        # We return BUILDING state here even when we know it is already
        # completed or failed, because otherwise utils.start_build_batch
        # would think this component is already built and also tagged, but
        # we have just built it - tagging will happen as result of build
        # change message we are sending above using _send_build_change.
        # It is just to make this backend compatible with other backends,
        # which return COMPLETE here only in case the resulting build is
        # already in repository ready to be used. This is not a case for Mock
        # backend in the time we return here.
        reason = "Building %s in Mock" % (artifact_name)
        return build_id, koji.BUILD_STATES['BUILDING'], reason, None

    def build(self, artifact_name, source):
        log.info("Starting building artifact %s: %s" % (artifact_name, source))

        # Load global mock config for this module build from mock.cfg and
        # generate the thread-specific mock config by writing it to fs again.
        self._load_mock_config()
        self._write_mock_config()
        mock_config = os.path.join(self.configdir, "mock-%s.cfg"
                                   % str(threading.current_thread().name))

        # Get the build-id in thread-safe manner.
        build_id = None
        with MockModuleBuilder._build_id_lock:
            MockModuleBuilder._build_id += 1
            build_id = int(MockModuleBuilder._build_id)

        # Clear resultsdir associated with this thread or in case it does not
        # exist, create it.
        resultsdir = os.path.join(self.resultsdir,
                                  str(threading.current_thread().name))
        if os.path.exists(resultsdir):
            for name in os.listdir(resultsdir):
                os.remove(os.path.join(resultsdir, name))
        else:
            os.makedirs(resultsdir)

        if source.endswith('.src.rpm'):
            builder = SRPMBuilder(mock_config, resultsdir, source)
        else:
            # Otherwise, assume we're building from some scm repo
            builder = SCMBuilder(mock_config, resultsdir, source, artifact_name)
        return self.build_srpm(artifact_name, source, build_id, builder)

    @staticmethod
    def get_disttag_srpm(disttag, module_build):
        # @FIXME
        return KojiModuleBuilder.get_disttag_srpm(disttag, module_build)

    def cancel_build(self, task_id):
        pass

    def list_tasks_for_components(self, component_builds=None, state='active'):
        pass

    def repo_from_tag(cls, config, tag_name, arch):
        pass

    def finalize(self):
        # If the state is "done", run one last createrepo, to include
        # the module metadata. We don't want to do this for failed builds,
        # since that makes it impossible to retry a build manually.
        if self.module.state == models.BUILD_STATES["done"]:
            self._createrepo(include_module_yaml=True)


class BaseBuilder(object):
    def __init__(self, config, resultsdir):
        self.config = config
        self.resultsdir = resultsdir
        self.cmd = ["mock", "-v", "-r", config,
                    "--no-clean",
                    "--resultdir=%s" % resultsdir]

    def build(self, stdout, stderr):
        execute_cmd(self.cmd, stdout=stdout, stderr=stderr)


class SRPMBuilder(BaseBuilder):
    def __init__(self, config, resultsdir, source):
        super(SRPMBuilder, self).__init__(config, resultsdir)
        self.cmd.extend(["--rebuild", source])


class SCMBuilder(BaseBuilder):
    def __init__(self, config, resultsdir, source, artifact_name):
        super(SCMBuilder, self).__init__(config, resultsdir)
        with open(config, "a") as f:
            branch = source.split("?#")[1]
            distgit_cmds = self._get_distgit_commands(source)
            distgit_get = distgit_cmds[0].format(artifact_name)

            # mock-scm cannot checkout particular commit hash, but only branch.
            # We therefore use a command that combines the distgit-command with
            # checking out a particular commit hash.
            # See https://bugzilla.redhat.com/show_bug.cgi?id=1459437 for
            # more info. Once mock-scm supports this feature, we can remove
            # this code.
            distgit_get_branch = \
                "sh -c {}'; git -C {} checkout {}'".format(pipes.quote(distgit_get),
                                                           artifact_name,
                                                           branch)

            f.writelines([
                "config_opts['scm'] = True\n",
                "config_opts['scm_opts']['method'] = 'distgit'\n",
                "config_opts['scm_opts']['package'] = '{}'\n".format(
                    artifact_name),
                "config_opts['scm_opts']['distgit_get'] = {!r}\n".format(
                    distgit_get_branch),
                "config_opts['scm_opts']['distgit_src_get'] = '{}'\n".format(
                    distgit_cmds[1]),
            ])

    def _make_executable(self, path):
        mode = os.stat(path).st_mode
        mode |= (mode & 0o444) >> 2    # copy R bits to X
        os.chmod(path, mode)

    def _get_distgit_commands(self, source):
        for host, cmds in conf.distgits.items():
            if source.startswith(host):
                return cmds
        raise KeyError("No defined commands for {}".format(source))

    def get_average_build_time(self, component):
        """
        Get the average build time of the component from Koji
        :param component: a ComponentBuild object
        :return: a float of the average build time in seconds
        """
        # We currently don't track build times in MBS directly, so we can use Koji to get a decent
        # estimate
        if not self.koji_session:
            # If Koji is not configured on the system, then just return 0.0 for components
            try:
                self.koji_session = KojiModuleBuilder.get_session(self.config, self.owner)
                # If the component has not been built before, then None is returned. Instead,
                # let's return 0.0 so the type is consistent
                return self.koji_session.getAverageBuildDuration(component.package) or 0.0
            except Exception:
                log.debug('The Koji call to getAverageBuildDuration failed. Is Koji properly '
                          'configured?')
                return 0.0
