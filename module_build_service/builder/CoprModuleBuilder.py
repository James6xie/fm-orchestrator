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
import koji
import tempfile
import threading

from copr.client import CoprClient
from copr.exceptions import CoprRequestException

from module_build_service import log
from module_build_service.models import ModuleBuild
import module_build_service.scm
import module_build_service.utils
import module_build_service.scheduler
import module_build_service.scheduler.consumer

from base import GenericBuilder, build_from_scm
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
        self.module_str = module

        self.copr = None
        self.client = CoprModuleBuilder._get_client(config)
        self.client.username = self.owner
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
        if self.copr and self.copr.projectname and self.copr.username:
            self.__prep = True
        log.info("%r buildroot sucessfully connected." % self)

    def _get_copr_safe(self):
        # @TODO it would be nice if the module build object was passed to Builder __init__
        module = ModuleBuild.query.filter(ModuleBuild.name == self.module_str).one()

        kwargs = {
            "ownername": module.copr_owner or self.owner,
            "projectname": module.copr_project or CoprModuleBuilder._tag_to_copr_name(self.tag_name)
        }

        try:
            return self._get_copr(**kwargs)
        except CoprRequestException:
            self._create_copr(**kwargs)
            return self._get_copr(**kwargs)

    def _get_copr(self, ownername, projectname):
        return self.client.get_project_details(projectname, username=ownername).handle

    def _create_copr(self, ownername, projectname):
        # @TODO fix issues with custom-1-x86_64 and custom-1-i386 chroot and use it
        return self.client.create_project(ownername, projectname, ["fedora-24-x86_64"])

    def _create_module_safe(self):
        from copr.exceptions import CoprRequestException

        # @TODO it would be nice if the module build object was passed to Builder __init__
        module = ModuleBuild.query.filter(ModuleBuild.name == self.module_str).one()
        modulemd = tempfile.mktemp()
        module.mmd().dump(modulemd)

        kwargs = {
            "username": module.copr_owner or self.owner,
            "projectname": module.copr_project or CoprModuleBuilder._tag_to_copr_name(self.tag_name),
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

        # Start of a new batch of builds is triggered by buildsys.repo.done message.
        # However in Copr there is no such thing. Therefore we are going to fake
        # the message when builds are finished
        self._send_repo_done()

    def _send_repo_done(self):
        msg = module_build_service.messaging.KojiRepoChange(
            msg_id='a faked internal message',
            repo_tag=self.tag_name + "-build",
        )
        module_build_service.scheduler.consumer.work_queue_put(msg)

    def buildroot_add_repos(self, dependencies):
        log.info("%r adding deps on %r" % (self, dependencies))
        # @TODO get architecture from some builder variable
        repos = [self._dependency_repo(d, "x86_64") for d in dependencies]
        self.client.modify_project(self.copr.projectname, username=self.copr.username, repos=repos)

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
            if source.startswith("git://"):
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

    def finalize(self):
        modulemd = tempfile.mktemp()
        m1 = ModuleBuild.query.filter(ModuleBuild.name == self.module_str).one()
        m1.mmd().dump(modulemd)

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
    def get_disttag_srpm(disttag):
        # @FIXME
        return KojiModuleBuilder.get_disttag_srpm(disttag)

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


