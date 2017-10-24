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


import logging
import os
import koji
import tempfile
import glob
import datetime
import time
import dogpile.cache
import random
import string
import kobo.rpmlib
import xmlrpclib
import threading

import munch
from OpenSSL.SSL import SysCallError

from module_build_service import log
import module_build_service.scm
import module_build_service.utils
from module_build_service.builder.utils import execute_cmd

from base import GenericBuilder

logging.basicConfig(level=logging.DEBUG)


class KojiModuleBuilder(GenericBuilder):
    """ Koji specific builder class """

    backend = "koji"
    _build_lock = threading.Lock()
    region = dogpile.cache.make_region().configure('dogpile.cache.memory')

    @module_build_service.utils.validate_koji_tag('tag_name')
    def __init__(self, owner, module, config, tag_name, components):
        """
        :param owner: a string representing who kicked off the builds
        :param module: module_build_service.models.ModuleBuild instance.
        :param config: module_build_service.config.Config instance
        :param tag_name: name of tag for given module
        """
        self.owner = owner
        self.module_str = module.name
        self.mmd = module.mmd()
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
        self.module_tag = None  # string
        self.module_build_tag = None  # string
        self.module_target = None  # A koji target dict

        self.build_priority = config.koji_build_priority
        self.components = components

    def __repr__(self):
        return "<KojiModuleBuilder module: %s, tag: %s>" % (
            self.module_str, self.tag_name)

    @region.cache_on_arguments()
    def getPerms(self):
        return dict([(p['name'], p['id']) for p in self.koji_session.getAllPerms()])

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

        if not repo:
            log.info("Repo is not generated yet, buildroot is not ready yet.")
            return False

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
    def get_disttag_srpm(disttag, module_build):

        # Taken from Karsten's create-distmacro-pkg.sh
        # - however removed any provides to system-release/redhat-release

        name = 'module-build-macros'
        version = "0.1"
        release = "1"
        today = datetime.date.today().strftime('%a %b %d %Y')
        mmd = module_build.mmd()

        # Generate "Conflicts: name = version-release". This is workaround for
        # Koji build system, because it does not filter out RPMs from the
        # build-requires based on their "mmd.filter.rpms". So we set the
        # module-build-macros to conflict with these filtered RPMs to ensure
        # they won't be installed to buildroot.
        filter_conflicts = ""
        for req_name, req_data in mmd.xmd["mbs"]["buildrequires"].items():
            if req_data["filtered_rpms"]:
                filter_conflicts += "# Filtered rpms from %s module:\n" % (
                    req_name)
            for nvr in req_data["filtered_rpms"]:
                parsed_nvr = kobo.rpmlib.parse_nvr(nvr)
                filter_conflicts += "Conflicts: %s = %s:%s-%s\n" % (
                    parsed_nvr["name"], parsed_nvr["epoch"],
                    parsed_nvr["version"], parsed_nvr["release"])

        spec_content = """
%global dist {disttag}
%global _module_name {module_name}
%global _module_stream {module_stream}
%global _module_version {module_version}

Name:       {name}
Version:    {version}
Release:    {release}%dist
Summary:    Package containing macros required to build generic module
BuildArch:  noarch

Group:      System Environment/Base
License:    MIT
URL:        http://fedoraproject.org

Source1:    macros.modules

{filter_conflicts}

%description
This package is used for building modules with a different dist tag.
It provides a file /usr/lib/rpm/macros.d/macro.modules and gets read
after macro.dist, thus overwriting macros of macro.dist like %%dist
It should NEVER be installed on any system as it will really mess up
 updates, builds, ....


%build

%install
mkdir -p %buildroot/%_sysconfdir/rpm 2>/dev/null |:
cp %SOURCE1 %buildroot/%_sysconfdir/rpm/macros.zz-modules
chmod 644 %buildroot/%_sysconfdir/rpm/macros.zz-modules


%files
%_sysconfdir/rpm/macros.zz-modules



%changelog
* {today} Fedora-Modularity - {version}-{release}{disttag}
- autogenerated macro by Module Build Service (MBS)
""".format(disttag=disttag, today=today, name=name, version=version,
           release=release,
           module_name=module_build.name,
           module_stream=module_build.stream,
           module_version=module_build.version,
           filter_conflicts=filter_conflicts)

        modulemd_macros = ""
        if mmd.buildopts and mmd.buildopts.rpms:
            modulemd_macros = mmd.buildopts.rpms.macros

        macros_content = """

# General macros set by MBS

%dist {disttag}
%_module_build 1
%_module_name {module_name}
%_module_stream {module_stream}
%_module_version {module_version}

# Macros set by module author:

{modulemd_macros}
""".format(disttag=disttag, module_name=module_build.name,
           module_stream=module_build.stream,
           module_version=module_build.version,
           modulemd_macros=modulemd_macros)

        td = tempfile.mkdtemp(prefix="module_build_service-build-macros")
        fd = open(os.path.join(td, "%s.spec" % name), "w")
        fd.write(spec_content)
        fd.close()
        sources_dir = os.path.join(td, "SOURCES")
        os.mkdir(sources_dir)
        fd = open(os.path.join(sources_dir, "macros.modules"), "w")
        fd.write(macros_content)
        fd.close()
        log.debug("Building %s.spec" % name)

        # We are not interested in the rpmbuild stdout...
        null_fd = open(os.devnull, 'w')
        execute_cmd(['rpmbuild', '-bs', '%s.spec' % name, '--define',
                     '_topdir %s' % td], cwd=td, stdout=null_fd)
        null_fd.close()
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
        # the main tag needs arches so pungi can dump it
        self.module_tag = self._koji_create_tag(
            self.tag_name, self.arches, perm="admin")
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

        self.koji_session.multicall = True
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
        self.koji_session.multiCall(strict=True)

    def tag_artifacts(self, artifacts):
        dest_tag = self._get_tag(self.module_tag)['id']

        tagged_nvrs = self._get_tagged_nvrs(self.module_tag['name'])

        self.koji_session.multicall = True
        for nvr in artifacts:
            if nvr in tagged_nvrs:
                continue

            log.info("%r tagging %r into %r" % (self, nvr, dest_tag))
            self.koji_session.tagBuild(dest_tag, nvr)
        self.koji_session.multiCall(strict=True)

    def wait_task(self, task_id):
        """
        :param task_id
        :return - task result object
        """

        log.info("Waiting for task_id=%s to finish" % task_id)

        timeout = 60 * 60  # 60 minutes

        @module_build_service.utils.retry(timeout=timeout, wait_on=koji.GenericError)
        def get_result():
            log.debug("Waiting for task_id=%s to finish" % task_id)
            task = self.koji_session.getTaskResult(task_id)
            log.info("Done waiting for task_id=%s to finish" % task_id)
            return task

        return get_result()

    def _get_build_by_artifact(self, artifact_name):
        """
        :param artifact_name: e.g. bash

        Searches for a complete build of artifact belonging to this module.
        The returned build can be even untagged.

        Returns koji_session.getBuild response or None.

        """
        # yaml file can hold only one reference to a package name, so
        # I expect that we can have only one build of package within single module
        # Rules for searching:
        #  * latest: True so I can return only single task_id.
        #  * we do want only build explicitly tagged in the module tag (inherit: False)

        opts = {'latest': True, 'package': artifact_name, 'inherit': False}

        if artifact_name == "module-build-macros":
            tag = self.module_build_tag['name']
        else:
            tag = self.module_tag['name']

        tagged = self.koji_session.listTagged(tag, **opts)

        if tagged:
            assert len(tagged) == 1, "Expected exactly one item in list. Got %s" % tagged
            return tagged[0]

        # If the build cannot be found in tag, it may be untagged as a result
        # of some earlier inconsistent situation. Let's find the task_info
        # based on the list of untagged builds
        release = module_build_service.utils.get_rpm_release_from_mmd(self.mmd)
        opts = {'name': artifact_name}
        untagged = self.koji_session.untaggedBuilds(**opts)
        for build in untagged:
            if build["release"].endswith(release):
                # Tag it.
                nvr = "{name}-{version}-{release}".format(**build)
                self.tag_artifacts([nvr])

                # Now, make the same query we made earlier to return a dict
                # with the same schema.
                tagged = self.koji_session.listTagged(tag, package=artifact_name)
                if not tagged:
                    # Should be impossible.
                    raise ValueError("Just tagged %s but didn't find it" % nvr)
                return tagged[0]

        return None

    def build(self, artifact_name, source):
        """
        :param source : scmurl to spec repository
        : param artifact_name: name of artifact (which we couldn't get
            from spec due involved macros)
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
                                     ''.join([random.choice(string.ascii_letters)
                                              for i in range(8)]))

            if not self.__prep:
                raise RuntimeError("Buildroot is not prep-ed")

            # Skip existing builds
            task_info = self._get_build_by_artifact(artifact_name)
            if task_info:
                log.info("skipping build of %s. Build already exists (task_id=%s), via %s" % (
                    source, task_info['task_id'], self))
                return (task_info['task_id'], koji.BUILD_STATES['COMPLETE'],
                        'Build already exists.', task_info['nvr'])

            self._koji_whitelist_packages([artifact_name])
            if '://' not in source:
                # treat source as an srpm and upload it
                serverdir = _unique_path('cli-build')
                callback = None
                self.koji_session.uploadWrapper(source, serverdir, callback=callback)
                source = "%s/%s" % (serverdir, os.path.basename(source))

            # When "koji_build_macros_target" is set, we build the
            # module-build-macros in this target instead of the self.module_target.
            # The reason is that it is faster to build this RPM in
            # already existing shared target, because Koji does not need to do
            # repo-regen.
            if (artifact_name == "module-build-macros" and
               self.config.koji_build_macros_target):
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

    @module_build_service.utils.validate_koji_tag(['tag_name'], post='')
    def _koji_add_many_tag_inheritance(self, tag_name, parent_tags):
        tag = self._get_tag(tag_name)
        # highest priority num is at the end
        inheritance_data = sorted(self.koji_session.getInheritanceData(tag['name']) or
                                  [], key=lambda k: k['priority'])
        # Set initial priority to last record in inheritance data or 0
        priority = 0
        if inheritance_data:
            priority = inheritance_data[-1]['priority'] + 10

        def record_exists(parent_id, data):
            for item in data:
                if parent_id == item['parent_id']:
                    return True
            return False

        for parent in parent_tags:  # We expect that they're sorted
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
        existing_groups = dict([(p['name'], p['group_id'])
                                for p
                                in self.koji_session.getTagGroups(dest_tag, inherit=False)
                                ])

        for group, packages in groups.items():
            group_id = existing_groups.get(group, None)
            if group_id is not None:
                log.debug("Group %s already exists for tag %s. Skipping creation."
                          % (group, dest_tag))
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
            if taginfo['arches']:  # None if none
                current_arches = taginfo['arches'].split()  # string separated by empty spaces

            if set(arches) != set(current_arches):
                opts['arches'] = " ".join(arches)

        if perm:
            if taginfo['locked']:
                raise SystemError("Tag %s: master lock already set. Can't edit tag"
                                  % taginfo['name'])

            perm_ids = self.getPerms()

            if perm not in perm_ids:
                raise ValueError("Unknown permissions %s" % perm)

            perm_id = perm_ids[perm]
            if taginfo['perm'] not in (perm_id, perm):  # check either id or the string
                opts['perm'] = perm_id

        opts['extra'] = {
            'mock.package_manager': 'dnf',
            # This is needed to include all the Koji builds (and therefore
            # all the packages) from all inherited tags into this tag.
            # See https://pagure.io/koji/issue/588 and
            # https://pagure.io/fm-orchestrator/issue/660 for background.
            'repo_include_all': True,
        }

        # edit tag with opts
        self.koji_session.editTag2(tag_name, **opts)
        return self._get_tag(tag_name)  # Return up2date taginfo

    def _koji_whitelist_packages(self, packages, tags=None):
        if not tags:
            tags = [self.module_tag, self.module_build_tag]

        # This will help with potential resubmiting of failed builds
        pkglists = {}
        for tag in tags:
            pkglists[tag['id']] = dict([(p['package_name'], p['package_id'])
                                        for p in self.koji_session.listPackages(tagID=tag['id'])])

        self.koji_session.multicall = True
        for tag in tags:
            pkglist = pkglists[tag['id']]
            for package in packages:
                if pkglist.get(package, None):
                    log.debug("%s Package %s is already whitelisted." % (self, package))
                    continue

                self.koji_session.packageListAdd(tag['name'], package, self.owner)
        self.koji_session.multiCall(strict=True)

    @module_build_service.utils.validate_koji_tag(['build_tag', 'dest_tag'])
    def _koji_add_target(self, name, build_tag, dest_tag):
        """
        :param name: target name
        :param build-tag: build_tag name
        :param dest_tag: dest tag name

        This call is safe to call multiple times. Raises SystemError() if the existing target
        doesn't match params. The reason not to touch existing target, is that we don't want to
        accidentaly alter a target which was already used to build some artifacts.
        """
        build_tag = self._get_tag(build_tag)
        dest_tag = self._get_tag(dest_tag)
        target_info = self.koji_session.getBuildTarget(name)

        barches = build_tag.get("arches", None)
        assert barches, "Build tag %s has no arches defined." % build_tag['name']

        if not target_info:
            target_info = self.koji_session.createBuildTarget(name, build_tag['name'],
                                                              dest_tag['name'])

        else:  # verify whether build and destination tag matches
            if build_tag['name'] != target_info['build_tag_name']:
                raise SystemError(("Target references unexpected build_tag_name. "
                                   "Got '%s', expected '%s'. Please contact administrator.")
                                  % (target_info['build_tag_name'], build_tag['name']))
            if dest_tag['name'] != target_info['dest_tag_name']:
                raise SystemError(("Target references unexpected dest_tag_name. "
                                   "Got '%s', expected '%s'. Please contact administrator.")
                                  % (target_info['dest_tag_name'], dest_tag['name']))

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

    def get_average_build_time(self, component):
        """
        Get the average build time of the component from Koji
        :param component: a ComponentBuild object
        :return: a float of the average build time in seconds
        """
        # If the component has not been built before, then None is returned. Instead, let's
        # return 0.0 so the type is consistent
        return self.koji_session.getAverageBuildDuration(component.package) or 0.0
