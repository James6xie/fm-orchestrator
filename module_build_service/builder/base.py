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
# Written by Petr Šabata <contyk@redhat.com>
#            Luboš Kocman <lkocman@redhat.com>

"""Generic component build functions."""

# TODO: Query the PDC to find what modules satisfy the build dependencies and
#       their tag names.
# TODO: Ensure the RPM %dist tag is set according to the policy.

import six
from abc import ABCMeta, abstractmethod
import logging
import os
import koji
import tempfile
import shutil
import subprocess

from module_build_service import conf, log, db
from module_build_service import pdc
import module_build_service.scm
import module_build_service.utils
import module_build_service.scheduler
import module_build_service.scheduler.consumer


from requests.exceptions import ConnectionError

logging.basicConfig(level=logging.DEBUG)

"""
Example workflows - helps to see the difference in implementations
Copr workflow:

1) create project (input: name, chroot deps:  e.g. epel7)
2) optional: selects project dependencies e.g. epel-7
3) build package a.src.rpm # package is automatically added into buildroot
   after it's finished
4) createrepo (package.a.src.rpm is available)

Koji workflow

1) create tag, and build-tag
2) create target out of ^tag and ^build-tag
3) run regen-repo to have initial repodata (happens automatically)
4) build module-build-macros which provides "dist" macro
5) tag module-build-macro into buildroot
6) wait for module-build-macro to be available in buildroot
7) build all components from scmurl
8) (optional) wait for selected builds to be available in buildroot

"""
class GenericBuilder(six.with_metaclass(ABCMeta)):
    """
    External Api for builders

    Example usage:
        config = module_build_service.config.Config()
        builder = Builder(module="testmodule-1.2-3", backend="koji", config)
        builder.buildroot_connect()
        builder.build(artifact_name="bash",
                      source="git://pkgs.stg.fedoraproject.org/rpms/bash"
                             "?#70fa7516b83768595a4f3280ae890a7ac957e0c7")

        ...
        # E.g. on some other worker ... just resume buildroot that was initially created
        builder = Builder(module="testmodule-1.2-3", backend="koji", config)
        builder.buildroot_connect()
        builder.build(artifact_name="not-bash",
                      source="git://pkgs.stg.fedoraproject.org/rpms/not-bash"
                             "?#70fa7516b83768595a4f3280ae890a7ac957e0c7")
        # wait until this particular bash is available in the buildroot
        builder.buildroot_ready(artifacts=["bash-1.23-el6"])
        builder.build(artifact_name="not-not-bash",
                      source="git://pkgs.stg.fedoraproject.org/rpms/not-not-bash"
                             "?#70fa7516b83768595a4f3280ae890a7ac957e0c7")

    """

    backend = "generic"
    backends = {}

    @classmethod
    def register_backend_class(cls, backend_class):
        GenericBuilder.backends[backend_class.backend] = backend_class

    @classmethod
    def create(cls, owner, module, backend, config, **extra):
        """
        :param owner: a string representing who kicked off the builds
        :param module: a module string e.g. 'testmodule-1.0'
        :param backend: a string representing backend e.g. 'koji'
        :param config: instance of module_build_service.config.Config

        Any additional arguments are optional extras which can be passed along
        and are implementation-dependent.
        """
        if backend in GenericBuilder.backends:
            return GenericBuilder.backends[backend](owner=owner, module=module,
                                                    config=config, **extra)
        else:
            raise ValueError("Builder backend='%s' not recognized" % backend)

    @classmethod
    def create_from_module(cls, session, module, config):
        """
        Creates new GenericBuilder instance based on the data from module
        and config and connects it to buildroot.

        :param session: SQLAlchemy databa session.
        :param module: module_build_service.models.ModuleBuild instance.
        :param config: module_build_service.config.Config instance.
        """
        components = [c.package for c in module.component_builds]
        builder = GenericBuilder.create(
            module.owner, module.name, config.system, config,
            tag_name=module.koji_tag, components=components)
        groups = GenericBuilder.default_buildroot_groups(session, module)
        builder.buildroot_connect(groups)
        return builder

    @classmethod
    def tag_to_repo(cls, backend, config, tag_name, arch):
        """
        :param backend: a string representing the backend e.g. 'koji'.
        :param config: instance of module_build_service.config.Config
        :param tag_name: Tag for which the repository is returned
        :param arch: Architecture for which the repository is returned

        Returns URL of repository containing the built artifacts for
        the tag with particular name and architecture.
        """
        if backend in GenericBuilder.backends:
            return GenericBuilder.backends[backend].repo_from_tag(
                config, tag_name, arch)
        else:
            raise ValueError("Builder backend='%s' not recognized" % backend)

    @abstractmethod
    def buildroot_connect(self, groups):
        """
        This is an idempotent call to create or resume and validate the build
        environment.  .build() should immediately fail if .buildroot_connect()
        wasn't called.

        Koji Example: create tag, targets, set build tag inheritance...
        """
        raise NotImplementedError()

    @abstractmethod
    def buildroot_ready(self, artifacts=None):
        """
        :param artifacts=None : a list of artifacts supposed to be in the buildroot
                                (['bash-123-0.el6'])

        returns when the buildroot is ready (or contains the specified artifact)

        This function is here to ensure that the buildroot (repo) is ready and
        contains the listed artifacts if specified.
        """
        raise NotImplementedError()

    @abstractmethod
    def buildroot_add_repos(self, dependencies):
        """
        :param dependencies: a list of modules represented as a list of dicts,
                             like:
                             [{'name': ..., 'version': ..., 'release': ...}, ...]

        Make an additional repository available in the buildroot. This does not
        necessarily have to directly install artifacts (e.g. koji), just make
        them available.

        E.g. the koji implementation of the call uses PDC to get koji_tag
        associated with each module dep and adds the tag to $module-build tag
        inheritance.
        """
        raise NotImplementedError()

    @abstractmethod
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
        raise NotImplementedError()

    @abstractmethod
    def tag_artifacts(self, artifacts):
        """
        :param artifacts: list of artifacts (NVRs) to be tagged

        Adds the artifacts to tag associated with this module build.
        """
        raise NotImplementedError()

    @abstractmethod
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

        Warning: This function must be thread-safe.

        Example
        .build("bash", "git://someurl/bash#damn") #build from SCM URL
        .build("bash", "/path/to/srpm.src.rpm") #build from source RPM
        """
        raise NotImplementedError()

    @abstractmethod
    def cancel_build(self, task_id):
        """
        :param task_id: Task ID returned by the build method.

        Cancels the build.
        """
        raise NotImplementedError()

    def finalize(self):
        """
        :return: None

        This method is supposed to be called after all module builds are
        successfully finished.

        It could be utilized for various purposes such as cleaning or
        running additional build-system based operations on top of
        finished builds (e.g. for copr - composing them into module)
        """
        pass

    @classmethod
    @abstractmethod
    def repo_from_tag(self, config, tag_name, arch):
        """
        :param config: instance of module_build_service.config.Config
        :param tag_name: Tag for which the repository is returned
        :param arch: Architecture for which the repository is returned

        Returns URL of repository containing the built artifacts for
        the tag with particular name and architecture.
        """
        raise NotImplementedError()

    @classmethod
    @module_build_service.utils.retry(wait_on=(ConnectionError))
    def default_buildroot_groups(cls, session, module):
        try:
            pdc_session = pdc.get_pdc_client_session(conf)
            pdc_groups = pdc.resolve_profiles(pdc_session, module.mmd(),
                                              ('buildroot', 'srpm-buildroot'))
            groups = {
                'build': pdc_groups['buildroot'],
                'srpm-build': pdc_groups['srpm-buildroot'],
            }
        except ValueError:
            reason = "Failed to gather buildroot groups from SCM."
            log.exception(reason)
            module.transition(conf, state="failed", state_reason=reason)
            session.commit()
            raise
        return groups

    @abstractmethod
    def list_tasks_for_components(self, component_builds=None, state='active'):
        """
        :param component_builds: list of component builds which we want to check
        :param state: limit the check only for tasks in the given state
        :return: list of tasks

        This method is supposed to list tasks ('active' by default)
        for component builds.
        """
        raise NotImplementedError()






def build_from_scm(artifact_name, source, config, build_srpm,
                   data = None, stdout=None, stderr=None):
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
        # Create temp dir and clone the repo there.
        td = tempfile.mkdtemp()
        scm = module_build_service.scm.SCM(source)
        cod = scm.checkout(td)

        # Use configured command to create SRPM out of the SCM repo.
        log.debug("Creating SRPM in %s" % cod)
        _execute_cmd(config.mock_build_srpm_cmd.split(" "),
                     stdout=stdout, stderr=stderr, cwd=cod)

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


def _execute_cmd(args, stdout = None, stderr = None, cwd = None):
    """
    Executes command defined by `args`. If `stdout` or `stderr` is set to
    Python file object, the stderr/stdout output is redirecter to that file.
    If `cwd` is set, current working directory is set accordingly for the
    executed command.

    :param args: list defining the command to execute.
    :param stdout: Python file object to redirect the stdout to.
    :param stderr: Python file object to redirect the stderr to.
    :param cwd: string defining the current working directory for command.
    :raises RuntimeError: Raised when command exits with non-zero exit code.
    """
    out_log_msg = ""
    if stdout:
        out_log_msg += ", stdout log: %s" % stdout.name
    if stderr:
        out_log_msg += ", stderr log: %s" % stderr.name

    log.info("Executing command: %s%s" % (args, out_log_msg))
    proc = subprocess.Popen(args, stdout=stdout, stderr=stderr, cwd=cwd)
    proc.communicate()

    if proc.returncode != 0:
        err_msg = "Command '%s' returned non-zero value %d%s" % (args, proc.returncode, out_log_msg)
        raise RuntimeError(err_msg)


