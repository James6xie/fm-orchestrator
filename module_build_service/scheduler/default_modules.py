# -*- coding: utf-8 -*-
# Copyright (c) 2019  Red Hat, Inc.
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
import errno
import os

import dnf
import kobo.rpmlib
import requests

from module_build_service import conf, log, models
from module_build_service.builder.KojiModuleBuilder import (
    koji_retrying_multicall_map, KojiModuleBuilder,
)
from module_build_service.errors import UnprocessableEntity
from module_build_service.utils.request_utils import requests_session
from module_build_service.resolver import system_resolver as resolver


def add_default_modules(db_session, mmd, arches):
    """
    Add default modules as buildrequires to the input modulemd.

    The base modules that are buildrequired can optionally link their default modules by specifying
    a URL to a text file in xmd.mbs.default_modules_url. Any default module that isn't in the
    database will be logged and ignored.

    :param db_session: a SQLAlchemy database session
    :param Modulemd.ModuleStream mmd: the modulemd of the module to add the module defaults to
    :param list arches: the arches to limit the external repo queries to; this should be the arches
        the module will be built with
    :raises RuntimeError: if the buildrequired base module isn't in the database or the default
        modules list can't be downloaded
    """
    log.info("Finding the default modules to include as buildrequires")
    xmd = mmd.get_xmd()
    buildrequires = xmd["mbs"]["buildrequires"]
    defaults_added = False

    for module_name in conf.base_module_names:
        bm_info = buildrequires.get(module_name)
        if bm_info is None:
            log.debug(
                "The base module %s is not a buildrequire of the submitted module %s",
                module_name, mmd.get_nsvc(),
            )
            continue

        bm = models.ModuleBuild.get_build_from_nsvc(
            db_session, module_name, bm_info["stream"], bm_info["version"], bm_info["context"],
        )
        bm_nsvc = ":".join([
            module_name, bm_info["stream"], bm_info["version"], bm_info["context"],
        ])
        if not bm:
            raise RuntimeError("Failed to retrieve the module {} from the database".format(bm_nsvc))

        bm_mmd = bm.mmd()
        bm_xmd = bm_mmd.get_xmd()
        default_modules_url = bm_xmd.get("mbs", {}).get("default_modules_url")
        if not default_modules_url:
            log.debug("The base module %s does not have any default modules", bm_nsvc)
            continue

        try:
            rv = requests_session.get(default_modules_url, timeout=10)
        except requests.RequestException:
            msg = (
                "The connection failed when getting the default modules associated with {}"
                .format(bm_nsvc)
            )
            log.exception(msg)
            raise RuntimeError(msg)

        if not rv.ok:
            log.error(
                "The request to get the default modules associated with %s failed with the status "
                'code %d and error "%s"',
                bm_nsvc, rv.status_code, rv.text,
            )
            raise RuntimeError(
                "Failed to retrieve the default modules for {}".format(bm_mmd.get_nsvc())
            )

        default_modules = [m.strip() for m in rv.text.strip().split("\n")]
        for default_module in default_modules:
            try:
                name, stream = default_module.split(":")
            except ValueError:
                log.error(
                    'The default module "%s" from %s is in an invalid format',
                    default_module, rv.url,
                )
                continue

            if name in buildrequires:
                conflicting_stream = buildrequires[name]["stream"]
                if stream == conflicting_stream:
                    log.info("The default module %s is already a buildrequire", default_module)
                    continue

                log.info(
                    "The default module %s will not be added as a buildrequire since %s:%s "
                    "is already a buildrequire",
                    default_module, name, conflicting_stream,
                )
                continue

            try:
                # We are reusing resolve_requires instead of directly querying the database since it
                # provides the exact format that is needed for mbs.xmd.buildrequires.
                #
                # Only one default module is processed at a time in resolve_requires so that we
                # are aware of which modules are not in the database, and can add those that are as
                # buildrequires.
                resolved = resolver.resolve_requires([default_module])
            except UnprocessableEntity:
                log.warning(
                    "The default module %s from %s is not in the database and couldn't be added as "
                    "a buildrequire",
                    default_module, bm_nsvc
                )
                continue

            nsvc = ":".join([name, stream, resolved[name]["version"], resolved[name]["context"]])
            log.info("Adding the default module %s as a buildrequire", nsvc)
            buildrequires.update(resolved)
            defaults_added = True

    # For now, we only want to run _handle_collisions if default modules were added, otherwise
    # still rely on the old approach of running ursine.handle_stream_collision_modules. This is
    # done in the init handler.
    if defaults_added:
        mmd.set_xmd(xmd)
        # For now, only handle collisions when defaults are used. In the future, this can be enabled
        # for all module builds when Ursa-Major is no longer supported.
        _handle_collisions(mmd, arches)


def _handle_collisions(mmd, arches):
    """
    Find any RPMs in the buildrequired base modules that collide with the buildrequired modules.

    If a buildrequired module contains RPMs that overlap with RPMs in the buildrequired base
    modules, then the NEVRAs of the overlapping RPMs in the base modules will be added as conflicts
    in the input modulemd.

    :param Modulemd.ModuleStream mmd: the modulemd to find the collisions
    :param list arches: the arches to limit the external repo queries to
    :raise RuntimeError: when a Koji query fails
    """
    log.info("Finding any buildrequired modules that collide with the RPMs in the base modules")
    bm_tags = set()
    non_bm_tags = set()
    xmd = mmd.get_xmd()
    buildrequires = xmd["mbs"]["buildrequires"]
    for name, info in buildrequires.items():
        if not info["koji_tag"]:
            continue

        if name in conf.base_module_names:
            bm_tags.add(info["koji_tag"])
        else:
            non_bm_tags.add(info["koji_tag"])

    if not (bm_tags and non_bm_tags):
        log.info(
            "Skipping the collision check since collisions are not possible with these "
            "buildrequires"
        )
        return

    log.debug(
        "Querying Koji for the latest RPMs from the buildrequired base modules from the tags: %s",
        ", ".join(bm_tags),
    )
    koji_session = KojiModuleBuilder.get_session(conf, login=False)
    bm_rpms = _get_rpms_from_tags(koji_session, bm_tags, arches)
    # The keys are base module RPM names and the values are sets of RPM NEVRAs with that name
    name_to_nevras = {}
    for bm_rpm in bm_rpms:
        rpm_name = kobo.rpmlib.parse_nvra(bm_rpm)["name"]
        name_to_nevras.setdefault(rpm_name, set())
        name_to_nevras[rpm_name].add(bm_rpm)
    # Clear this out of RAM as soon as possible since this value can be huge
    del bm_rpms

    log.debug(
        "Querying Koji for the latest RPMs from the other buildrequired modules from the tags: %s",
        ", ".join(non_bm_tags),
    )
    # This will contain any NEVRAs of RPMs in the base module tag with the same name as those in the
    # buildrequired modules
    conflicts = set()
    non_bm_rpms = _get_rpms_from_tags(koji_session, non_bm_tags, arches)
    for rpm in non_bm_rpms:
        rpm_name = kobo.rpmlib.parse_nvra(rpm)["name"]
        if rpm_name in name_to_nevras:
            conflicts = conflicts | name_to_nevras[rpm_name]

    # Setting these values will keep ursine.handle_stream_collision_modules from running.
    # These values are handled in KojiModuleBuilder.get_disttag_srpm.
    xmd["mbs"]["ursine_rpms"] = list(conflicts)
    xmd["mbs"]["stream_collision_modules"] = []
    mmd.set_xmd(xmd)


def _get_rpms_from_tags(koji_session, tags, arches):
    """
    Get the RPMs in NEVRA form (tagged or external repos) of the input tags.

    :param koji.ClientSession koji_session: the Koji session to use to query
    :param list tags: the list of tags to get the RPMs from
    :param list arches: the arches to limit the external repo queries to
    :return: the set of RPMs in NEVRA form of the input tags
    :rtype: set
    :raises RuntimeError: if the Koji query fails
    """
    log.debug("Get the latest RPMs from the tags: %s", ", ".join(tags))
    kwargs = [{"latest": True, "inherit": True}] * len(tags)
    tagged_results = koji_retrying_multicall_map(
        koji_session, koji_session.listTaggedRPMS, tags, kwargs,
    )
    if not tagged_results:
        raise RuntimeError(
            "Getting the tagged RPMs of the following Koji tags failed: {}"
            .format(", ".join(tags))
        )

    nevras = set()
    for tagged_result in tagged_results:
        rpms, _ = tagged_result
        for rpm_dict in rpms:
            nevra = kobo.rpmlib.make_nvra(rpm_dict, force_epoch=True)
            nevras.add(nevra)

    repo_results = koji_retrying_multicall_map(koji_session, koji_session.getExternalRepoList, tags)
    if not repo_results:
        raise RuntimeError(
            "Getting the external repos of the following Koji tags failed: {}"
            .format(", ".join(tags)),
        )
    for repos in repo_results:
        for repo in repos:
            # Use the repo ID in the cache directory name in case there is more than one external
            # repo associated with the tag
            cache_dir_name = "{}-{}".format(repo["tag_name"], repo["external_repo_id"])
            nevras = nevras | _get_rpms_in_external_repo(repo["url"], arches, cache_dir_name)

    return nevras


def _get_rpms_in_external_repo(repo_url, arches, cache_dir_name):
    """
    Get the available RPMs in the external repo for the provided arches.

    :param str repo_url: the URL of the external repo with the "$arch" variable included
    :param list arches: the list of arches to query the external repo for
    :param str cache_dir_name: the cache directory name under f"{conf.cache_dir}/dnf"
    :return: a set of the RPM NEVRAs
    :rtype: set
    :raise RuntimeError: if the cache is not writeable or the external repo couldn't be loaded
    :raises ValueError: if there is no "$arch" variable in repo URL
    """
    if "$arch" not in repo_url:
        raise ValueError(
            "The external repo {} does not contain the $arch variable".format(repo_url)
        )

    base = dnf.Base()
    dnf_conf = base.conf
    # Expire the metadata right away so that when a repo is loaded, it will always check to see if
    # the external repo has been updated
    dnf_conf.metadata_expire = 0

    cache_location = os.path.join(conf.cache_dir, "dnf", cache_dir_name)
    try:
        # exist_ok=True can't be used in Python 2
        os.makedirs(cache_location, mode=0o0770)
    except OSError as e:
        # Don't fail if the directories already exist
        if e.errno != errno.EEXIST:
            log.exception("Failed to create the cache directory %s", cache_location)
            raise RuntimeError("The MBS cache is not writeable.")

    # Tell DNF to use the cache directory
    dnf_conf.cachedir = cache_location
    # Get rid of everything to be sure it's a blank slate. This doesn't delete the cached repo data.
    base.reset(repos=True, goal=True, sack=True)

    # Add a separate repo for each architecture
    for arch in arches:
        repo_name = "repo_{}".format(arch)
        repo_arch_url = repo_url.replace("$arch", arch)
        base.repos.add_new_repo(repo_name, dnf_conf, baseurl=[repo_arch_url])
        # Load one repo at a time instead of running `base.update_cache()` so that we know which
        # repo fails to load if one does
        try:
            base.repos[repo_name].load()
        except dnf.exceptions.RepoError:
            msg = "Failed to load the external repo {}".format(repo_arch_url)
            log.exception(msg)
            raise RuntimeError(msg)

    base.fill_sack(load_system_repo=False)

    # Return all the available RPMs
    nevras = set()
    for rpm in base.sack.query().available():
        rpm_dict = {
            "arch": rpm.arch,
            "epoch": rpm.epoch,
            "name": rpm.name,
            "release": rpm.release,
            "version": rpm.version,
        }
        nevra = kobo.rpmlib.make_nvra(rpm_dict, force_epoch=True)
        nevras.add(nevra)

    return nevras
