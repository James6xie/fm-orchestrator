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

from abc import ABCMeta, abstractmethod
import logging
import os

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

from rida import log
import rida.utils

logging.basicConfig(level=logging.DEBUG)

# TODO: read defaults from rida's config
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

class GenericBuilder:
    """External Api for builders"""
    __metaclass__ = ABCMeta

    backend = "generic"

    @abstractmethod
    def buildroot_prep(self):
        """
        preps buildroot
        """
        raise NotImplementedError()

    @abstractmethod
    def buildroot_resume(self):
        """
        resumes buildroot (alternative to prep)
        """
        raise NotImplementedError()

    @abstractmethod
    def buildroot_ready(self, artifacts=None):
        """
        :param artifacts=None : a list of artifacts supposed to be in buildroot
        return when buildroot is ready (or contain specified artifact)
        """
        raise NotImplementedError()

    @abstractmethod
    def buildroot_add_dependency(self, dependencies):
        """
        :param dependencies: a list off modules which we build-depend on
        adds dependencies 'another module(s)' into buildroot
        """
        raise NotImplementedError()

    @abstractmethod
    def buildroot_add_artifacts(self, artifacts, install=False):
        """
        :param artifacts: list of artifacts to be available in buildroot
        :param install=False: pre-install artifact in buildroot (otherwise "make it available for install")
        add artifacts into buildroot, can be used to override buildroot macros
        """
        raise NotImplementedError()

    @abstractmethod
    def build(self, artifact_name, source):
        """
        :param artifact_name : a crucial, since we can't guess a valid srpm name
                               without having the exact buildroot (collections/macros)
                               used e.g. for whitelisting packages
                               artifact_name is used to distinguish from artifact (e.g. package x nvr)
        :param source : a scmurl to repository with receipt (e.g. spec)
        """
        raise NotImplementedError()

class Builder:
    """Wrapper class"""

    def __new__(cls, module, backend, config, **extra):
        """
        :param module : a module string e.g. 'testmodule-1.0'
        :param backend: a string representing backend e.g. 'koji'
        :param config: instance of rida.config.Config

        Any additional arguments are optional extras which can be passed along
        and are implementation-dependent.
        """

        if backend == "koji":
            return KojiModuleBuilder(module=module, config=config, **extra)
        else:
            raise ValueError("Builder backend='%s' not recognized" % backend)


class KojiModuleBuilder(GenericBuilder):
    """ Koji specific builder class """

    backend = "koji"

    def __init__(self, module, config, tag_name):
        """
        :param module: string representing module
        :param config: rida.config.Config instance
        :param tag_name: name of tag for given module
        """
        self.module_str = module
        self.tag_name = tag_name
        self.__prep = False
        log.debug("Using koji profile %r" % config.koji_profile)
        log.debug ("Using koji_config: %s" % config.koji_config)

        self.koji_session, self.koji_module = self.get_session_from_config(config)
        self.arches = config.koji_arches
        if not self.arches:
            raise ValueError("No koji_arches specified in the config.")

        # These eventually get populated when buildroot_{prep,resume} is called
        self.module_tag = None # string
        self.module_build_tag = None # string
        self.module_target = None # A koji target dict

    def __repr__(self):
        return "<KojiModuleBuilder module: %s, tag: %s>" % (
            self.module_str, self.tag_name)

    @rida.utils.retry(wait_on=koji.GenericError)
    def buildroot_ready(self, artifacts):
        """ Returns True or False if the given artifacts are in the build root.
        """
        assert self.module_target, "Invalid build target"

        tag_id = self.module_target['build_tag']
        repo = self.koji_session.getRepo(tag_id)
        builds = [self.koji_session.getBuild(a) for a in artifacts]
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
        td = tempfile.mkdtemp(prefix="rida-build-macros")
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
    def get_session_from_config(config):
        koji_config = munch.Munch(koji.read_config(
            profile_name=config.koji_profile,
            user_config=config.koji_config,
        ))
        koji_module = koji.get_profile_module(
            config.koji_profile,
            config=koji_config,
        )

        krbservice = getattr(koji_config, "krbservice", None)
        if krbservice:
            koji_config.krbservice = krbservice

        address = koji_config.server
        log.info("Connecting to koji %r" % address)
        koji_session = koji.ClientSession(address, opts=vars(koji_config))

        authtype = koji_config.authtype
        if authtype == "kerberos":
            keytab = getattr(koji_config, "keytab", None)
            principal = getattr(koji_config, "principal", None)
            if keytab and principal:
                koji_session.krb_login(
                    principal=principal,
                    keytab=keytab,
                    proxyuser=None,
                )
            else:
                koji_session.krb_login()
        elif authtype == "ssl":
            koji_session.ssl_login(
                os.path.expanduser(koji_config.cert),
                None,
                os.path.expanduser(koji_config.serverca),
                proxyuser=None,
            )
        else:
            raise ValueError("Unrecognized koji authtype %r" % authtype)
        return (koji_session, koji_module)

    def buildroot_resume(self): # XXX: experimental
        """
        Resume existing buildroot. Sets __prep=True
        """
        log.info("%r resuming buildroot." % self)
        chktag = self.koji_session.getTag(self.tag_name)
        if not chktag:
            raise SystemError("Tag %s doesn't exist" % self.tag_name)
        chkbuildtag = self.koji_session.getTag(self.tag_name + "-build")
        if not chkbuildtag:
            raise SystemError("Build Tag %s doesn't exist" % self.tag_name + "-build")
        chktarget = self.koji_session.getBuildTarget(self.tag_name)
        if not chktarget:
            raise SystemError("Target %s doesn't exist" % self.tag_name)
        self.module_tag = chktag
        self.module_build_tag = chkbuildtag
        self.module_target = chktarget
        self.__prep = True
        log.info("%r buildroot resumed." % self)

    def buildroot_prep(self):
        """
        :param module_deps_tags: a tag names of our build requires
        :param module_deps_tags: a tag names of our build requires
        """
        log.info("%r preparing buildroot." % self)
        self.module_tag = self._koji_create_tag(
            self.tag_name, self.arches, perm="admin") # the main tag needs arches so pungi can dump it
        self.module_build_tag = self._koji_create_tag(
            self.tag_name + "-build", self.arches, perm="admin")

        groups = KOJI_DEFAULT_GROUPS # TODO: read from config
        if groups:
            @rida.utils.retry(wait_on=SysCallError, interval=5)
            def add_groups():
                return self._koji_add_groups_to_tag(
                    dest_tag=self.module_build_tag,
                    groups=groups,
                )
            add_groups()

        self.module_target = self._koji_add_target(self.tag_name, self.module_build_tag, self.module_tag)
        self.__prep = True
        log.info("%r buildroot prepared." % self)

    def buildroot_add_dependency(self, dependencies):
        tags = [self._get_tag(d)['name'] for d in dependencies]
        log.info("%r adding deps for %r" % (self, tags))
        self._koji_add_many_tag_inheritance(self.module_build_tag, tags)

    def buildroot_add_artifacts(self, artifacts, install=False):
        """
        :param artifacts - list of artifacts to add to buildroot
        :param install=False - force install artifact (if it's not dragged in as dependency)
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
        @rida.utils.retry(timeout=timeout, wait_on=koji.GenericError)
        def get_result():
            log.debug("Waiting for task_id=%s to finish" % task_id)
            task = self.koji_session.getTaskResult(task_id)
            log.info("Done waiting for task_id=%s to finish" % task_id)
            return task

        return get_result()


    def build(self, artifact_name, source):
        """
        :param source : scmurl to spec repository
        : param artifact_name: name of artifact (which we couldn't get from spec due involved macros)
        :return koji build task id
        """
        # Taken from /usr/bin/koji
        def _unique_path(prefix):
            """Create a unique path fragment by appending a path component
            to prefix.  The path component will consist of a string of letter and numbers
            that is unlikely to be a duplicate, but is not guaranteed to be unique."""
            # Use time() in the dirname to provide a little more information when
            # browsing the filesystem.
            # For some reason repr(time.time()) includes 4 or 5
            # more digits of precision than str(time.time())
            return '%s/%r.%s' % (prefix, time.time(),
                              ''.join([random.choice(string.ascii_letters) for i in range(8)]))

        if not self.__prep:
            raise RuntimeError("Buildroot is not prep-ed")

        self._koji_whitelist_packages([artifact_name,])
        if '://' not in source:
            #treat source as an srpm and upload it
            serverdir = _unique_path('cli-build')
            callback =None
            self.koji_session.uploadWrapper(source, serverdir, callback=callback)
            source = "%s/%s" % (serverdir, os.path.basename(source))

        task_id = self.koji_session.build(source, self.module_target['name'])
        log.info("submitted build of %s (task_id=%s), via %s" % (
            source, task_id, self))
        return task_id

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

        inheritanceData = []
        priority = 0
        for parent in parent_tags: # We expect that they're sorted
            parent = self._get_tag(parent)
            parent_data = {}
            parent_data['parent_id'] = parent['id']
            parent_data['priority'] = priority
            parent_data['maxdepth'] = None
            parent_data['intransitive'] = False
            parent_data['noconfig'] = False
            parent_data['pkg_filter'] = ''
            inheritanceData.append(parent_data)
            priority += 10

        self.koji_session.setInheritanceData(tag['id'], inheritanceData)

    def _koji_add_groups_to_tag(self, dest_tag, groups=None):
        """
        :param build_tag_name
        :param groups: A dict {'group' : [package, ...]}
        """
        log.debug("Adding groups=%s to tag=%s" % (groups.keys(), dest_tag))

        if groups and not isinstance(groups, dict):
            raise ValueError("Expected dict {'group' : [str(package1), ...]")

        dest_tag = self._get_tag(dest_tag)['name']
        existing_groups = dict([
            (p['name'], p['group_id'])
            for p in self.koji_session.getTagGroups(dest_tag, inherit=False)
        ])

        for group, packages in groups.iteritems():
            group_id = existing_groups.get(group, None)
            if group_id is not None:
                log.warning("Group %s already exists for tag %s" % (group, dest_tag))
                continue
            self.koji_session.groupListAdd(dest_tag, group)
            log.debug("Adding %d packages into group=%s tag=%s" % (len(packages), group, dest_tag))
            for pkg in packages:
                self.koji_session.groupPackageListAdd(dest_tag, group, pkg)


    def _koji_create_tag(self, tag_name, arches=None, fail_if_exists=True, perm=None):
        log.debug("Creating tag %s" % tag_name)
        chktag = self.koji_session.getTag(tag_name)
        if chktag and fail_if_exists:
            raise SystemError("Tag %s already exist" % tag_name)

        elif chktag:
            return self._get_tag(self.module_tag)

        else:
            opts = {}
            if arches:
                if not isinstance(arches, list):
                    raise ValueError("Expected list or None on input got %s" % type(arches))
                opts['arches'] = " ".join(arches)

            self.koji_session.createTag(tag_name, **opts)
            if perm:
                self._lock_tag(tag_name, perm)
            return self._get_tag(tag_name)

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
                log.warn("Package %s already exists in tag %s" % (package, self.module_tag['name']))
                continue
            to_add.append(package)

        for package in to_add:
            owner = self._get_component_owner(package)
            if not self.koji_session.getUser(owner):
                raise ValueError("Unknown user %s" % owner)

            self.koji_session.packageListAdd(self.module_tag['name'], package, owner)

    def _koji_add_target(self, name, build_tag, dest_tag):
        build_tag = self._get_tag(build_tag)
        dest_tag = self._get_tag(dest_tag)

        barches = build_tag.get("arches", None)
        assert barches, "Build tag %s has no arches defined" % build_tag['name']
        self.koji_session.createBuildTarget(name, build_tag['name'], dest_tag['name'])
        return self.koji_session.getBuildTarget(name)

    def _lock_tag(self, tag, perm="admin"):
        taginfo = self._get_tag(tag)
        if taginfo['locked']:
            raise SystemError("Tag %s: master lock already set" % taginfo['name'])
        perm_ids = dict([(p['name'], p['id']) for p in self.koji_session.getAllPerms()])
        if perm not in perm_ids.keys():
            raise ValueError("Unknown permissions %s" % perm)
        perm_id = perm_ids[perm]
        self.koji_session.editTag2(taginfo['id'], perm=perm_id)
