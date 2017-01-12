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

import munch
from OpenSSL.SSL import SysCallError

from module_build_service import conf, log, db
from module_build_service.models import ModuleBuild
from module_build_service import pdc
import module_build_service.scm
import module_build_service.utils
import module_build_service.scheduler
import module_build_service.scheduler.consumer

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
    def tag_to_repo(cls, backend, config, tag_name, arch):
        """
        :param backend: a string representing the backend e.g. 'koji'.
        :param config: instance of rida.config.Config
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
        :param config: instance of rida.config.Config
        :param tag_name: Tag for which the repository is returned
        :param arch: Architecture for which the repository is returned

        Returns URL of repository containing the built artifacts for
        the tag with particular name and architecture.
        """
        raise NotImplementedError()

    @classmethod
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

class KojiModuleBuilder(GenericBuilder):
    """ Koji specific builder class """

    backend = "koji"

    def __init__(self, owner, module, config, tag_name):
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

    def __repr__(self):
        return "<KojiModuleBuilder module: %s, tag: %s>" % (
            self.module_str, self.tag_name)

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
- autogenerated macro by Rida "The Orchestrator"
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
        tags = [self._get_tag("module-" + d)['name'] for d in dependencies]
        log.info("%r adding deps on %r" % (self, tags))
        self._koji_add_many_tag_inheritance(self.module_build_tag, tags)

    def buildroot_add_artifacts(self, artifacts, install=False):
        """
        :param artifacts - list of artifacts to add to buildroot
        :param install=False - force install artifact (if it's not dragged in as dependency)

        This method is safe to call multiple times.
        """
        log.info("%r adding artifacts %r" % (self, artifacts))
        build_tag = self._get_tag(self.module_build_tag)['id']

        for nvr in artifacts:
            log.info("%r tagging %r into %r" % (self, nvr, build_tag))
            self.koji_session.tagBuild(build_tag, nvr, force=True)

            if not install:
                continue

            for group in ('srpm-build', 'build'):
                name = kobo.rpmlib.parse_nvr(nvr)['name']
                log.info("%r adding %s to group %s" % (self, name, group))
                self.koji_session.groupPackageListAdd(build_tag, group, name)

    def tag_artifacts(self, artifacts):
        dest_tag = self._get_tag(self.module_tag)['id']

        for nvr in artifacts:
            log.info("%r tagging %r into %r" % (self, nvr, dest_tag))
            self.koji_session.tagBuild(dest_tag, nvr, force=True)

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

        build_opts = {"skip_tag": True}
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
        :param config: instance of rida.config.Config
        :param tag_name: Tag for which the repository is returned
        :param arch: Architecture for which the repository is returned

        Returns URL of repository containing the built artifacts for
        the tag with particular name and architecture.
        """
        return "%s/%s/latest/%s" % (config.koji_repository_url, tag_name, arch)

    def _get_tag(self, tag, strict=True):
        if isinstance(tag, dict):
            tag = tag['name']
        taginfo = self.koji_session.getTag(tag)
        if not taginfo:
            if strict:
                raise SystemError("Unknown tag: %s" % tag)
        return taginfo

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


    def _koji_create_tag(self, tag_name, arches=None, perm=None):
        """
        :param tag_name: name of koji tag
        :param arches: list of architectures for the tag
        :param perm: permissions for the tag (used in lock-tag)

        This call is safe to call multiple times.
        """

        log.debug("Ensuring existence of tag='%s'." % tag_name)
        taginfo = self.koji_session.getTag(tag_name)

        if not taginfo: # Existing tag, need to check whether settings is correct
            self.koji_session.createTag(tag_name, {})
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
        return user

    def _koji_whitelist_packages(self, packages):
        # This will help with potential resubmiting of failed builds
        pkglist = dict([(p['package_name'], p['package_id']) for p in self.koji_session.listPackages(tagID=self.module_tag['id'])])
        to_add = []
        for package in packages:
            package_id = pkglist.get(package, None)
            if not package_id is None:
                log.debug("%s Package %s is already whitelisted." % (self, package))
                continue
            to_add.append(package)

        for package in to_add:
            owner = self._get_component_owner(package)
            if not self.koji_session.getUser(owner):
                raise ValueError("Unknown user %s" % owner)

            self.koji_session.packageListAdd(self.module_tag['name'], package, owner)

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


class CoprModuleBuilder(GenericBuilder):

    """
    See http://blog.samalik.com/copr-in-the-modularity-world/
    especially section "Building a stack"
    """

    backend = "copr"

    def __init__(self, owner, module, config, tag_name):
        self.owner = owner
        self.config = config
        self.tag_name = tag_name
        self.module_str = module

        self.copr = None
        self.client = CoprModuleBuilder._get_client(config)
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
        # @TODO how the authentication is designed?
        kwargs = {"ownername": "@copr", "projectname": CoprModuleBuilder._tag_to_copr_name(self.tag_name)}
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

        # Git sources are treated specially.
        if source.startswith("git://"):
            return build_from_scm(artifact_name, source, self.config, self.build_srpm)
        else:
            return self.build_srpm(artifact_name, source)

    def build_srpm(self, artifact_name, source):
        if not self.__prep:
            raise RuntimeError("Buildroot is not prep-ed")

        # Build package from `source`
        response = self.client.create_new_build(self.copr.projectname, [source], username=self.copr.username)
        if response.output != "ok":
            log.error(response.error)

        # Since we don't have implemented messaging support in copr yet,
        # let's just assume that the build is finished by now
        return response.data["ids"][0], koji.BUILD_STATES["COMPLETE"], response.message, None

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
        m1 = ModuleBuild.query.filter(ModuleBuild.name == self.module_str).first()
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
        :param config: instance of rida.config.Config
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
    def _tag_to_copr_name(cls, koji_tag):
        return koji_tag.replace("+", "-")


class MockModuleBuilder(GenericBuilder):
    """
    See http://blog.samalik.com/copr-in-the-modularity-world/
    especially section "Building a stack"
    """

    backend = "mock"
    # Global build_id/task_id we increment when new build is executed.
    _build_id = 1

    MOCK_CONFIG_TEMPLATE = """
config_opts['root'] = '$root'
config_opts['target_arch'] = '$arch'
config_opts['legal_host_arches'] = ('$arch',)
config_opts['chroot_setup_cmd'] = 'install $group'
config_opts['dist'] = ''
config_opts['extra_chroot_dirs'] = [ '/run/lock', ]
config_opts['releasever'] = ''
config_opts['package_manager'] = 'dnf'

config_opts['yum.conf'] = \"\"\"
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

$repos
\"\"\"
"""

    def __init__(self, owner, module, config, tag_name):
        self.module_str = module
        self.tag_name = tag_name
        self.config = config
        self.groups = []
        self.arch = "x86_64" # TODO: We may need to change that in the future
        self.repos = ""

        # Create main directory for this tag
        self.tag_dir = os.path.join(self.config.mock_resultsdir, tag_name)
        if not os.path.exists(self.tag_dir):
            os.makedirs(self.tag_dir)

        # Create "results" sub-directory for this tag to store build results
        # and local repository.
        self.resultsdir = os.path.join(self.tag_dir, "results")
        if not os.path.exists(self.resultsdir):
            os.makedirs(self.resultsdir)

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

        # Create "config" sub-directory.
        self.configdir = os.path.join(self.tag_dir, "config")
        if not os.path.exists(self.configdir):
            os.makedirs(self.configdir)

        # Generate path to mock config and add local repository there.
        self.mock_config = os.path.join(self.configdir, "mock.cfg")
        self._add_repo("localrepo", "file://" + self.resultsdir, "metadata_expire=1\n")

        log.info("MockModuleBuilder initialized, tag_name=%s, tag_dir=%s" %
                 (tag_name, self.tag_dir))

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
        self.repos += "[%s]\n" % name
        self.repos += "name=%s\n" % name
        self.repos += "baseurl=%s\n" % baseurl
        self.repos += extra
        self.repos += "enabled=1\n"

    def _write_mock_config(self):
        """
        Writes Mock config file to self.configdir/mock.cfg.
        """

        # We want to write confing only before the first build, otherwise
        # we would overwrite it in the middle of module build which would
        # break the build.
        if MockModuleBuilder._build_id != 1:
            return

        config = str(MockModuleBuilder.MOCK_CONFIG_TEMPLATE)
        config = config.replace("$root", self.tag_name)
        config = config.replace("$arch", self.arch)
        config = config.replace("$group", " ".join(self.groups))
        config = config.replace("$repos", self.repos)

        with open(os.path.join(self.configdir, "mock.cfg"), 'w') as f:
            f.write(config)

    def buildroot_connect(self, groups):
        self.groups = groups["build"]
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
            if artifact.startswith("module-build-macros"):
                _execute_cmd(["mock", "-r", self.mock_config, "-i",
                                   "module-build-macros"])

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

    def _save_log(self, log_name, artifact_name):
        old_log = os.path.join(self.resultsdir, log_name)
        new_log = os.path.join(self.resultsdir, artifact_name + "-" + log_name)
        if os.path.exists(old_log):
            os.rename(old_log, new_log)

    def build_srpm(self, artifact_name, source):
        """
        Builds the artifact from the SRPM.
        """
        try:
            # Initialize mock.
            _execute_cmd(["mock", "-r", self.mock_config, "--init"])

            # Start the build and store results to resultsdir
            # TODO: Maybe this should not block in the future, but for local
            # builds it is not a big problem.
            _execute_cmd(["mock", "-r", self.mock_config,
                               "--no-clean", "--rebuild", source,
                               "--resultdir=%s" % self.resultsdir])

            # Emit messages simulating complete build. These messages
            # are put in the scheduler's work queue and are handled
            # by MBS after the build_srpm() method returns and scope gets
            # back to scheduler.main.main() method.
            self._send_build_change(koji.BUILD_STATES['COMPLETE'], source,
                                    MockModuleBuilder._build_id)

            with open(os.path.join(self.resultsdir, "status.log"), 'w') as f:
                f.write("complete\n")
        except Exception as e:
            log.error("Error while building artifact %s: %s" % (artifact_name,
                      str(e)))

            # Emit messages simulating complete build. These messages
            # are put in the scheduler's work queue and are handled
            # by MBS after the build_srpm() method returns and scope gets
            # back to scheduler.main.main() method.
            self._send_build_change(koji.BUILD_STATES['FAILED'], source,
                                    MockModuleBuilder._build_id)
            with open(os.path.join(self.resultsdir, "status.log"), 'w') as f:
                f.write("failed\n")

        self._save_log("state.log", artifact_name)
        self._save_log("root.log", artifact_name)
        self._save_log("build.log", artifact_name)
        self._save_log("status.log", artifact_name)

        # Return the "building" state. Real state will be taken by MBS
        # from the messages emitted above.
        state = koji.BUILD_STATES['BUILDING']
        reason = "Submitted %s to Koji" % (artifact_name)
        return MockModuleBuilder._build_id, state, reason, None

    def build(self, artifact_name, source):
        log.info("Starting building artifact %s: %s" % (artifact_name, source))
        MockModuleBuilder._build_id += 1

        # Git sources are treated specially.
        if source.startswith("git://"):
            return build_from_scm(artifact_name, source, self.config, self.build_srpm)
        else:
            return self.build_srpm(artifact_name, source)


    @staticmethod
    def get_disttag_srpm(disttag):
        # @FIXME
        return KojiModuleBuilder.get_disttag_srpm(disttag)

    def cancel_build(self, task_id):
        pass


def build_from_scm(artifact_name, source, config, build_srpm):
    """
    Builds the artifact from the SCM based source.
    """
    td = None
    owd = os.getcwd()
    ret = (0, koji.BUILD_STATES["FAILED"], "Cannot create SRPM", None)

    try:
        log.debug('Cloning source URL: %s' % source)
        # Create temp dir and clone the repo there.
        td = tempfile.mkdtemp()
        scm = module_build_service.scm.SCM(source)
        cod = scm.checkout(td)

        # Use configured command to create SRPM out of the SCM repo.
        log.debug("Creating SRPM")
        os.chdir(cod)
        _execute_cmd(config.mock_build_srpm_cmd.split(" "))

        # Find out the built SRPM and build it normally.
        for f in os.listdir(cod):
            if f.endswith(".src.rpm"):
                log.info("Created SRPM %s" % f)
                source = os.path.join(cod, f)
                ret = build_srpm(artifact_name, source)
                break
    finally:
        os.chdir(owd)
        try:
            if td is not None:
                shutil.rmtree(td)
        except Exception as e:
            log.warning(
                "Failed to remove temporary directory {!r}: {}".format(
                    td, str(e)))

    return ret


def _execute_cmd(args):
    log.debug("Executing command: %s" % args)
    ret = subprocess.call(args)
    if ret != 0:
        raise RuntimeError("Command '%s' returned non-zero value %d"
                           % (args, ret))


GenericBuilder.register_backend_class(KojiModuleBuilder)
GenericBuilder.register_backend_class(CoprModuleBuilder)
GenericBuilder.register_backend_class(MockModuleBuilder)
