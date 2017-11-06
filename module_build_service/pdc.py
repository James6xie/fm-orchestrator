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
# Written by Lubos Kocman <lkocman@redhat.com>

"""PDC handler functions."""

import modulemd
from pdc_client import PDCClient
from module_build_service import db
from module_build_service import models
from module_build_service.errors import UnprocessableEntity

import inspect
import pprint
import logging
import six
import copy
import kobo.rpmlib
log = logging.getLogger()


def get_pdc_client_session(config):
    """
    :param config: instance of module_build_service.config.Config
    :return pdc_client.PDCClient instance
    """
    if 'ssl_verify' in inspect.getargspec(PDCClient.__init__).args:
        # New API
        return PDCClient(
            server=config.pdc_url,
            develop=config.pdc_develop,
            ssl_verify=not config.pdc_insecure,
        )
    else:
        # Old API
        return PDCClient(
            server=config.pdc_url,
            develop=config.pdc_develop,
            insecure=config.pdc_insecure,
        )


def get_variant_dict(data):
    """
    :param data: one of following
                    pdc variant_dict {'variant_id': value, 'variant_version': value, }
                    module dict {'name': value, 'version': value }
                    modulemd

    :return final list of module_info which pass repoclosure
    """
    def is_module_dict(data):
        if not isinstance(data, dict):
            return False

        for attr in ('name', 'version'):
            if attr not in data.keys():
                return False
        return True

    def is_variant_dict(data):
        if not isinstance(data, dict):
            return False

        if ('variant_id' not in data or
                ('variant_stream' not in data and
                 'variant_version' not in data)):
            return False
        return True

    def is_modulemd(data):
        return isinstance(data, modulemd.ModuleMetadata)

    def is_module_str(data):
        return isinstance(data, six.string_types)

    result = None

    if is_module_str(data):
        result = variant_dict_from_str(data)

    elif is_modulemd(data):
        result = {'variant_id': data.name}
        # Check if this is an old modulemd that doesn't use the new nomenclature
        if hasattr(data, 'release'):
            result['variant_release'] = data.release
            result['variant_version'] = data.version
        else:
            result['variant_release'] = data.version
            result['variant_version'] = data.stream

    elif is_variant_dict(data):
        result = data.copy()

        # This is a transitionary thing until we've ported PDC away from the old nomenclature
        if 'variant_version' not in result and 'variant_stream' in result:
            result['variant_version'] = result['variant_stream']
            del result['variant_stream']

        # ensure that variant_type is in result
        if 'variant_type' not in result.keys():
            result['variant_type'] = 'module'

    elif is_module_dict(data):
        result = {'variant_id': data['name'], 'variant_version': data['version']}

        if 'release' in data:
            result['variant_release'] = data['release']

        if 'active' in data:
            result['active'] = data['active']

    if not result:
        raise RuntimeError("Couldn't get variant_dict from %s" % data)

    return result


def variant_dict_from_str(module_str):
    """
    :param module_str: a string to match in PDC
    :return module_info dict

    Example minimal module_info:
        {
            'variant_id': module_name,
            'variant_version': module_version,
            'variant_type': 'module'
        }
    """
    log.debug("variant_dict_from_str(%r)" % module_str)
    # best match due several filters not being provided such as variant type ...

    module_info = {}

    release_start = module_str.rfind('-')
    version_start = module_str.rfind('-', 0, release_start)
    module_info['variant_release'] = module_str[release_start + 1:]
    module_info['variant_version'] = module_str[version_start + 1:release_start]
    module_info['variant_id'] = module_str[:version_start]
    module_info['variant_type'] = 'module'

    return module_info


def get_module(session, module_info, strict=False):
    """
    :param session : PDCClient instance
    :param module_info: pdc variant_dict, str, mmd or module dict
    :param strict: Normally this function returns None if no module can be
           found.  If strict=True, then an UnprocessableEntity is raised.

    :return final list of module_info which pass repoclosure
    """

    log.debug("get_module(%r, strict=%r)" % (module_info, strict))
    variant_dict = get_variant_dict(module_info)

    query = dict(
        variant_id=variant_dict['variant_id'],
        variant_version=variant_dict['variant_version'],
    )
    if variant_dict.get('variant_release'):
        query['variant_release'] = variant_dict['variant_release']
    if module_info.get('active'):
        query['active'] = module_info['active']

    # TODO: So far sorting on Fedora prod PDC instance is broken and it sorts
    # only by variant_uid by default. Once the sorting is fixed, we can start
    # using '-variant_release' ordering and just get the first variant from
    # there. But in the meantime, we have to get the first variant with
    # page_size set to 1 to find out how many variants (pages) are there in
    # results set and jump to last one in another query. The last one is always
    # the latest one (the one with the highest version).
    try:
        retval = session['unreleasedvariants/'](page_size=1, **query)
    except Exception as ex:
        log.debug("error during PDC lookup: %r" % ex)
        raise RuntimeError("Error during PDC lookup for module %s" % module_info["name"])

    # Error handling
    if not retval or len(retval["results"]) == 0:
        if strict:
            raise UnprocessableEntity("Failed to find module in PDC %r" % query)
        else:
            return None

    # Jump to last page to latest module release.
    if retval['count'] != 1:
        query['page'] = retval['count']
        retval = session['unreleasedvariants/'](page_size=1, **query)

    results = retval["results"]
    assert len(results) <= 1, pprint.pformat(retval)
    return results[0]


def get_module_tag(session, module_info, strict=False):
    """
    :param session : PDCClient instance
    :param module_info: list of module_info dicts
    :param strict: Normally this function returns None if no module can be
           found.  If strict=True, then an UnprocessableEntity is raised.
    :return: koji tag string
    """
    return get_module(session, module_info, strict=strict)['koji_tag']


def get_module_modulemd(session, module_info, strict=False):
    """
    :param session : PDCClient instance
    :param module_info: list of module_info dicts
    :param strict: Normally this function returns None if no module can be
           found.  If strict=True, then an UnprocessableEntity is raised.
    :return: ModuleMetadata instance
    """
    yaml = None
    module = get_module(session, module_info, strict=strict)
    if module:
        yaml = module['modulemd']

    if not yaml:
        if strict:
            raise UnprocessableEntity(
                "Failed to find modulemd entry in PDC for %r" % module_info)
        else:
            return None

    return _extract_modulemd(yaml, strict=strict)


def _extract_modulemd(yaml, strict=False):
    mmd = modulemd.ModuleMetadata()
    mmd.loads(yaml)
    return mmd


def _get_recursively_required_modules(session, info, modules=None,
                                      strict=False):
    """
    :param session: PDCClient instance
    :param info: pdc variant_dict, str, mmd or module dict
    :param modules: Used by recursion only, list of modules found by previous
                    iteration of this method.
    :param strict: Normally this function returns empty list if no module can
                   be found.  If strict=True, then an UnprocessableEntity is raised.

    Returns list of modules by recursively querying PDC based on a "requires"
    list of an input module represented by `info`. The returned list
    therefore contains all modules the input module "requires".

    If there are some modules loaded by utils.load_local_builds(...), these
    local modules will be used instead of querying PDC for the particular
    module found in local module builds database.

    The returned list contains only "modulemd" and "koji_tag" fields returned
    by PDC, because other fields are not known for local builds.
    """
    modules = modules or []

    variant_dict = get_variant_dict(info)
    local_modules = models.ModuleBuild.local_modules(
        db.session, variant_dict["variant_id"],
        variant_dict['variant_version'])
    if local_modules:
        local_module = local_modules[0]
        log.info("Using local module %r as a dependency.",
                 local_module)
        mmd = local_module.mmd()
        module_info = {}
        module_info["modulemd"] = local_module.modulemd
        module_info["koji_tag"] = local_module.koji_tag
    else:
        module_info = get_module(session, variant_dict, strict)
        module_info = {k: v for k, v in module_info.items()
                       if k in ["modulemd", "koji_tag"]}
        module_info = {
            'modulemd': module_info['modulemd'],
            'koji_tag': module_info['koji_tag']
        }

        yaml = module_info['modulemd']
        mmd = _extract_modulemd(yaml)

    # Check if we have examined this koji_tag already - no need to do
    # it again...
    if module_info in modules:
        return modules

    modules.append(module_info)

    # We want to use the same stream as the one used in the time this
    # module was built. But we still should fallback to plain mmd.requires
    # in case this module depends on some older module for which we did
    # not populate mmd.xmd['mbs']['requires'].
    if mmd.xmd.get('mbs') and mmd.xmd['mbs'].get('requires'):
        requires = mmd.xmd['mbs']['requires']
        requires = {name: data['stream'] for name, data in requires.items()}
    else:
        requires = mmd.requires

    for name, stream in requires.items():
        modified_dep = {
            'name': name,
            'version': stream,
            # Only return details about module builds that finished
            'active': True,
        }
        modules = _get_recursively_required_modules(
            session, modified_dep, modules, strict)

    return modules


def resolve_profiles(session, mmd, keys):
    """
    :param session : PDCClient instance
    :param mmd: ModuleMetadata instance of module
    :param keys: list of modulemd installation profiles to include in
                 the result.
    :return: Dictionary with keys set according to `keys` param and values
             set to union of all components defined in all installation
             profiles matching the key using the buildrequires.

    If there are some modules loaded by utils.load_local_builds(...), these
    local modules will be considered when returning the profiles.

    https://pagure.io/fm-orchestrator/issue/181
    """

    results = {}
    for key in keys:
        results[key] = set()
    for module_name, module_info in mmd.xmd['mbs']['buildrequires'].items():
        local_modules = models.ModuleBuild.local_modules(
            db.session, module_name, module_info['stream'])
        if local_modules:
            local_module = local_modules[0]
            log.info("Using local module %r to resolve profiles.",
                     local_module)
            dep_mmd = local_module.mmd()
            for key in keys:
                if key in dep_mmd.profiles:
                    results[key] |= dep_mmd.profiles[key].rpms
            continue

        # Find the dep in the built modules in PDC
        module_info = {
            'variant_id': module_name,
            'variant_stream': module_info['stream'],
            'variant_release': module_info['version']}
        modules = _get_recursively_required_modules(
            session, module_info, strict=True)

        for module in modules:
            yaml = module['modulemd']
            dep_mmd = _extract_modulemd(yaml)

            # Take note of what rpms are in this dep's profile.
            for key in keys:
                if key in dep_mmd.profiles:
                    results[key] |= dep_mmd.profiles[key].rpms

    # Return the union of all rpms in all profiles of the given keys.
    return results


def get_module_build_dependencies(session, module_info, strict=False):
    """
    :param session : PDCClient instance
    :param module_info : a dict containing filters for pdc or ModuleMetadata
    instance.
    :param strict: Normally this function returns None if no module can be
           found.  If strict=True, then an UnprocessableEntity is raised.
    :return dict with koji_tag as a key and ModuleMetadata object as value.

    Example minimal module_info:
        {
            'variant_id': module_name,
            'variant_version': module_version,
            'variant_type': 'module'
        }
    """
    log.debug("get_module_build_dependencies(%r, strict=%r)" % (module_info, strict))
    # XXX get definitive list of modules

    # This is the set we're going to build up and return.
    module_tags = {}

    if not isinstance(module_info, modulemd.ModuleMetadata):
        queried_module = get_module(session, module_info, strict=strict)
        yaml = queried_module['modulemd']
        queried_mmd = _extract_modulemd(yaml, strict=strict)
    else:
        queried_mmd = module_info

    if (not queried_mmd or not queried_mmd.xmd.get('mbs') or
            not queried_mmd.xmd['mbs'].get('buildrequires')):
        raise RuntimeError(
            'The module "{0!r}" did not contain its modulemd or did not have '
            'its xmd attribute filled out in PDC'.format(module_info))

    buildrequires = queried_mmd.xmd['mbs']['buildrequires']
    # Queue up the next tier of deps that we should look at..
    for name, details in buildrequires.items():
        modified_dep = {
            'name': name,
            'version': details['stream'],
            'release': details['version'],
            # Only return details about module builds that finished
            'active': True,
        }
        modules = _get_recursively_required_modules(
            session, modified_dep, strict=strict)
        for m in modules:
            if m["koji_tag"] in module_tags:
                continue
            module_tags[m["koji_tag"]] = _extract_modulemd(m["modulemd"])

    return module_tags


def resolve_requires(session, requires):
    """
    Takes `requires` dict with module_name as key and module_stream as value.
    Resolves the stream to particular latest version of a module and returns
    new dict in following format:

    {
        "module_name": {
            "ref": module_commit_hash,
            "stream": original_module_stream,
            "version": module_version,
            "filtered_rpms": ["nvr", ...]
        },
        ...
    }

    If there are some modules loaded by utils.load_local_builds(...), these
    local modules will be considered when resolving the requires.

    Raises RuntimeError on PDC lookup error.
    """
    new_requires = copy.deepcopy(requires)
    for module_name, module_stream in requires.items():
        # Try to find out module dependency in the local module builds
        # added by utils.load_local_builds(...).
        local_modules = models.ModuleBuild.local_modules(
            db.session, module_name, module_stream)
        if local_modules:
            local_build = local_modules[0]
            new_requires[module_name] = {
                # The commit ID isn't currently saved in modules.yaml
                'ref': None,
                'stream': local_build.stream,
                'version': local_build.version,
                # No need to set filtered_rpms for local builds, because MBS
                # filters the RPMs automatically when the module build is
                # done.
                'filtered_rpms': []
            }
            continue

        # Assumes that module_stream is the stream and not the commit hash
        module_info = {
            'name': module_name,
            'version': module_stream,
            'active': True}
        module = get_module(session, module_info)

        commit_hash = None
        version = None
        filtered_rpms = []
        module = get_module(session, module_info, strict=True)
        if module.get('modulemd'):
            mmd = modulemd.ModuleMetadata()
            mmd.loads(module['modulemd'])
            if mmd.xmd.get('mbs') and mmd.xmd['mbs'].get('commit'):
                commit_hash = mmd.xmd['mbs']['commit']

            # Find out the particular NVR of filtered packages
            if "rpms" in module and mmd.filter and mmd.filter.rpms:
                for rpm in module["rpms"]:
                    nvr = kobo.rpmlib.parse_nvra(rpm)
                    # If the package is not filtered, continue
                    if not nvr["name"] in mmd.filter.rpms:
                        continue

                    # If the nvr is already in filtered_rpms, continue
                    nvr = kobo.rpmlib.make_nvr(nvr, force_epoch=True)
                    if nvr in filtered_rpms:
                        continue
                    filtered_rpms.append(nvr)

        if module.get('variant_release'):
            version = module['variant_release']

        if version and commit_hash:
            new_requires[module_name] = {
                'ref': commit_hash,
                'stream': module_stream,
                'version': str(version),
                'filtered_rpms': filtered_rpms,
            }
        else:
            raise RuntimeError(
                'The module "{0}" didn\'t contain either a commit hash or a'
                ' version in PDC'.format(module_name))

    return new_requires
