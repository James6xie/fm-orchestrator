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

import munch
from OpenSSL.SSL import SysCallError

from module_build_service import log, db
from module_build_service.models import ModuleBuild
import module_build_service.utils

logging.basicConfig(level=logging.DEBUG)

try:
    from copr.client import CoprClient
except ImportError:
    log.exception("Failed to import CoprClient.")

# TODO: read defaults from module_build_service's config
KOJI_DEFAULT_GROUPS = {
    'build': [
        'bash',
        'bzip2',
        'coreutils',
        'cpio',
        'diffutils',
        'fedora-release',
        'findutils',
        'gawk',
        'gcc',
        'gcc-c++',
        'grep',
        'gzip',
        'info',
        'make',
        'patch',
        'redhat-rpm-config',
        'rpm-build',
        'sed',
        'shadow-utils',
        'tar',
        'unzip',
        'util-linux',
        'which',
        'xz',
    ],
    'srpm-build': [
        'bash',
        'fedora-release',
        'fedpkg-minimal',
        'gnupg2',
        'redhat-rpm-config',
        'rpm-build',
        'shadow-utils',
    ]
}


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

    @abstractmethod
    def buildroot_connect(self):
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
    def build(self, artifact_name, source):
        """
        :param artifact_name : A package name. We can't guess it since macros
                               in the buildroot could affect it, (e.g. software
                               collections).
        :param source : an SCM URL, clearly identifying the build artifact in a
                        repository

        The artifact_name parameter is used in koji add-pkg (and it's actually
        the only reason why we need to pass it). We don't really limit source
        types. The actual source is usually delivered as an SCM URL from
        fedmsg.

        Example
        .build("bash", "git://someurl/bash#damn") #build from SCM URL
        .build("bash", "/path/to/srpm.src.rpm") #build from source RPM
        """
        raise NotImplementedError()

    @classmethod
    @abstractmethod
    def tag_to_repo(self, config, tag_name, arch):
        """
        :param config: instance of rida.config.Config
        :param tag_name: Tag for which the repository is returned
        :param arch: Architecture for which the repository is returned

        Returns URL of repository containing the built artifacts for
        the tag with particular name and architecture.
        """
        raise NotImplementedError()

class Builder(object):
    """Wrapper class"""

    def __new__(cls, owner, module, backend, config, **extra):
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
        elif backend == "koji":
            return KojiModuleBuilder(owner=owner, module=module,
                                     config=config, **extra)
        elif backend == "copr":
            return CoprModuleBuilder(owner=owner, module=module,
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
        if backend == "koji":
            return KojiModuleBuilder.tag_to_repo(config, tag_name, arch)
        else:
            raise ValueError("Builder backend='%s' not recognized" % backend)


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

    def __repr__(self):
        return "<KojiModuleBuilder module: %s, tag: %s>" % (
            self.module_str, self.tag_name)

    @module_build_service.utils.retry(wait_on=koji.GenericError)
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
    def get_session(config, owner):
        koji_config = munch.Munch(koji.read_config(
            profile_name=config.koji_profile,
            user_config=config.koji_config,
        ))

        address = koji_config.server
        log.info("Connecting to koji %r" % address)
        koji_session = koji.ClientSession(address, opts=koji_config)

        authtype = koji_config.authtype
        if authtype == "kerberos":
            ccache = getattr(config, "krb_ccache", None)
            keytab = getattr(config, "krb_keytab", None)
            principal = getattr(config, "krb_principal", None)
            if keytab and principal:
                koji_session.krb_login(
                    principal=principal,
                    keytab=keytab,
                    ccache=ccache,
                    proxyuser=owner,
                )
            else:
                koji_session.krb_login(ccache=ccache)
        elif authtype == "ssl":
            koji_session.ssl_login(
                os.path.expanduser(koji_config.cert),
                None,
                os.path.expanduser(koji_config.serverca),
                proxyuser=owner,
            )
        else:
            raise ValueError("Unrecognized koji authtype %r" % authtype)

        return koji_session

    def buildroot_connect(self):
        log.info("%r connecting buildroot." % self)

        # Create or update individual tags
        self.module_tag = self._koji_create_tag(
            self.tag_name, self.arches, perm="admin") # the main tag needs arches so pungi can dump it

        self.module_build_tag = self._koji_create_tag(
            self.tag_name + "-build", self.arches, perm="admin")

        # TODO: handle in buildroot_add_artifact(install=true) and track groups as module buildrequires
        groups = KOJI_DEFAULT_GROUPS
        if groups:
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
        tags = [self._get_tag(d)['name'] for d in dependencies]
        log.info("%r adding deps on %r" % (self, tags))
        self._koji_add_many_tag_inheritance(self.module_build_tag, tags)

    def buildroot_add_artifacts(self, artifacts, install=False):
        """
        :param artifacts - list of artifacts to add to buildroot
        :param install=False - force install artifact (if it's not dragged in as dependency)

        This method is safe to call multiple times.
        """
        log.info("%r adding artifacts %r" % (self, artifacts))
        dest_tag = self._get_tag(self.module_build_tag)['id']

        for nvr in artifacts:
            log.info("%r tagging %r into %r" % (self, nvr, dest_tag))
            self.koji_session.tagBuild(dest_tag, nvr, force=True)

            if not install:
                continue

            for group in ('srpm-build', 'build'):
                name = kobo.rpmlib.parse_nvr(nvr)['name']
                log.info("%r adding %s to group %s" % (self, name, group))
                self.koji_session.groupPackageListAdd(dest_tag, group, name)

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
            return tagged[0]['task_id']

        return None

    def build(self, artifact_name, source):
        """
        :param source : scmurl to spec repository
        : param artifact_name: name of artifact (which we couldn't get from spec due involved macros)
        :return koji build task id
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
        task_id = self._get_task_by_artifact(artifact_name)
        if task_id:
            log.info("skipping build of %s. Build already exists (task_id=%s), via %s" % (
                source, task_id, self))
            return task_id

        self._koji_whitelist_packages([artifact_name,])
        if '://' not in source:
            #treat source as an srpm and upload it
            serverdir = _unique_path('cli-build')
            callback = None
            self.koji_session.uploadWrapper(source, serverdir, callback=callback)
            source = "%s/%s" % (serverdir, os.path.basename(source))

        task_id = self.koji_session.build(source, self.module_target['name'])
        log.info("submitted build of %s (task_id=%s), via %s" % (
            source, task_id, self))
        return task_id

    @classmethod
    def tag_to_repo(cls, config, tag_name, arch):
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
        self.module_str = module
        self.tag_name = tag_name

    def buildroot_connect(self):
        pass

    def buildroot_prep(self):
        pass

    def buildroot_resume(self):
        pass

    def buildroot_ready(self, artifacts=None):
        return True

    def buildroot_add_dependency(self, dependencies):
        pass

    def buildroot_add_artifacts(self, artifacts, install=False):
        pass

    def buildroot_add_repos(self, dependencies):
        pass

    def build(self, artifact_name, source):
        log.info("Copr build")

        modulemd = tempfile.mktemp()
        m1 = db.session.query(ModuleBuild).first()
        m1.mmd().dump(modulemd)

        # @TODO how the authentication is designed?
        username, copr = "@copr", "modules"
        client = CoprClient.create_from_file_config()

        data = {"modulemd": modulemd}
        result = client.create_new_build_module(username=username, projectname=copr, **data)
        if result.output != "ok":
            log.error(result.error)
            return

        log.info(result.message)
        log.info(result.data["modulemd"])

    @staticmethod
    def get_disttag_srpm(disttag):
        # @FIXME
        return KojiModuleBuilder.get_disttag_srpm(disttag)
