# -*- coding: utf-8 -*-
# Copyright (c) 2018  Red Hat, Inc.
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
# Written by Chenxiong Qi <cqi@redhat.com>

import re

from module_build_service import conf, log, glib
from module_build_service.resolver import system_resolver


"""
This module handles module stream collision with ursine content before a module
is built.

This kind of collision would happen when packages, which are managed by
Ursa-Major, are used to build a module. Let's see an example, when a module foo
buildrequires bar with stream A, however module bar with another stream B was
already added to ursine content by Ursa-Major when it has been built and moved
to ready state. Hence, MBS has to ensure any packages from module bar:B are not
present in the buildroot.

A technical background:

Generally, each module buildrequires a platform module, which is associated
with ursine content by adding an external repository to the platform module's
tag. That repository is generated from a build tag that inherits from a set
modules' koji tag through its tag inheritance hierarchy. Ursa-Major manages
the inheritance relationship.

Stream collision modules are just those modules added to tag inheritance by
Ursa-Major.
"""


def find_build_tags_from_external_repos(koji_session, repo_infos):
    """Find build tags from external repos

    An external repo added to a tag could be an arbitrary external repository.
    Hence, this method tries best to guess the tags from each external repo's
    URL by a regular expression.

    :param repo_infos: list of mappings represeting external repos information.
    :type repo_infos: list[dict]
    :return: a list of tag names.
    :rtype: list[str]
    """
    re_external_repo_url = r'^{}/repos/(.+-build)/latest/\$arch/?$'.format(
        conf.koji_external_repo_url_prefix.rstrip('/'))
    tag_names = []
    for info in repo_infos:
        om = re.match(re_external_repo_url, info['url'])
        if om:
            name = om.groups()[0]
            if koji_session.getTag(name) is None:
                log.warning('Ignore found tag %s because no tag info is found '
                            'with this name.', name)
            else:
                tag_names.append(name)
        else:
            log.warning('The build tag could not be parsed from external repo '
                        '%s whose url is %s.',
                        info['external_repo_name'], info['url'])
    return tag_names


def find_module_koji_tags(koji_session, build_tag):
    """
    Find module koji tags from parents of build tag through the tag inheritance

    MBS supports a few of prefixes which is configured in
    ``conf.koij_tag_prefixes``. Tags with a configured prefix will be
    considered as a koji tag.

    :param koji_session: instance of Koji client session.
    :type koji_session: ClientSession
    :param str build_tag: tag name, which is the build tag inheriting from
        parent tags where module koji tags are contained.
    :return: list of module koji tags.
    :rtype: list[str]
    """
    return [
        data['name'] for data in koji_session.getFullInheritance(build_tag)
        if any(data['name'].startswith(prefix) for prefix in conf.koji_tag_prefixes)
    ]


def get_modulemds_from_ursine_content(tag):
    """Get all modules metadata which were added to ursine content

    Ursine content is the tag inheritance managed by Ursa-Major by adding
    specific modules' koji_tag.

    Background of module build based on ursine content:

    Each module build buildrequires a platform module, which is a presudo-module
    used to connect to an external repository whose packages could be present
    in the buildroot. In practice, the external repo is generated from a build
    tag which could inherit from a few module koji_tags so that those module's
    RPMs could be build dependencies for some specific packages.

    So, this method is to find out all module koji_tags from the build tag
    and return corresponding module metadata.

    :param str tag: a base module's koji_tag.
    :return: list of module metadata. Empty list will be returned if no ursine
        modules metadata is found.
    :rtype: list[Modulemd.Module]
    """
    from module_build_service.builder.KojiModuleBuilder import KojiModuleBuilder
    koji_session = KojiModuleBuilder.get_session(conf, None)
    repos = koji_session.getExternalRepoList(tag)
    build_tags = find_build_tags_from_external_repos(koji_session, repos)
    if not build_tags:
        log.info('No external repo containing ursine content is found.')
        return []
    modulemds = []
    for tag in build_tags:
        koji_tags = find_module_koji_tags(koji_session, tag)
        for koji_tag in koji_tags:
            md = system_resolver.get_modulemd_by_koji_tag(koji_tag)
            if md:
                modulemds.append(md)
            else:
                log.warning('No module is found by koji_tag \'%s\'', koji_tag)
    return modulemds


def find_stream_collision_modules(buildrequired_modules, koji_tag):
    """
    Find out modules from ursine content which are buildrequires but with a
    different stream.

    :param dict buildrequired_modules: a mapping of buildrequires, which is just
        the ``xmd/mbs/buildrequires``. This mapping is used to determine if a module
        found from ursine content is a buildrequire with different stream.
    :param str koji_tag: a base module's koji_tag. Modules will be retrieve from
        ursince content associated with this koji_tag and check if there are
        collision modules.
    :return: a list of NSVC of collision modules. If no collision module is
        found, false value is returned.
    :rtype: list[str]
    """
    ursine_modulemds = get_modulemds_from_ursine_content(koji_tag)
    if not ursine_modulemds:
        log.info('No module metadata is found from ursine content.')
        return

    collision_modules = [
        item.dup_nsvc()
        for item in ursine_modulemds
        # If some module in the ursine content is one of the buildrequires but has
        # different stream, that is what we want to record here, whose RPMs will be
        # excluded from buildroot by adding them into SRPM module-build-macros as
        # Conflicts.
        if (item.get_name() in buildrequired_modules and
            item.get_stream() != buildrequired_modules[item.get_name()]['stream'])
    ]

    for item in collision_modules:
        name, stream, _ = item.split(':', 2)
        log.info('Buildrequired module %s exists in ursine content with '
                 'different stream %s, whose RPMs will be excluded.',
                 name, stream)

    return collision_modules


def record_stream_collision_modules(mmd):
    """
    Find out modules from ursine content and record those that are buildrequire
    module but have different stream.

    Note that, this handle depends on the result of module stream expansion.

    MBS supports multiple base modules via option conf.base_module_names. A base
    module name could be platform in most cases, but there could be others for
    particular cases in practice. So, each expanded base module stored in
    ``xmd/mbs/buildrequires`` will be handled and will have a new
    key/value pair ``stream_collision_modules: [N-S-V-C, ...]``. This key/value
    will be handled in module event handler then.

    As a result, a new item is added xmd/mbs/buildrequires/platform/stream_collision_modules,
    which is a list of NSVC strings. Each of them is the module added to ursine
    content by Ursa-Major.

    :param mmd: a module's metadata which will be built.
    :type mmd: Modulemd.Module
    """
    unpacked_xmd = glib.from_variant_dict(mmd.get_xmd())
    buildrequires = unpacked_xmd['mbs']['buildrequires']

    for module_name in conf.base_module_names:
        base_module_info = buildrequires.get(module_name)
        if base_module_info is None:
            log.warning(
                'Base module %s is not a buildrequire of module %s. '
                'Skip handling module stream collision for this base module.',
                mmd.get_name())
            continue

        modules_nsvc = find_stream_collision_modules(
            buildrequires, base_module_info['koji_tag'])
        if modules_nsvc:
            base_module_info['stream_collision_modules'] = modules_nsvc
        else:
            log.info('No stream collision module is found against base module %s.',
                     module_name)

    mmd.set_xmd(glib.dict_values(unpacked_xmd))
