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

log = logging.getLogger(__name__)

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
    def buildroot_add_dependency(self, dependencies):
        """
        :param dependencies: a list off modules which we build-depend on
        adds dependencies 'another module(s)' into buildroot
        """
        raise NotImplementedError()

    @abstractmethod
    def buildroot_add_artifacts(self, artifacts):
        """
        :param artifacts: list of artifacts to be available in buildroot
        add artifacts into buildroot, can be used to override buildroot macros
        """
        raise NotImplementedError()

    @abstractmethod
    def buildroot_ready(self, artifact=None):
        """
        :param artifact=None: wait for specific artifact to be present
        waits for buildroot to be ready and contain given artifact
        """
        raise NotImplementedError()

    @abstractmethod
    def build(self, artifact_name, source):
        """
        :param artifact_name : name of what are we building (used for whitelists)
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
        :param koji_profile: koji profile to be used
        """
        self.module_str = module
        self.__prep = False
        self._koji_profile_name = config.koji_profile
        log.debug("Using koji profile %r" % self._koji_profile_name)
        self.koji_module = koji.get_profile_module(self._koji_profile_name)
        opts = {}

        koji_config = self.koji_module.config

        krbservice = getattr(koji_config, "krbservice", None)
        if krbservice:
            opts["krbservice"] = krbservice

        address = koji_config.server
        log.info("Connecting to koji %r, %r" % (address, opts))
        self.koji_session = koji.ClientSession(address, opts=opts)

        authtype = koji_config.authtype
        if authtype == "kerberos":
            keytab = getattr(koji_config, "keytab", None)
            principal = getattr(koji_config, "principal", None)
            if keytab and principal:
                self.koji_session.krb_login(
                    principal=principal,
                    keytab=keytab,
                    proxyuser=None,
                )
            else:
                self.koji_session.krb_login()
        elif authtype == "ssl":
            self.koji_session.ssl_login(
                os.path.expanduser(koji_config.cert),
                None,
                os.path.expanduser(koji_config.serverca),
                proxyuser=None,
            )
        else:
            raise ValueError("Unrecognized koji authtype %r" % authtype)

        self.arches = config.koji_arches
        if not self.arches:
            raise ValueError("No koji_arches specified in the config.")

        self.module_tag = tag_name
        self.module_build_tag = "%s-build" % tag_name
        self.module_target = tag_name

    def buildroot_resume(self): # XXX: experimental
        """
        Resume existing buildroot. Sets __prep=True
        """
        chktag = self.koji_session.getTag(self.module_tag)
        if not chktag:
            raise SystemError("Tag %s doesn't exist" % self.module_tag)
        chkbuildtag = self.koji_session.getTag(self.module_build_tag)
        if not chkbuildtag:
            raise SystemError("Build Tag %s doesn't exist" % self.module_build_tag)
        chktarget = self.koji_session.getBuildTarget(self.module_build_tag)
        if not chktarget:
            raise SystemError("Target %s doesn't exist" % self.module_target)
        self.module_tag = chktag
        self.module_build_tag = chkbuildtag
        self.module_target = chktarget
        self.__prep = True

    def buildroot_prep(self):
        """
        :param module_deps_tags: a tag names of our build requires
        :param module_deps_tags: a tag names of our build requires
        """
        self.module_tag = self._koji_create_tag(self.module_tag, perm="admin") # returns tag obj
        self.module_build_tag = self._koji_create_tag(self.module_build_tag, self.arches, perm="admin")

        groups = KOJI_DEFAULT_GROUPS # TODO: read from config
        if groups:
            self._koji_add_groups_to_tag(self.module_build_tag, groups)

        self.module_target = self._koji_add_target(self.module_target, self.module_build_tag, self.module_tag)
        self.__prep = True

    def buildroot_add_dependency(self, dependencies):
        tags = [self._get_tag(d)['name'] for d in dependencies]
        self._koji_add_many_tag_inheritance(self.module_build_tag, tags)

    def buildroot_add_artifacts(self, artifacts):
        # TODO: import /usr/bin/koji's TaskWatcher()
        for nvr in artifacts:
            self.koji_session.tagBuild(self.module_build_tag, nvr, force=True)

    def buildroot_ready(self, artifact=None):
        # XXX: steal code from /usr/bin/koji
        cmd = "koji -p %s wait-repo %s " % (self._koji_profile_name, self.module_build_tag['name'])
        if artifact:
            cmd += " --build %s" % artifact
        print ("Waiting for buildroot(%s) to be ready" % (self.module_build_tag['name']))
        run(cmd) # wait till repo is current

    def build(self, artifact_name, source):
        """
        :param source : scmurl to spec repository
        :return koji build id
        """
        if not self.__prep:
            raise RuntimeError("Buildroot is not prep-ed")

        if '://' not in source:
            raise NotImplementedError("Only scm url is currently supported, got source='%s'" % source)
        self._koji_whitelist_packages([artifact_name,])
        build_id = self.koji_session.build(source, self.module_target['name'])
        print("Building %s (build_id=%s)." % (source, build_id))
        return build_id

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

        if groups and not isinstance(groups, dict):
            raise ValueError("Expected dict {'group' : [str(package1), ...]")

        dest_tag = self._get_tag(dest_tag)['name']
        groups = dict([(p['name'], p['group_id']) for p in self.koji_session.getTagGroups(dest_tag, inherit=False)])
        for group, packages in groups.iteritems():
            group_id = groups.get(group, None)
            if group_id is not None:
                print("Group %s already exists for tag %s" % (group, dest_tag))
                return 1
            self.koji_session.groupListAdd(dest_tag, group)
            for pkg in packages:
                self.koji_session.groupPackageListAdd(dest_tag, group, pkg)


    def _koji_create_tag(self, tag_name, arches=None, fail_if_exists=True, perm=None):
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
                print ("Package %s already exists in tag %s" % (package, self.module_tag['name']))
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
