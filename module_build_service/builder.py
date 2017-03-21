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

from mock import Mock
from kobo.shortcuts import run
import koji
import tempfile
import glob
import datetime
import time
import random
import string
import kobo.rpmlib
import xmlrpclib
import shutil
import subprocess
import threading

import munch
from OpenSSL.SSL import SysCallError

from module_build_service import conf, log, db
from module_build_service.models import ModuleBuild
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

        if isinstance(config.system, Mock):
            return KojiModuleBuilder(owner=owner, module=module,
                                     config=config, **extra)
        elif backend in GenericBuilder.backends:
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

    @abstractmethod
    def is_waiting_for_repo_regen(self):
        """
        :return: True if there is repo regeneration pending for a module.
        """
        raise NotImplementedError()

class KojiModuleBuilder(GenericBuilder):
    """ Koji specific builder class """

    backend = "koji"
    _build_lock = threading.Lock()

    @module_build_service.utils.validate_koji_tag('tag_name')
    def __init__(self, owner, module, config, tag_name, components):
        """
        :param owner: a string representing who kicked off the builds
        :param module: string representing module
        :param config: module_build_service.config.Config instance
        :param tag_name: name of tag for given module
        """
        self.owner = owner
        self.module_str = module
        self.config = config
        self.tag_name = tag_name
        self.__prep = False
        log.debug("Using koji profile %r" % config.koji_profile)
        log.debug("Using koji_config: %s" % config.koji_config)

        self.koji_session = self.get_session(config, owner)
        self.arches = config.koji_arches
        if not self.arches:
            raise ValueError("No koji_arches specified in the config.")

        # These eventually get populated by calling _connect and __prep is set to True
        self.module_tag = None # string
        self.module_build_tag = None # string
        self.module_target = None # A koji target dict

        self.build_priority = config.koji_build_priority
        self.components = components

    def __repr__(self):
        return "<KojiModuleBuilder module: %s, tag: %s>" % (
            self.module_str, self.tag_name)

    def is_waiting_for_repo_regen(self):
        """
        Returns true when there is 'newRepo' task for our tag.
        """
        tasks = []
        state = [koji.TASK_STATES[s] for s in ('FREE', 'OPEN', 'ASSIGNED')]
        for task in self.koji_session.listTasks(opts={'state': state,
                                                      'decode': True,
                                                      'method': 'newRepo'}):
            tag = task['request'][0]
            if tag == self.tag_name:
                return True
        return False

    @module_build_service.utils.retry(wait_on=(IOError, koji.GenericError))
    def buildroot_ready(self, artifacts=None):
        """
        :param artifacts=None - list of nvrs
        Returns True or False if the given artifacts are in the build root.
        """
        assert self.module_target, "Invalid build target"

        tag_id = self.module_target['build_tag']
        repo = self.koji_session.getRepo(tag_id)
        builds = [self.koji_session.getBuild(a) for a in artifacts or []]
        log.info("%r checking buildroot readiness for "
                 "repo: %r, tag_id: %r, artifacts: %r, builds: %r" % (
                     self, repo, tag_id, artifacts, builds))
        ready = bool(koji.util.checkForBuilds(
            self.koji_session,
            tag_id,
            builds,
            repo['create_event'],
            latest=True,
        ))
        if ready:
            log.info("%r buildroot is ready" % self)
        else:
            log.info("%r buildroot is not yet ready.. wait." % self)
        return ready


    @staticmethod
    def get_disttag_srpm(disttag):

        #Taken from Karsten's create-distmacro-pkg.sh
        # - however removed any provides to system-release/redhat-release

        name = 'module-build-macros'
        version = "0.1"
        release = "1"
        today = datetime.date.today().strftime('%a %b %d %Y')

        spec_content = """%global dist {disttag}
Name:       {name}
Version:    {version}
Release:    {release}%dist
Summary:    Package containing macros required to build generic module
BuildArch:  noarch

Group:      System Environment/Base
License:    MIT
URL:        http://fedoraproject.org

%description
This package is used for building modules with a different dist tag.
It provides a file /usr/lib/rpm/macros.d/macro.modules and gets read
after macro.dist, thus overwriting macros of macro.dist like %%dist
It should NEVER be installed on any system as it will really mess up
 updates, builds, ....


%build

%install
mkdir -p %buildroot/%_rpmconfigdir/macros.d 2>/dev/null |:
echo %%dist %dist > %buildroot/%_rpmconfigdir/macros.d/macros.modules
echo %%_module_build 1 >> %buildroot/%_rpmconfigdir/macros.d/macros.modules
chmod 644 %buildroot/%_rpmconfigdir/macros.d/macros.modules


%files
%_rpmconfigdir/macros.d/macros.modules



%changelog
* {today} Fedora-Modularity - {version}-{release}{disttag}
- autogenerated macro by Module Build Service (MBS)
""".format(disttag=disttag, today=today, name=name, version=version, release=release)
        td = tempfile.mkdtemp(prefix="module_build_service-build-macros")
        fd = open(os.path.join(td, "%s.spec" % name), "w")
        fd.write(spec_content)
        fd.close()
        log.debug("Building %s.spec" % name)
        ret, out = run('rpmbuild -bs %s.spec --define "_topdir %s"' % (name, td), workdir=td)
        sdir = os.path.join(td, "SRPMS")
        srpm_paths = glob.glob("%s/*.src.rpm" % sdir)
        assert len(srpm_paths) == 1, "Expected exactly 1 srpm in %s. Got %s" % (sdir, srpm_paths)

        log.debug("Wrote srpm into %s" % srpm_paths[0])
        return srpm_paths[0]

    @staticmethod
    @module_build_service.utils.retry(wait_on=(xmlrpclib.ProtocolError, koji.GenericError))
    def get_session(config, owner):
        koji_config = munch.Munch(koji.read_config(
            profile_name=config.koji_profile,
            user_config=config.koji_config,
        ))

        # In "production" scenarios, our service principal may be blessed to
        # allow us to authenticate as the owner of this request.  But, in local
        # development that is unreasonable so just submit the job as the
        # module_build_service developer.
        proxyuser = owner if config.koji_proxyuser else None

        address = koji_config.server
        authtype = koji_config.authtype
        log.info("Connecting to koji %r with %r.  (proxyuser %r)" % (
            address, authtype, proxyuser))
        koji_session = koji.ClientSession(address, opts=koji_config)
        if authtype == "kerberos":
            ccache = getattr(config, "krb_ccache", None)
            keytab = getattr(config, "krb_keytab", None)
            principal = getattr(config, "krb_principal", None)
            log.debug("  ccache: %r, keytab: %r, principal: %r" % (
                ccache, keytab, principal))
            if keytab and principal:
                koji_session.krb_login(
                    principal=principal,
                    keytab=keytab,
                    ccache=ccache,
                    proxyuser=proxyuser,
                )
            else:
                koji_session.krb_login(ccache=ccache)
        elif authtype == "ssl":
            koji_session.ssl_login(
                os.path.expanduser(koji_config.cert),
                None,
                os.path.expanduser(koji_config.serverca),
                proxyuser=proxyuser,
            )
        else:
            raise ValueError("Unrecognized koji authtype %r" % authtype)

        return koji_session

    def buildroot_connect(self, groups):
        log.info("%r connecting buildroot." % self)

        # Create or update individual tags
        self.module_tag = self._koji_create_tag(
            self.tag_name, self.arches, perm="admin") # the main tag needs arches so pungi can dump it

        self.module_build_tag = self._koji_create_tag(
            self.tag_name + "-build", self.arches, perm="admin")

        self._koji_whitelist_packages(self.components)

        @module_build_service.utils.retry(wait_on=SysCallError, interval=5)
        def add_groups():
            return self._koji_add_groups_to_tag(
                dest_tag=self.module_build_tag,
                groups=groups,
            )
        add_groups()

        # Add main build target.
        self.module_target = self._koji_add_target(self.tag_name,
                                                   self.module_build_tag,
                                                   self.module_tag)

        # Add -repo target, so Kojira creates RPM repository with built
        # module for us.
        self._koji_add_target(self.tag_name + "-repo", self.module_tag,
                              self.module_tag)

        self.__prep = True
        log.info("%r buildroot sucessfully connected." % self)

    def buildroot_add_repos(self, dependencies):
        log.info("%r adding deps on %r" % (self, dependencies))
        self._koji_add_many_tag_inheritance(self.module_build_tag, dependencies)

    def _get_tagged_nvrs(self, tag):
        """
        Returns set of NVR strings tagged in tag `tag`.
        """
        tagged = self.koji_session.listTagged(tag)
        tagged_nvrs = set(build["nvr"] for build in tagged)
        return tagged_nvrs

    def buildroot_add_artifacts(self, artifacts, install=False):
        """
        :param artifacts - list of artifacts to add to buildroot
        :param install=False - force install artifact (if it's not dragged in as dependency)

        This method is safe to call multiple times.
        """
        log.info("%r adding artifacts %r" % (self, artifacts))
        build_tag = self._get_tag(self.module_build_tag)['id']

        tagged_nvrs = self._get_tagged_nvrs(self.module_build_tag['name'])

        for nvr in artifacts:
            if nvr in tagged_nvrs:
                continue

            log.info("%r tagging %r into %r" % (self, nvr, build_tag))
            self.koji_session.tagBuild(build_tag, nvr)

            if not install:
                continue

            for group in ('srpm-build', 'build'):
                name = kobo.rpmlib.parse_nvr(nvr)['name']
                log.info("%r adding %s to group %s" % (self, name, group))
                self.koji_session.groupPackageListAdd(build_tag, group, name)

    def tag_artifacts(self, artifacts):
        dest_tag = self._get_tag(self.module_tag)['id']

        tagged_nvrs = self._get_tagged_nvrs(self.module_tag['name'])

        for nvr in artifacts:
            if nvr in tagged_nvrs:
                continue

            log.info("%r tagging %r into %r" % (self, nvr, dest_tag))
            self.koji_session.tagBuild(dest_tag, nvr)

    def wait_task(self, task_id):
        """
        :param task_id
        :return - task result object
        """

        log.info("Waiting for task_id=%s to finish" % task_id)

        timeout = 60 * 60 # 60 minutes
        @module_build_service.utils.retry(timeout=timeout, wait_on=koji.GenericError)
        def get_result():
            log.debug("Waiting for task_id=%s to finish" % task_id)
            task = self.koji_session.getTaskResult(task_id)
            log.info("Done waiting for task_id=%s to finish" % task_id)
            return task

        return get_result()

    def _get_task_by_artifact(self, artifact_name):
        """
        :param artifact_name: e.g. bash

        Searches for a tagged package inside module tag.

        Returns task_id or None.

        TODO: handle builds with skip_tag (not tagged at all)
        """
        # yaml file can hold only one reference to a package name, so
        # I expect that we can have only one build of package within single module
        # Rules for searching:
        #  * latest: True so I can return only single task_id.
        #  * we do want only build explicitly tagged in the module tag (inherit: False)

        opts = {'latest': True, 'package': artifact_name, 'inherit': False}
        tagged = self.koji_session.listTagged(self.module_tag['name'], **opts)

        if tagged:
            assert len(tagged) == 1, "Expected exactly one item in list. Got %s" % tagged
            return tagged[0]

        return None

    def build(self, artifact_name, source):
        """
        :param source : scmurl to spec repository
        : param artifact_name: name of artifact (which we couldn't get from spec due involved macros)
        :return 4-tuple of the form (koji build task id, state, reason, nvr)
        """

        # TODO: If we are sure that this method is thread-safe, we can just
        # remove _build_lock locking.
        with KojiModuleBuilder._build_lock:
            # This code supposes that artifact_name can be built within the component
            # Taken from /usr/bin/koji
            def _unique_path(prefix):
                """
                Create a unique path fragment by appending a path component
                to prefix.  The path component will consist of a string of letter and numbers
                that is unlikely to be a duplicate, but is not guaranteed to be unique.
                """
                # Use time() in the dirname to provide a little more information when
                # browsing the filesystem.
                # For some reason repr(time.time()) includes 4 or 5
                # more digits of precision than str(time.time())
                # Unnamed Engineer: Guido v. R., I am disappoint
                return '%s/%r.%s' % (prefix, time.time(),
                                    ''.join([random.choice(string.ascii_letters) for i in range(8)]))

            if not self.__prep:
                raise RuntimeError("Buildroot is not prep-ed")

            # Skip existing builds
            task_info = self._get_task_by_artifact(artifact_name)
            if task_info:
                log.info("skipping build of %s. Build already exists (task_id=%s), via %s" % (
                    source, task_info['task_id'], self))
                return task_info['task_id'], koji.BUILD_STATES['COMPLETE'], 'Build already exists.', task_info['nvr']

            self._koji_whitelist_packages([artifact_name,])
            if '://' not in source:
                #treat source as an srpm and upload it
                serverdir = _unique_path('cli-build')
                callback = None
                self.koji_session.uploadWrapper(source, serverdir, callback=callback)
                source = "%s/%s" % (serverdir, os.path.basename(source))

            # When "koji_build_macros_target" is set, we build the
            # module-build-macros in this target instead of the self.module_target.
            # The reason is that it is faster to build this RPM in
            # already existing shared target, because Koji does not need to do
            # repo-regen.
            if (artifact_name == "module-build-macros"
                    and self.config.koji_build_macros_target):
                module_target = self.config.koji_build_macros_target
            else:
                module_target = self.module_target['name']

            build_opts = {"skip_tag": True,
                          "mbs_artifact_name": artifact_name,
                          "mbs_module_target": module_target}

            task_id = self.koji_session.build(source, module_target, build_opts,
                                            priority=self.build_priority)
            log.info("submitted build of %s (task_id=%s), via %s" % (
                source, task_id, self))
            if task_id:
                state = koji.BUILD_STATES['BUILDING']
                reason = "Submitted %s to Koji" % (artifact_name)
            else:
                state = koji.BUILD_STATES['FAILED']
                reason = "Failed to submit artifact %s to Koji" % (artifact_name)
            return task_id, state, reason, None

    def cancel_build(self, task_id):
        self.koji_session.cancelTask(task_id)

    @classmethod
    def repo_from_tag(cls, config, tag_name, arch):
        """
        :param config: instance of module_build_service.config.Config
        :param tag_name: Tag for which the repository is returned
        :param arch: Architecture for which the repository is returned

        Returns URL of repository containing the built artifacts for
        the tag with particular name and architecture.
        """
        return "%s/%s/latest/%s" % (config.koji_repository_url, tag_name, arch)

    @module_build_service.utils.validate_koji_tag('tag', post='')
    def _get_tag(self, tag, strict=True):
        if isinstance(tag, dict):
            tag = tag['name']
        taginfo = self.koji_session.getTag(tag)
        if not taginfo:
            if strict:
                raise SystemError("Unknown tag: %s" % tag)
        return taginfo

    @module_build_service.utils.validate_koji_tag(['tag_name', 'parent_tags'], post='')
    def _koji_add_many_tag_inheritance(self, tag_name, parent_tags):
        tag = self._get_tag(tag_name)
        # highest priority num is at the end
        inheritance_data = sorted(self.koji_session.getInheritanceData(tag['name']) or [], key=lambda k: k['priority'])
        # Set initial priority to last record in inheritance data or 0
        priority = 0
        if inheritance_data:
            priority = inheritance_data[-1]['priority'] + 10
        def record_exists(parent_id, data):
            for item in data:
                if parent_id == item['parent_id']:
                    return True
            return False

        for parent in parent_tags: # We expect that they're sorted
            parent = self._get_tag(parent)
            if record_exists(parent['id'], inheritance_data):
                continue

            parent_data = {}
            parent_data['parent_id'] = parent['id']
            parent_data['priority'] = priority
            parent_data['maxdepth'] = None
            parent_data['intransitive'] = False
            parent_data['noconfig'] = False
            parent_data['pkg_filter'] = ''
            inheritance_data.append(parent_data)
            priority += 10

        if inheritance_data:
            self.koji_session.setInheritanceData(tag['id'], inheritance_data)

    @module_build_service.utils.validate_koji_tag('dest_tag')
    def _koji_add_groups_to_tag(self, dest_tag, groups=None):
        """
        :param build_tag_name
        :param groups: A dict {'group' : [package, ...]}
        """
        log.debug("Adding groups=%s to tag=%s" % (list(groups), dest_tag))
        if groups and not isinstance(groups, dict):
            raise ValueError("Expected dict {'group' : [str(package1), ...]")

        dest_tag = self._get_tag(dest_tag)['name']
        existing_groups = dict([
            (p['name'], p['group_id'])
            for p in self.koji_session.getTagGroups(dest_tag, inherit=False)
        ])

        for group, packages in groups.items():
            group_id = existing_groups.get(group, None)
            if group_id is not None:
                log.debug("Group %s already exists for tag %s. Skipping creation." % (group, dest_tag))
                continue

            self.koji_session.groupListAdd(dest_tag, group)
            log.debug("Adding %d packages into group=%s tag=%s" % (len(packages), group, dest_tag))

            # This doesn't fail in case that it's already present in the group. This should be safe
            for pkg in packages:
                self.koji_session.groupPackageListAdd(dest_tag, group, pkg)


    @module_build_service.utils.validate_koji_tag('tag_name')
    def _koji_create_tag(self, tag_name, arches=None, perm=None):
        """
        :param tag_name: name of koji tag
        :param arches: list of architectures for the tag
        :param perm: permissions for the tag (used in lock-tag)

        This call is safe to call multiple times.
        """

        log.debug("Ensuring existence of tag='%s'." % tag_name)
        taginfo = self.koji_session.getTag(tag_name)

        if not taginfo:
            self.koji_session.createTag(tag_name)
            taginfo = self._get_tag(tag_name)

        opts = {}
        if arches:
            if not isinstance(arches, list):
                raise ValueError("Expected list or None on input got %s" % type(arches))

            current_arches = []
            if taginfo['arches']: # None if none
                current_arches = taginfo['arches'].split() # string separated by empty spaces

            if set(arches) != set(current_arches):
                opts['arches'] = " ".join(arches)

        if perm:
            if taginfo['locked']:
                raise SystemError("Tag %s: master lock already set. Can't edit tag" % taginfo['name'])

            perm_ids = dict([(p['name'], p['id']) for p in self.koji_session.getAllPerms()])
            if perm not in perm_ids:
                raise ValueError("Unknown permissions %s" % perm)

            perm_id = perm_ids[perm]
            if taginfo['perm'] not in (perm_id, perm): # check either id or the string
                opts['perm'] = perm_id

        opts['extra'] = {
            'mock.package_manager': 'dnf',
        }

        # edit tag with opts
        self.koji_session.editTag2(tag_name, **opts)
        return self._get_tag(tag_name) # Return up2date taginfo

    def _get_component_owner(self, package):
        user = self.koji_session.getLoggedInUser()['name']
        if not self.koji_session.getUser(user):
            raise ValueError("Unknown user %s" % user)
        return user

    def _koji_whitelist_packages(self, packages, tags = None):
        if not tags:
            tags = [self.module_tag, self.module_build_tag]

        # TODO: This has to be done per-package or just without the need
        # to pass the `packages` to it depending on the result of
        # issue #337.
        owner = self._get_component_owner(packages[0])

        # This will help with potential resubmiting of failed builds
        pkglists = {}
        for tag in tags:
            pkglists[tag['id']] = dict([(p['package_name'], p['package_id']) for p in self.koji_session.listPackages(tagID=tag['id'])])

        self.koji_session.multicall = True
        for tag in tags:
            pkglist = pkglists[tag['id']]
            to_add = []
            for package in packages:
                if pkglist.get(package, None):
                    log.debug("%s Package %s is already whitelisted." % (self, package))
                    continue

                self.koji_session.packageListAdd(tag['name'], package, owner)
        self.koji_session.multiCall(strict=True)

    @module_build_service.utils.validate_koji_tag(['build_tag', 'dest_tag'])
    def _koji_add_target(self, name, build_tag, dest_tag):
        """
        :param name: target name
        :param build-tag: build_tag name
        :param dest_tag: dest tag name

        This call is safe to call multiple times. Raises SystemError() if the existing target doesn't match params.
        The reason not to touch existing target, is that we don't want to accidentaly alter a target
        which was already used to build some artifacts.
        """
        build_tag = self._get_tag(build_tag)
        dest_tag = self._get_tag(dest_tag)
        target_info = self.koji_session.getBuildTarget(name)

        barches = build_tag.get("arches", None)
        assert barches, "Build tag %s has no arches defined." % build_tag['name']

        if not target_info:
            target_info = self.koji_session.createBuildTarget(name, build_tag['name'], dest_tag['name'])

        else: # verify whether build and destination tag matches
            if build_tag['name'] != target_info['build_tag_name']:
                raise SystemError("Target references unexpected build_tag_name. Got '%s', expected '%s'. Please contact administrator." % (target_info['build_tag_name'], build_tag['name']))
            if dest_tag['name'] != target_info['dest_tag_name']:
                raise SystemError("Target references unexpected dest_tag_name. Got '%s', expected '%s'. Please contact administrator." % (target_info['dest_tag_name'], dest_tag['name']))

        return self.koji_session.getBuildTarget(name)

    def list_tasks_for_components(self, component_builds=None, state='active'):
        """
        :param component_builds: list of component builds which we want to check
        :param state: limit the check only for Koji tasks in the given state
        :return: list of Koji tasks

        List Koji tasks ('active' by default) for component builds.
        """

        component_builds = component_builds or []
        if state == 'active':
            states = [koji.TASK_STATES['FREE'],
                      koji.TASK_STATES['OPEN'],
                      koji.TASK_STATES['ASSIGNED']]
        elif state.upper() in koji.TASK_STATES:
            states = [koji.TASK_STATES[state.upper()]]
        else:
            raise ValueError("State {} is not valid within Koji task states."
                             .format(state))

        tasks = []
        for task in self.koji_session.listTasks(opts={'state': states,
                                                      'decode': True,
                                                      'method': 'build'}):
            task_opts = task['request'][-1]
            assert isinstance(task_opts, dict), "Task options shall be a dict."
            if 'scratch' in task_opts and task_opts['scratch']:
                continue
            if 'mbs_artifact_name' not in task_opts:
                task_opts['mbs_artifact_name'] = None
            if 'mbs_module_target' not in task_opts:
                task_opts['mbs_module_target'] = None
            for c in component_builds:
                # TODO: https://pagure.io/fm-orchestrator/issue/397
                # Subj: Do not mix target/tag when looking for component builds
                if (c.package == task_opts['mbs_artifact_name'] and
                    c.module_build.koji_tag == task_opts['mbs_module_target']):
                    tasks.append(task)

        return tasks


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
        from copr.client import CoprClient
        return CoprClient.create_from_file_config(config.copr_config)

    def buildroot_connect(self, groups):
        """
        This is an idempotent call to create or resume and validate the build
        environment.  .build() should immediately fail if .buildroot_connect()
        wasn't called.

        Koji Example: create tag, targets, set build tag inheritance...
        """
        self.copr = self._get_copr_safe()
        if self.copr and self.copr.projectname and self.copr.username:
            self.__prep = True
        log.info("%r buildroot sucessfully connected." % self)

    def _get_copr_safe(self):
        from copr.exceptions import CoprRequestException

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
        pass

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

    def is_waiting_for_repo_regen(self):
        return False

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

    def _wait_until_all_builds_are_finished(self, module):
        while True:
            states = {b: self.client.get_build_details(b.task_id).status for b in module.component_builds}
            if "failed" in states.values():
                raise ValueError("Some builds failed")

            if not filter(lambda x: x != "succeeded", states.values()):
                return

            seconds = 60
            log.info("Going to sleep for {}s to wait until builds in copr are finished".format(seconds))
            time.sleep(seconds)

    def finalize(self):
        modulemd = tempfile.mktemp()
        m1 = ModuleBuild.query.filter(ModuleBuild.name == self.module_str).one()
        m1.mmd().dump(modulemd)

        # Wait until all builds are finished
        # We shouldn't do this once the fedmsg on copr is done
        from copr.exceptions import CoprRequestException
        try:
            self._wait_until_all_builds_are_finished(m1)
        except (CoprRequestException, ValueError):
            return log.info("Missing builds, not going to create a module")

        # Create a module from previous project
        kwargs = {"username": self.copr.username, "projectname": self.copr.projectname, "modulemd": modulemd}
        result = self.client.create_new_build_module(**kwargs)
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

        from copr.exceptions import CoprRequestException
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


class MockModuleBuilder(GenericBuilder):
    """
    See http://blog.samalik.com/copr-in-the-modularity-world/
    especially section "Building a stack"
    """

    backend = "mock"
    # Global build_id/task_id we increment when new build is executed.
    _build_id_lock = threading.Lock()
    _build_id = 1
    _config_lock = threading.Lock()

    MOCK_CONFIG_TEMPLATE = """
config_opts['root'] = '$root'
config_opts['target_arch'] = '$arch'
config_opts['legal_host_arches'] = ('$arch',)
config_opts['chroot_setup_cmd'] = 'install $group'
config_opts['dist'] = ''
config_opts['extra_chroot_dirs'] = [ '/run/lock', ]
config_opts['releasever'] = ''
config_opts['package_manager'] = 'dnf'
config_opts['nosync'] = True

config_opts['yum.conf'] = \"\"\"
$yum_conf
\"\"\"
"""

    MOCK_YUM_CONF_TEMPLATE = """
[main]
keepcache=1
debuglevel=2
reposdir=/dev/null
logfile=/var/log/yum.log
retries=20
obsoletes=1
gpgcheck=0
assumeyes=1
syslog_ident=mock
syslog_device=
install_weak_deps=0
metadata_expire=3600
mdpolicy=group:primary

# repos

"""

    @module_build_service.utils.validate_koji_tag('tag_name')
    def __init__(self, owner, module, config, tag_name, components):
        self.module_str = module
        self.tag_name = tag_name
        self.config = config
        self.groups = []
        self.arch = "x86_64" # TODO: We may need to change that in the future
        self.yum_conf = MockModuleBuilder.MOCK_YUM_CONF_TEMPLATE

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

    def _createrepo(self):
        """
        Creates the repository using "createrepo_c" command in the resultsdir.
        """
        log.debug("Creating repository in %s" % self.resultsdir)
        path = self.resultsdir
        if os.path.exists(path + '/repodata/repomd.xml'):
            comm = ['/usr/bin/createrepo_c', '--update', path]
        else:
            comm = ['/usr/bin/createrepo_c', path]
        cmd = subprocess.Popen(
            comm, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = cmd.communicate()
        return out, err

    def _add_repo(self, name, baseurl, extra = ""):
        """
        Adds repository to Mock config file. Call _write_mock_config() to
        actually write the config file to filesystem.
        """
        self.yum_conf += "[%s]\n" % name
        self.yum_conf += "name=%s\n" % name
        self.yum_conf += "baseurl=%s\n" % baseurl
        self.yum_conf += extra
        self.yum_conf += "enabled=1\n"

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
            config = str(MockModuleBuilder.MOCK_CONFIG_TEMPLATE)
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

        self._send_repo_done()

    def _send_repo_done(self):
        msg = module_build_service.messaging.KojiRepoChange(
            msg_id='a faked internal message',
            repo_tag=self.tag_name + "-build",
        )
        module_build_service.scheduler.consumer.work_queue_put(msg)

    def tag_artifacts(self, artifacts):
        pass

    def buildroot_add_repos(self, dependencies):
        # TODO: We support only dependencies from Koji here. This should be
        # extended to Copr in the future.
        self._load_mock_config()
        for tag in dependencies:
            baseurl = KojiModuleBuilder.repo_from_tag(self.config, tag, self.arch)
            self._add_repo(tag, baseurl)
        self._write_mock_config()

    def _send_build_change(self, state, source, build_id):
        nvr = kobo.rpmlib.parse_nvr(source)

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

    def build_srpm(self, artifact_name, source, build_id):
        """
        Builds the artifact from the SRPM.
        """
        state = koji.BUILD_STATES['BUILDING']

        # Use the mock config associated with this thread.
        mock_config = os.path.join(self.configdir,
            "mock-%s.cfg" % str(threading.current_thread().name))

        # Clear resultsdir associated with this thread or in case it does not
        # exist, create it.
        resultsdir = os.path.join(self.resultsdir,
            str(threading.current_thread().name))
        if os.path.exists(resultsdir):
            for name in os.listdir(resultsdir):
                os.remove(os.path.join(resultsdir, name))
        else:
            os.makedirs(resultsdir)

        # Open the logs to which we will forward mock stdout/stderr.
        mock_stdout_log = open(os.path.join(self.resultsdir,
            artifact_name + "-mock-stdout.log"), "w")
        mock_stderr_log = open(os.path.join(self.resultsdir,
            artifact_name + "-mock-stderr.log"), "w")

        try:
            # Initialize mock.
            _execute_cmd(["mock", "-v", "-r", mock_config, "--init"],
                         stdout=mock_stdout_log, stderr=mock_stderr_log)

            # Start the build and store results to resultsdir
            _execute_cmd(["mock", "-v", "-r", mock_config,
                               "--no-clean", "--rebuild", source,
                               "--resultdir=%s" % resultsdir],
                         stdout=mock_stdout_log, stderr=mock_stderr_log)

            # Emit messages simulating complete build. These messages
            # are put in the scheduler's work queue and are handled
            # by MBS after the build_srpm() method returns and scope gets
            # back to scheduler.main.main() method.
            state = koji.BUILD_STATES['COMPLETE']
            self._send_build_change(state, source, build_id)

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
            self._send_build_change(state, source,
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
            shutil.copyfile(os.path.join(resultsdir, name), os.path.join(self.resultsdir, name))

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

        # Get the build-id in thread-safe manner.
        build_id = None
        with MockModuleBuilder._build_id_lock:
            MockModuleBuilder._build_id += 1
            build_id = int(MockModuleBuilder._build_id)

        # Git sources are treated specially.
        if source.startswith("git://"):
            # Open the srpm-stdout and srpm-stderr logs and build from SCM.
            srpm_stdout_fn = os.path.join(self.resultsdir,
                artifact_name + "-srpm-stdout.log")
            srpm_stderr_fn = os.path.join(self.resultsdir,
                artifact_name + "-srpm-stderr.log")
            with open(srpm_stdout_fn, "w") as srpm_stdout_log, open(srpm_stderr_fn, "w") as srpm_stderr_log:
                return build_from_scm(artifact_name, source,
                    self.config, self.build_srpm, data=build_id,
                    stdout=srpm_stdout_log, stderr=srpm_stderr_log)
        else:
            return self.build_srpm(artifact_name, source, build_id)

    @staticmethod
    def get_disttag_srpm(disttag):
        # @FIXME
        return KojiModuleBuilder.get_disttag_srpm(disttag)

    def cancel_build(self, task_id):
        pass

    def list_tasks_for_components(self, component_builds=None, state='active'):
        pass

    def is_waiting_for_repo_regen(self):
        return True


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


GenericBuilder.register_backend_class(KojiModuleBuilder)
GenericBuilder.register_backend_class(CoprModuleBuilder)
GenericBuilder.register_backend_class(MockModuleBuilder)
