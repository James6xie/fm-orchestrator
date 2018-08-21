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
import threading
try:
    import xmlrpclib
except ImportError:
    import xmlrpc.client as xmlrpclib

import munch
from OpenSSL.SSL import SysCallError

from module_build_service import log, conf, models
import module_build_service.scm
import module_build_service.utils
from module_build_service.builder.utils import execute_cmd
from module_build_service.errors import ProgrammingError

from module_build_service.builder.base import GenericBuilder
from module_build_service.builder.KojiContentGenerator import KojiContentGenerator
from module_build_service.utils import get_reusable_components, get_reusable_module

logging.basicConfig(level=logging.DEBUG)


def koji_multicall_map(koji_session, koji_session_fnc, list_of_args=None, list_of_kwargs=None):
    """
    Calls the `koji_session_fnc` using Koji multicall feature N times based on the list of
    arguments passed in `list_of_args` and `list_of_kwargs`.
    Returns list of responses sorted the same way as input args/kwargs. In case of error,
    the error message is logged and None is returned.

    For example to get the package ids of "httpd" and "apr" packages:
        ids = koji_multicall_map(session, session.getPackageID, ["httpd", "apr"])
        # ids is now [280, 632]

    :param KojiSessions koji_session: KojiSession to use for multicall.
    :param object koji_session_fnc: Python object representing the KojiSession method to call.
    :param list list_of_args: List of args which are passed to each call of koji_session_fnc.
    :param list list_of_kwargs: List of kwargs which are passed to each call of koji_session_fnc.
    """
    if list_of_args is None and list_of_kwargs is None:
        raise ProgrammingError("One of list_of_args or list_of_kwargs must be set.")

    if (type(list_of_args) not in [type(None), list] or
            type(list_of_kwargs) not in [type(None), list]):
        raise ProgrammingError("list_of_args and list_of_kwargs must be list or None.")

    if list_of_kwargs is None:
        list_of_kwargs = [{}] * len(list_of_args)
    if list_of_args is None:
        list_of_args = [[]] * len(list_of_kwargs)

    if len(list_of_args) != len(list_of_kwargs):
        raise ProgrammingError("Length of list_of_args and list_of_kwargs must be the same.")

    koji_session.multicall = True
    for args, kwargs in zip(list_of_args, list_of_kwargs):
        if type(args) != list:
            args = [args]
        if type(kwargs) != dict:
            raise ProgrammingError("Every item in list_of_kwargs must be a dict")
        koji_session_fnc(*args, **kwargs)

    try:
        responses = koji_session.multiCall(strict=True)
    except Exception:
        log.exception("Exception raised for multicall of method %r with args %r, %r:",
                      koji_session_fnc, args, kwargs)
        return None

    if not responses:
        log.error("Koji did not return response for multicall of %r", koji_session_fnc)
        return None
    if type(responses) != list:
        log.error("Fault element was returned for multicall of method %r: %r",
                  koji_session_fnc, responses)
        return None

    results = []

    # For the response specification, see
    # https://web.archive.org/web/20060624230303/http://www.xmlrpc.com/discuss/msgReader$1208?mode=topic
    # Relevant part of this:
    # Multicall returns an array of responses. There will be one response for each call in
    # the original array. The result will either be a one-item array containing the result value,
    # or a struct of the form found inside the standard <fault> element.
    for response, args, kwargs in zip(responses, list_of_args, list_of_kwargs):
        if type(response) == list:
            if not response:
                log.error("Empty list returned for multicall of method %r with args %r, %r",
                          koji_session_fnc, args, kwargs)
                return None
            results.append(response[0])
        else:
            log.error("Unexpected data returned for multicall of method %r with args %r, %r: %r",
                      koji_session_fnc, args, kwargs, response)
            return None

    return results


@module_build_service.utils.retry(wait_on=(xmlrpclib.ProtocolError, koji.GenericError))
def koji_retrying_multicall_map(*args, **kwargs):
    """
    Retrying version of koji_multicall_map. This tries to retry the Koji call
    in case of koji.GenericError or xmlrpclib.ProtocolError.

    Please refer to koji_multicall_map for further specification of arguments.
    """
    return koji_multicall_map(*args, **kwargs)


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
        self.module = module
        self.mmd = module.mmd()
        self.config = config
        self.tag_name = tag_name
        self.__prep = False
        log.debug("Using koji profile %r" % config.koji_profile)
        log.debug("Using koji_config: %s" % config.koji_config)

        self.koji_session = self.get_session(config, owner)
        self.arches = config.koji_arches

        # Handle BASE_MODULE_KOJI_ARCHES. Find out the base modules in buildrequires
        # section of XMD and set the Koji tag arches according to it.
        if "mbs" in self.mmd.get_xmd().keys():
            for req_name, req_data in self.mmd.get_xmd()["mbs"]["buildrequires"].items():
                ns = ":".join([req_name, req_data["stream"]])
                if ns in config.base_module_koji_arches:
                    self.arches = config.base_module_koji_arches[ns]
                    break

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
        builds = [self.koji_session.getBuild(a, strict=True) for a in artifacts or []]
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
    def _get_filtered_rpms_on_self_dep(module_build, filtered_rpms_of_dep):
        # filtered_rpms will contain the NVRs of non-reusable component's RPMs
        filtered_rpms = list(set(filtered_rpms_of_dep))
        with models.make_session(conf) as db_session:
            # Get a module build that can be reused, which will likely be the
            # build dep that is used since it relies on itself
            reusable_module = get_reusable_module(db_session, module_build)
            if not reusable_module:
                return filtered_rpms
            koji_session = KojiModuleBuilder.get_session(conf, None)
            # Get all the RPMs and builds of the reusable module in Koji
            rpms, builds = koji_session.listTaggedRPMS(reusable_module.koji_tag, latest=True)
            # Convert the list to a dict where each key is the build_id
            builds = {build['build_id']: build for build in builds}
            # Create a mapping of package (SRPM) to the RPMs in NVR format
            package_to_rpms = {}
            for rpm in rpms:
                package = builds[rpm['build_id']]['name']
                if package not in package_to_rpms:
                    package_to_rpms[package] = []
                package_to_rpms[package].append(kobo.rpmlib.make_nvr(rpm))

            components_in_module = [c.package for c in module_build.component_builds]
            reusable_components = get_reusable_components(
                db_session, module_build, components_in_module,
                previous_module_build=reusable_module)
            # Loop through all the reusable components to find if any of their RPMs are
            # being filtered
            for reusable_component in reusable_components:
                # reusable_component will be None if the component can't be reused
                if not reusable_component:
                    continue
                # We must get the component name from the NVR and not from
                # reusable_component.package because macros such as those used
                # by SCLs can change the name of the underlying build
                component_name = kobo.rpmlib.parse_nvr(reusable_component.nvr)['name']

                if component_name not in package_to_rpms:
                    continue

                # Loop through the RPMs associted with the reusable component
                for nvr in package_to_rpms[component_name]:
                    parsed_nvr = kobo.rpmlib.parse_nvr(nvr)
                    # Don't compare with the epoch
                    parsed_nvr['epoch'] = None
                    # Loop through all the filtered RPMs to find a match with the reusable
                    # component's RPMs.
                    for nvr2 in list(filtered_rpms):
                        parsed_nvr2 = kobo.rpmlib.parse_nvr(nvr2)
                        # Don't compare with the epoch
                        parsed_nvr2['epoch'] = None
                        # Only remove the filter if we are going to reuse a component with
                        # the same exact NVR
                        if parsed_nvr == parsed_nvr2:
                            filtered_rpms.remove(nvr2)
                            # Since filtered_rpms was cast to a set and then back
                            # to a list above, we know there won't be duplicate RPMS,
                            # so we can just break here.
                            break
        return filtered_rpms

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
        for req_name, req_data in mmd.get_xmd()["mbs"]["buildrequires"].items():
            if req_data["filtered_rpms"]:
                filter_conflicts += "# Filtered rpms from %s module:\n" % (
                    req_name)
            # Check if the module depends on itself
            if req_name == module_build.name:
                filtered_rpms = KojiModuleBuilder._get_filtered_rpms_on_self_dep(
                    module_build, req_data["filtered_rpms"])
            else:
                filtered_rpms = req_data["filtered_rpms"]
            for nvr in filtered_rpms:
                parsed_nvr = kobo.rpmlib.parse_nvr(nvr)
                filter_conflicts += "Conflicts: %s = %s:%s-%s\n" % (
                    parsed_nvr["name"], parsed_nvr["epoch"],
                    parsed_nvr["version"], parsed_nvr["release"])

        spec_content = """
%global dist {disttag}
%global disttag module({module_name}:{module_stream}:{module_version}:{module_context})
%global _module_name {module_name}
%global _module_stream {module_stream}
%global _module_version {module_version}
%global _module_context {module_context}

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
mkdir -p %buildroot/etc/rpm 2>/dev/null |:
cp %SOURCE1 %buildroot/etc/rpm/macros.zz-modules
chmod 644 %buildroot/etc/rpm/macros.zz-modules


%files
/etc/rpm/macros.zz-modules



%changelog
* {today} Fedora-Modularity - {version}-{release}{disttag}
- autogenerated macro by Module Build Service (MBS)
""".format(disttag=disttag, today=today, name=name, version=version,
           release=release,
           module_name=module_build.name,
           module_stream=module_build.stream,
           module_version=module_build.version,
           module_context=module_build.context,
           filter_conflicts=filter_conflicts)

        modulemd_macros = ""
        rpm_buildopts = mmd.get_rpm_buildopts()
        if rpm_buildopts:
            modulemd_macros = rpm_buildopts.get('macros')

        macros_content = """

# General macros set by MBS

%dist {disttag}
%disttag module({module_name}:{module_stream}:{module_version}:{module_context})
%_module_build 1
%_module_name {module_name}
%_module_stream {module_stream}
%_module_version {module_version}
%_module_context {module_context}

# Macros set by module author:

{modulemd_macros}
""".format(disttag=disttag, module_name=module_build.name,
           module_stream=module_build.stream,
           module_version=module_build.version,
           module_context=module_build.context,
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
        execute_cmd(['rpmbuild', '-bs', '%s.spec' % name,
                     '--define', '_topdir %s' % td,
                     '--define', '_sourcedir %s' % sources_dir],
                    cwd=td, stdout=null_fd)
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
        # Timeout after 10 minutes.  The default is 12 hours.
        koji_config["timeout"] = 60 * 10

        address = koji_config.server
        authtype = koji_config.authtype
        log.info("Connecting to koji %r with %r." % (address, authtype))
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
                    ccache=ccache
                )
            else:
                koji_session.krb_login(ccache=ccache)
        elif authtype == "ssl":
            koji_session.ssl_login(
                os.path.expanduser(koji_config.cert),
                None,
                os.path.expanduser(koji_config.serverca)
            )
        else:
            raise ValueError("Unrecognized koji authtype %r" % authtype)

        return koji_session

    def buildroot_connect(self, groups):
        log.info("%r connecting buildroot." % self)

        # Check if the build_tag exists, because there are Koji calls later which must be called
        # only if we are creating the build_tag for first time.
        build_tag_exists = self.koji_session.getTag(self.tag_name + "-build")

        # Create or update individual tags
        # the main tag needs arches so pungi can dump it
        self.module_tag = self._koji_create_tag(
            self.tag_name, self.arches, perm="admin")
        self.module_build_tag = self._koji_create_tag(
            self.tag_name + "-build", self.arches, perm="admin")

        self._koji_whitelist_packages(
            self.mmd.props.buildopts.props.rpm_whitelist or self.components)

        # If we have just created the build tag in this buildroot_connect call, block all
        # the components in `blocked_packages` list. We want to do that just once, because
        # there might be some unblocked packages later and we would block them again...
        if not build_tag_exists:
            xmd = self.mmd.get_xmd()
            if "mbs_options" in xmd.keys() and "blocked_packages" in xmd["mbs_options"].keys():
                self._koji_block_packages(xmd["mbs_options"]["blocked_packages"])

        @module_build_service.utils.retry(wait_on=SysCallError, interval=5)
        def add_groups():
            return self._koji_add_groups_to_tag(
                dest_tag=self.module_build_tag,
                groups=groups,
            )
        add_groups()

        # Koji targets can only be 50 characters long, but the generate_koji_tag function
        # checks the length with '-build' at the end, but we know we will never append '-build',
        # so we can safely have the name check be more characters
        target_length = 50 + len('-build')
        target = module_build_service.utils.generate_koji_tag(
            self.module.name, self.module.stream, self.module.version, self.module.context,
            target_length)
        # Add main build target.
        self.module_target = self._koji_add_target(target, self.module_build_tag, self.module_tag)

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

        xmd = self.mmd.get_xmd()
        if "mbs_options" in xmd.keys() and "blocked_packages" in xmd["mbs_options"].keys():
            packages = [kobo.rpmlib.parse_nvr(nvr)["name"] for nvr in artifacts]
            packages = [package for package in packages
                        if package in xmd["mbs_options"]["blocked_packages"]]
            if packages:
                self._koji_unblock_packages(packages)

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

    def tag_artifacts(self, artifacts, dest_tag=True):
        """ Tag the provided artifacts to the module tag
        :param artifacts: a list of NVRs to tag
        :kwarg dest_tag: a boolean determining if the destination or build tag should be used
        :return: None
        """
        if dest_tag:
            tag = self._get_tag(self.module_tag)['id']
            tagged_nvrs = self._get_tagged_nvrs(self.module_tag['name'])
        else:
            tag = self._get_tag(self.module_build_tag)['id']
            tagged_nvrs = self._get_tagged_nvrs(self.module_build_tag['name'])

        self.koji_session.multicall = True
        for nvr in artifacts:
            if nvr in tagged_nvrs:
                continue

            log.info("%r tagging %r into %r" % (self, nvr, tag))
            self.koji_session.tagBuild(tag, nvr)
        self.koji_session.multiCall(strict=True)

    def untag_artifacts(self, artifacts):
        """ Untag the provided artifacts from the module destination and build tag
        :param artifacts: a list of NVRs to untag
        :return: None
        """
        build_tag_name = self.tag_name + '-build'
        dest_tag = self._get_tag(self.tag_name, strict=False)
        build_tag = self._get_tag(build_tag_name, strict=False)
        # Get the NVRs in the tags to make sure the builds exist and they're tagged before
        # untagging them
        if dest_tag:
            dest_tagged_nvrs = self._get_tagged_nvrs(dest_tag['name'])
        else:
            log.info('The tag "{0}" doesn\'t exist'.format(self.tag_name))
            dest_tagged_nvrs = []
        if build_tag:
            build_tagged_nvrs = self._get_tagged_nvrs(build_tag['name'])
        else:
            log.info('The tag "{0}" doesn\'t exist'.format(build_tag_name))
            build_tagged_nvrs = []

        # If there is nothing to untag, then just return
        if not dest_tagged_nvrs and not build_tagged_nvrs:
            return

        self.koji_session.multicall = True
        for nvr in artifacts:
            if nvr in dest_tagged_nvrs:
                log.info("%r untagging %r from %r" % (self, nvr, dest_tag['id']))
                self.koji_session.untagBuild(dest_tag['id'], nvr)
            if nvr in build_tagged_nvrs:
                log.info("%r untagging %r from %r" % (self, nvr, build_tag['id']))
                self.koji_session.untagBuild(build_tag['id'], nvr)
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

    def recover_orphaned_artifact(self, component_build):
        """
        Searches for a complete build of an artifact belonging to the module and sets the
        component_build in the MBS database to the found build. This usually returns nothing since
        these builds should *not* exist.
        :param artifact_name: a ComponentBuild object
        :return: a list of msgs that MBS needs to process
        """
        opts = {'latest': True, 'package': component_build.package, 'inherit': False}
        build_tagged = self.koji_session.listTagged(self.module_build_tag['name'], **opts)
        dest_tagged = None
        # Only check the destination tag if the component is not a build_time_only component
        if not component_build.build_time_only:
            dest_tagged = self.koji_session.listTagged(self.module_tag['name'], **opts)
        for rv in [build_tagged, dest_tagged]:
            if rv and len(rv) != 1:
                raise ValueError("Expected exactly one item in list. Got %s" % rv)

        build = None
        if build_tagged:
            build = build_tagged[0]
        elif dest_tagged:
            build = dest_tagged[0]

        if not build:
            # If the build cannot be found in the tags, it may be untagged as a result
            # of some earlier inconsistent situation. Let's find the task_info
            # based on the list of untagged builds
            release = module_build_service.utils.get_rpm_release(self.module)
            untagged = self.koji_session.untaggedBuilds(name=component_build.package)
            for untagged_build in untagged:
                if untagged_build["release"].endswith(release):
                    nvr = "{name}-{version}-{release}".format(**untagged_build)
                    build = self.koji_session.getBuild(nvr)
                    break
        further_work = []
        # If the build doesn't exist, then return
        if not build:
            return further_work

        # Start setting up MBS' database to use the existing build
        log.info('Skipping build of "{0}" since it already exists.'.format(build['nvr']))
        # Set it to COMPLETE so it doesn't count towards the concurrent component threshold
        component_build.state = koji.BUILD_STATES['COMPLETE']
        component_build.nvr = build['nvr']
        component_build.task_id = build['task_id']
        component_build.state_reason = 'Found existing build'
        nvr_dict = kobo.rpmlib.parse_nvr(component_build.nvr)
        # Trigger a completed build message
        further_work.append(module_build_service.messaging.KojiBuildChange(
            'recover_orphaned_artifact: fake message', build['build_id'],
            build['task_id'], koji.BUILD_STATES['COMPLETE'], component_build.package,
            nvr_dict['version'], nvr_dict['release'], component_build.module_build.id))

        component_tagged_in = []
        if build_tagged:
            component_tagged_in.append(self.module_build_tag['name'])
        else:
            # Tag it in the build tag if it's not there
            self.tag_artifacts([component_build.nvr], dest_tag=False)
        if dest_tagged:
            component_tagged_in.append(self.module_tag['name'])
        for tag in component_tagged_in:
            log.info('The build being skipped isn\'t tagged in the "{0}" tag. Will send a '
                     'message to the tag handler'.format(tag))
            further_work.append(module_build_service.messaging.KojiTagChange(
                'recover_orphaned_artifact: fake message', tag, component_build.package,
                component_build.nvr))
        return further_work

    def build(self, artifact_name, source):
        """
        :param artifact_name: a string of the name of the artifact
        :param source: a string of the scmurl to the spec repository
        :return: 4-tuple of the form (koji build task id, state, reason, nvr)
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
        try:
            self.koji_session.cancelTask(task_id)
        except Exception as error:
            log.error('Failed to cancel task ID {0} in Koji. The error '
                      'message was: {1}'.format(task_id, str(error)))

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

        xmd = self.mmd.get_xmd()
        if "mbs_options" in xmd.keys() and "repo_include_all" in xmd["mbs_options"].keys():
            opts['extra']['repo_include_all'] = xmd["mbs_options"]["repo_include_all"]

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

    def _koji_block_packages(self, packages):
        """
        Blocks the `packages` for the module_build_tag.
        """
        log.info("Blocking packages in tag %s: %r", self.module_build_tag["name"], packages)
        args = [[self.module_build_tag["name"], package] for package in packages]
        koji_multicall_map(self.koji_session, self.koji_session.packageListBlock, args)

    def _koji_unblock_packages(self, packages):
        """
        Unblocks the `packages` for the module_build_tag.
        """
        log.info("Unblocking packages in tag %s: %r", self.module_build_tag["name"], packages)
        args = [[self.module_build_tag["name"], package] for package in packages]
        koji_multicall_map(self.koji_session, self.koji_session.packageListUnblock, args)

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

    @classmethod
    def get_average_build_time(cls, component):
        """
        Get the average build time of the component from Koji
        :param component: a ComponentBuild object
        :return: a float of the average build time in seconds
        """
        # If the component has not been built before, then None is returned. Instead, let's
        # return 0.0 so the type is consistent
        koji_session = KojiModuleBuilder.get_session(conf, None)
        return koji_session.getAverageBuildDuration(component) or 0.0

    @classmethod
    def get_build_weights(cls, components):
        """
        Returns a dict with component name as a key and float number
        representing the overall Koji weight of a component build.
        The weight is sum of weights of all tasks in a previously done modular
        build of a component.

        :param list components: List of component names.
        :rtype: dict
        :return: {component_name: weight_as_float, ...}
        """

        koji_session = KojiModuleBuilder.get_session(conf, None)

        # Get our own userID, so we can limit the builds to only modular builds
        user_info = koji_session.getLoggedInUser()
        if not user_info or "id" not in user_info:
            log.warn("Koji.getLoggedInUser() failed while getting build weight.")
            return cls.compute_weights_from_build_time(components)
        mbs_user_id = user_info["id"]

        # Get the Koji PackageID for every component in single Koji call.
        # If some package does not exist in Koji, component_ids will be None.
        component_ids = koji_retrying_multicall_map(
            koji_session, koji_session.getPackageID, list_of_args=components)
        if not component_ids:
            return cls.compute_weights_from_build_time(components)

        # Prepare list of queries to call koji_session.listBuilds
        build_queries = []
        for component_id in component_ids:
            build_queries.append({
                "packageID": component_id,
                "userID": mbs_user_id,
                "state": koji.BUILD_STATES["COMPLETE"],
                "queryOpts": {"order": "-build_id", "limit": 1}})

        # Get the latest Koji build created by MBS for every component in single Koji call.
        builds_per_component = koji_retrying_multicall_map(
            koji_session, koji_session.listBuilds, list_of_kwargs=build_queries)
        if not builds_per_component:
            return cls.compute_weights_from_build_time(components)

        # Get list of task_ids associated with the latest build in builds.
        # For some packages, there may not be a build done by MBS yet.
        # We store such packages in `components_without_build` and later
        # compute the weight by compute_weights_from_build_time().
        # For others, we will continue by examining weights of all tasks
        # belonging to that build later.
        task_ids = []
        components_with_build = []
        components_without_build = []
        for builds, component_name in zip(builds_per_component, components):
            if not builds:
                # No build for this component.
                components_without_build.append(component_name)
                continue

            latest_build = builds[0]
            task_id = latest_build["task_id"]

            if not task_id:
                # No task_id for this component, this can happen for imported
                # component builds.
                components_without_build.append(component_name)
                continue

            components_with_build.append(component_name)
            task_ids.append(task_id)

        weights = {}

        # For components without any build, fallback to weights computation based on
        # the average time to build.
        weights.update(cls.compute_weights_from_build_time(components_without_build))

        # For components with a build, get the list of tasks associated with this build
        # and compute the weight for each component build as sum of weights of all tasks.
        tasks_per_latest_build = koji_retrying_multicall_map(
            koji_session, koji_session.getTaskDescendents, list_of_args=task_ids)
        if not tasks_per_latest_build:
            return cls.compute_weights_from_build_time(components_with_build)

        for tasks, component_name in zip(tasks_per_latest_build, components_with_build):
            # Compute overall weight of this build. This is sum of weights
            # of all tasks in a build.
            weight = 0
            for task in tasks.values():
                weight += sum([t["weight"] for t in task])
            weights[component_name] = weight

        return weights

    @classmethod
    def get_built_rpms_in_module_build(cls, mmd):
        """
        :param Modulemd mmd: Modulemd to get the built RPMs from.
        :return: list of NVRs
        """
        with models.make_session(conf) as db_session:
            build = models.ModuleBuild.get_build_from_nsvc(
                db_session, mmd.get_name(), mmd.get_stream(), mmd.get_version(),
                mmd.get_context())
            koji_session = KojiModuleBuilder.get_session(conf, None)
            rpms = koji_session.listTaggedRPMS(build.koji_tag, latest=True)[0]
            nvrs = set(kobo.rpmlib.make_nvr(rpm, force_epoch=True) for rpm in rpms)
            return list(nvrs)

    def finalize(self):
        # Only import to koji CG if the module is "done".
        if self.config.koji_enable_content_generator and self.module.state == 3:
            cg = KojiContentGenerator(self.module, self.config)
            cg.koji_import()

    @staticmethod
    def get_rpm_module_tag(rpm):
        """
        Returns koji tag of a given rpm filename.

        :param str rpm: the *.rpm filename of a rpm
        :rtype: str
        :return: koji tag
        """

        session = KojiModuleBuilder.get_session(conf, None)
        rpm_md = session.getRPM(rpm)
        if not rpm_md:
            return None

        tags = []
        koji_tags = session.listTags(rpm_md["build_id"])
        for t in koji_tags:
            if not t["name"].endswith("-build") and t["name"].startswith("module-"):
                tags.append(t["name"])

        return tags
