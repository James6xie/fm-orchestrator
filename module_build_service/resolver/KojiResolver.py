# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
from itertools import groupby

from module_build_service.resolver.DBResolver import DBResolver
from module_build_service import conf, models, log


class KojiResolver(DBResolver):
    """
    Resolver using Koji server running in infrastructure.
    """

    backend = "koji"

    def _filter_inherited(self, koji_session, module_builds, top_tag, event):
        """
        Look at the tag inheritance and keep builds only from the topmost tag.

        For example, we have "foo:bar:1" and "foo:bar:2" builds. We also have "foo-tag" which
        inherits "foo-parent-tag". The "foo:bar:1" is tagged in the "foo-tag". The "foo:bar:2"
        is tagged in the "foo-parent-tag".

        In this case, this function filters out the foo:bar:2, because "foo:bar:1" is tagged
        lower in the inheritance tree in the "foo-tag".

        For normal RPMs, using latest=True for listTagged() call, Koji would automatically do
        this, but it does not understand streams, so we have to reimplement it here.

        :param KojiSession koji_session: Koji session.
        :param list module_builds: List of builds as returned by KojiSession.listTagged method.
        :param str top_tag: The top Koji tag.
        :param dict event: Koji event defining the time at which the `module_builds` have been
            fetched.
        :return list: Filtered list of builds.
        """
        inheritance = [
            tag["name"] for tag in koji_session.getFullInheritance(top_tag, event=event["id"])
        ]

        def keyfunc(mb):
            return (mb["name"], mb["version"])

        result = []

        # Group modules by Name-Stream
        for _, builds in groupby(sorted(module_builds, key=keyfunc), keyfunc):
            builds = list(builds)
            # For each N-S combination find out which tags it's in
            available_in = set(build["tag_name"] for build in builds)

            # And find out which is the topmost tag
            for tag in [top_tag] + inheritance:
                if tag in available_in:
                    break

            # And keep only builds from that topmost tag
            result.extend(build for build in builds if build["tag_name"] == tag)

        return result

    def get_buildrequired_modulemds(self, name, stream, base_module_mmd):
        """
        Returns modulemd metadata of all module builds with `name` and `stream` which are tagged
        in the Koji tag defined in `base_module_mmd`.

        :param str name: Name of module to return.
        :param str stream: Stream of module to return.
        :param Modulemd base_module_mmd: Base module metadata.
        :return list: List of modulemd metadata.
        """
        # Get the `koji_tag_with_modules`. If the `koji_tag_with_modules` is not configured for
        # the base module, fallback to DBResolver.
        tag = base_module_mmd.get_xmd().get("mbs", {}).get("koji_tag_with_modules")
        if not tag:
            log.info(
                "The %s does not define 'koji_tag_with_modules'. Falling back to DBResolver." % (
                    base_module_mmd.get_nsvc()))
            return DBResolver.get_buildrequired_modulemds(self, name, stream, base_module_mmd)

        # Create KojiSession. We need to import here because of circular dependencies.
        from module_build_service.builder.KojiModuleBuilder import KojiModuleBuilder
        koji_session = KojiModuleBuilder.get_session(conf, login=False)
        event = koji_session.getLastEvent()

        # List all the modular builds in the modular Koji tag.
        # We cannot use latest=True here, because we need to get all the
        # available streams of all modules. The stream is represented as
        # "version" in Koji build and with latest=True, Koji would return
        # only builds with the highest version.
        # We also cannot ask for particular `stream`, because Koji does not support that.
        module_builds = koji_session.listTagged(
            tag, inherit=True, type="module", package=name, event=event["id"])

        # Filter out different streams
        normalized_stream = stream.replace("-", "_")
        module_builds = [b for b in module_builds if b["version"] == normalized_stream]

        # Filter out builds inherited from non-top tag
        module_builds = self._filter_inherited(koji_session, module_builds, tag, event)

        # Find the latest builds of all modules. This does the following:
        # - Sorts the module_builds descending by Koji NVR (which maps to NSV
        #   for modules). Split release into modular version and context, and
        #   treat version as numeric.
        # - Groups the sorted module_builds by NV (NS in modular world).
        #   In each resulting `ns_group`, the first item is actually build
        #   with the latest version (because the list is still sorted by NVR).
        # - Groups the `ns_group` again by "release" ("version" in modular
        #   world) to just get all the "contexts" of the given NSV. This is
        #   stored in `nsv_builds`.
        # - The `nsv_builds` contains the builds representing all the contexts
        #   of the latest version for give name-stream, so add them to
        #   `latest_builds`.
        def _key(build):
            ver, ctx = build["release"].split(".", 1)
            return build["name"], build["version"], int(ver), ctx

        latest_builds = []
        module_builds = sorted(module_builds, key=_key, reverse=True)
        for _, ns_builds in groupby(
                module_builds, key=lambda x: ":".join([x["name"], x["version"]])):
            for _, nsv_builds in groupby(
                    ns_builds, key=lambda x: x["release"].split(".")[0]):
                latest_builds += list(nsv_builds)
                break

        # For each latest module build, find the matching ModuleBuild and store its modulemd
        # in `mmds`.
        mmds = []
        for build in latest_builds:
            version, context = build["release"].split(".")
            module = models.ModuleBuild.get_build_from_nsvc(
                self.db_session, name, stream, version, context)
            if not module:
                raise ValueError(
                    "Module %s is tagged in the %s Koji tag, but does not exist "
                    "in MBS DB." % (":".join([name, stream, version, context]), tag))
            mmds.append(module.mmd())

        return mmds

    def get_compatible_base_module_modulemds(self, *args, **kwargs):
        """
        For KojiResolver, this method returns always an empty list. The compatible modules are
        defined by the Koji tag inheritance, so there is no need to find out the compatible
        base modules on MBS side.
        """
        return []
