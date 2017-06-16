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
# Written by Jakub Kadlčík <jkadlcik@redhat.com>


import logging
import os
import re
import koji
import tempfile
import threading
import subprocess
import shutil

from copr.client import CoprClient
from copr.exceptions import CoprRequestException

from module_build_service import log
from module_build_service.models import ModuleBuild
import module_build_service.scm
import module_build_service.utils
import module_build_service.scheduler
import module_build_service.scheduler.consumer

from base import GenericBuilder
from utils import execute_cmd, fake_repo_done_message
from KojiModuleBuilder import KojiModuleBuilder

logging.basicConfig(level=logging.DEBUG)


class CoprModuleBuilder(GenericBuilder):

    """
    See http://blog.samalik.com/copr-in-the-modularity-world/
    especially section "Building a stack"
    """

    backend = "copr"
    _build_lock = threading.Lock()

    @module_build_service.utils.validate_koji_tag('tag_name')
    def __init__(self, owner, module, config, tag_name, components):
        self.owner = owner
        self.config = config
        self.tag_name = tag_name
        self.module = module
        self.module_str = module.name

        self.copr = None
        self.client = CoprModuleBuilder._get_client(config)
        self.client.username = self.owner
        self.chroot = "custom-1-x86_64"
        self.__prep = False


    @classmethod
    def _get_client(cls, config):
        return CoprClient.create_from_file_config(config.copr_config)

    def buildroot_connect(self, groups):
        """
        This is an idempotent call to create or resume and validate the build
        environment.  .build() should immediately fail if .buildroot_connect()
        wasn't called.

        Koji Example: create tag, targets, set build tag inheritance...
        """
        self.copr = self._get_copr_safe()
        self._create_module_safe()

        # @FIXME Not able to use gcc-c++ in chroot (RhBug: 1440889)
        packages = groups["build"] - {"gcc-c++"}
        self._update_chroot(packages=list(packages))

        if self.copr and self.copr.projectname and self.copr.username:
            self.__prep = True
        log.info("%r buildroot sucessfully connected." % self)

    def _get_copr_safe(self):
        kwargs = {
            "ownername": self.module.copr_owner or self.owner,
            "projectname": self.module.copr_project or CoprModuleBuilder._tag_to_copr_name(self.tag_name)
        }

        try:
            return self._get_copr(**kwargs)
        except CoprRequestException:
            self._create_copr(**kwargs)
            return self._get_copr(**kwargs)

    def _get_copr(self, ownername, projectname):
        return self.client.get_project_details(projectname, username=ownername).handle

    def _create_copr(self, ownername, projectname):
        return self.client.create_project(ownername, projectname, [self.chroot])

    def _create_module_safe(self):
        from copr.exceptions import CoprRequestException

        modulemd = tempfile.mktemp()
        self.module.mmd().dump(modulemd)

        kwargs = {
            "username": self.module.copr_owner or self.owner,
            "projectname": self.module.copr_project or CoprModuleBuilder._tag_to_copr_name(self.tag_name),
            "modulemd": modulemd,
            "create": True,
            "build": False,
        }
        try:
            self.client.make_module(**kwargs)
        except CoprRequestException as ex:
            if "already exists" not in ex.message.get("nsv", [""])[0]:
                raise RuntimeError("Buildroot is not prep-ed")
        finally:
            os.remove(modulemd)

    def buildroot_ready(self, artifacts=None):
        """
        :param artifacts=None : a list of artifacts supposed to be in the buildroot
                                (['bash-123-0.el6'])

        returns when the buildroot is ready (or contains the specified artifact)

        This function is here to ensure that the buildroot (repo) is ready and
        contains the listed artifacts if specified.
        """
        # @TODO check whether artifacts are in the buildroot (called from repos.py)
        return True

    def buildroot_add_artifacts(self, artifacts, install=False):
        """
        :param artifacts: list of artifacts to be available or installed
                          (install=False) in the buildroot (e.g  list of $NEVRAS)
        :param install=False: pre-install artifact in the buildroot (otherwise
                              "just make it available for install")

        Example:

        koji tag-build $module-build-tag bash-1.234-1.el6
        if install:
            koji add-group-pkg $module-build-tag build bash
            # This forces install of bash into buildroot and srpm-buildroot
            koji add-group-pkg $module-build-tag srpm-build bash
        """

        # Install the module-build-macros into the buildroot
        # We are using same hack as mock builder does
        for artifact in artifacts:
            if artifact and artifact.startswith("module-build-macros"):
                self._update_chroot(packages=["module-build-macros"])
                break

        # Start of a new batch of builds is triggered by buildsys.repo.done message.
        # However in Copr there is no such thing. Therefore we are going to fake
        # the message when builds are finished
        fake_repo_done_message(self.tag_name)

    def buildroot_add_repos(self, dependencies):
        log.info("%r adding deps on %r" % (self, dependencies))
        # @TODO get architecture from some builder variable
        repos = [self._dependency_repo(d, "x86_64") for d in dependencies]

        # @FIXME
        # Kojipkgs repos have been prematurely disabled without providing any
        # suitable alternative for Copr. This is a temporary workaround until
        # we figure out how to solve this permanently.
        repos.append("https://kojipkgs.fedoraproject.org/compose/"
                     "latest-Fedora-Modular-Rawhide/compose/Server/x86_64/os/")

        self._update_chroot(repos=repos)

    def _update_chroot(self, packages=None, repos=None):
        request = self.client.get_chroot(self.copr.projectname, self.copr.username, self.chroot)
        chroot = request.data["chroot"]
        current_packages = (chroot["buildroot_pkgs"] or "").split()
        current_repos = (chroot["repos"] or "").split()

        def merge(current, new):
            current, new = current or [], new or []
            return " ".join(set(current + new))

        self.client.edit_chroot(self.copr.projectname, self.chroot,
                                ownername=self.copr.username,
                                packages=merge(current_packages, packages),
                                repos=merge(current_repos, repos))

    def _dependency_repo(self, module, arch, backend="copr"):
        try:
            repo = GenericBuilder.tag_to_repo(backend, self.config, module, arch)
            return repo
        except ValueError:
            if backend == "copr":
                return self._dependency_repo(module, arch, "koji")

    def tag_artifacts(self, artifacts):
        pass

    def list_tasks_for_components(self, component_builds=None, state='active'):
        pass

    def build(self, artifact_name, source):
        """
        :param artifact_name : A package name. We can't guess it since macros
                               in the buildroot could affect it, (e.g. software
                               collections).
        :param source : an SCM URL, clearly identifying the build artifact in a
                        repository
        :return 4-tuple of the form (build task id, state, reason, nvr)

        The artifact_name parameter is used in koji add-pkg (and it's actually
        the only reason why we need to pass it). We don't really limit source
        types. The actual source is usually delivered as an SCM URL from
        fedmsg.

        Example
        .build("bash", "git://someurl/bash#damn") #build from SCM URL
        .build("bash", "/path/to/srpm.src.rpm") #build from source RPM
        """
        log.info("Copr build")

        # TODO: If we are sure that this method is thread-safe, we can just
        # remove _build_lock locking.
        with CoprModuleBuilder._build_lock:
            # Git sources are treated specially.
            if source.startswith(("git://", "http://", "https://")):
                return build_from_scm(artifact_name, source, self.config, self.build_srpm)
            else:
                return self.build_srpm(artifact_name, source)

    def build_srpm(self, artifact_name, source, build_id=None):
        if not self.__prep:
            raise RuntimeError("Buildroot is not prep-ed")

        # Build package from `source`
        response = self.client.create_new_build(self.copr.projectname, [source], username=self.copr.username)
        if response.output != "ok":
            log.error(response.error)

        return response.data["ids"][0], koji.BUILD_STATES["BUILDING"], response.message, None

    def build_scm(self, source):
        # @TODO use this method once support on Copr side is finished
        # Copr is currently able to create a build from fedora distgit,
        # but not from custom distgit, such as copr-dist-git
        url, branch = source.split("?#")
        url = (url.replace("git://", "https://")
                  .replace("pkgs.fedoraproject.org", "src.fedoraproject.org/git"))
        self.client.create_new_build_distgit(self.copr.projectname, url, branch=branch, username=self.copr.username)

    def finalize(self):
        modulemd = tempfile.mktemp()
        self.module.mmd().dump(modulemd)

        # Create a module from previous project
        result = self.client.make_module(username=self.copr.username, projectname=self.copr.projectname,
                                         modulemd=modulemd, create=False, build=True)
        os.remove(modulemd)
        if result.output != "ok":
            log.error(result.error)
            return

        log.info(result.message)
        log.info(result.data["modulemd"])

    @staticmethod
    def get_disttag_srpm(disttag, module_build):
        # @FIXME
        return KojiModuleBuilder.get_disttag_srpm(disttag, module_build)

    @property
    def module_build_tag(self):
        # Workaround koji specific code in modules.py
        return {"name": self.tag_name}

    @classmethod
    def repo_from_tag(cls, config, tag_name, arch):
        """
        :param backend: a string representing the backend e.g. 'koji'.
        :param config: instance of module_build_service.config.Config
        :param tag_name: Tag for which the repository is returned
        :param arch: Architecture for which the repository is returned

        Returns URL of repository containing the built artifacts for
        the tag with particular name and architecture.
        """
        # @TODO get the correct user
        # @TODO get the correct project
        owner, project = "@copr", cls._tag_to_copr_name(tag_name)

        # Premise is that tag_name is in name-stream-version format
        name, stream, version = tag_name.rsplit("-", 2)

        try:
            client = cls._get_client(config)
            response = client.get_module_repo(owner, project, name, stream, version, arch).data
            return response["repo"]

        except CoprRequestException as e:
            raise ValueError(e)

    def cancel_build(self, task_id):
        pass

    @classmethod
    @module_build_service.utils.validate_koji_tag('koji_tag')
    def _tag_to_copr_name(cls, koji_tag):
        return koji_tag.replace("+", "-")


def build_from_scm(artifact_name, source, config, build_srpm,
                   data=None, stdout=None, stderr=None):
    """
    Builds the artifact from the SCM based source.

    :param artifact_name: Name of the artifact.
    :param source: SCM URL with artifact's sources (spec file).
    :param config: Config instance.
    :param build_srpm: Method to call to build the RPM from the generate SRPM.
    :param data: Data to be passed to the build_srpm method.
    :param stdout: Python file object to which the stdout of SRPM build
                   command is logged.
    :param stderr: Python file object to which the stderr of SRPM build
                   command is logged.
    """
    ret = (0, koji.BUILD_STATES["FAILED"], "Cannot create SRPM", None)
    td = None

    try:
        log.debug('Cloning source URL: %s' % source)
        url, commit = source.split("?#")
        # Create temp dir and clone the repo there.
        td = tempfile.mkdtemp()
        scm = module_build_service.scm.SCM(source)
        cod = scm.checkout(td)

        cmd = config.mock_build_srpm_cmd.split(" ")
        if is_from_copr(source):
            branch = git_branch_contains(cod, commit)
            if branch != "HEAD":
                git_checkout(cod, branch)
            cmd = ["fedpkg-copr", "--release", branch, "srpm"]

        # Use configured command to create SRPM out of the SCM repo.
        log.debug("Creating SRPM in %s" % cod)
        execute_cmd(cmd, stdout=stdout, stderr=stderr, cwd=cod)

        # Find out the built SRPM and build it normally.
        for f in os.listdir(cod):
            if f.endswith(".src.rpm"):
                log.info("Created SRPM %s" % f)
                source = os.path.join(cod, f)
                ret = build_srpm(artifact_name, source, data)
                break
    except Exception as e:
        log.error("Error while generating SRPM for artifact %s: %s" % (
            artifact_name, str(e)))
        ret = (0, koji.BUILD_STATES["FAILED"], "Cannot create SRPM %s" % str(e), None)
    finally:
        try:
            if td is not None:
                shutil.rmtree(td)
        except Exception as e:
            log.warning(
                "Failed to remove temporary directory {!r}: {}".format(
                    td, str(e)))

    return ret


def git_branch_contains(cod, commit):
    cmd = ["git", "branch", "-r", "--contains", commit]
    out, err = execute_cmd(cmd, cwd=cod, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    branch = out.strip().split("/")[1]
    if " -> " in branch:
        branch = branch.split(" -> ")[0]
    return branch


def is_from_copr(source):
    return bool(re.match("https?://copr-dist-git(-dev)?\.fedorainfracloud\.org", source))


def git_checkout(cod, branch):
    cmd = ["git", "checkout", branch]
    execute_cmd(cmd, cwd=cod)
