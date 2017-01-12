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

import pprint
import logging
log = logging.getLogger()

import six
import module_build_service


def get_pdc_client_session(config):
    """
    :param config: instance of module_build_service.config.Config
    :return pdc_client.PDCClient instance
    """
    return PDCClient(config.pdc_url, config.pdc_develop, config.pdc_insecure) # hardcoded devel env

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

        for attr in ('variant_id', 'variant_stream'):
            if attr not in data.keys():
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
        result = {'variant_id': data.name, 'variant_version': data.version, 'variant_release': data.release }

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

    if not result:
        raise ValueError("Couldn't get variant_dict from %s" % data)

    return result


def variant_dict_from_str(module_str):
    """
    :param module_str: a string to match in PDC
    :return module_info dict

    Example minimal module_info {'variant_id': module_name, 'variant_version': module_version, 'variant_type': 'module'}
    """
    log.debug("variant_dict_from_str(%r)" % module_str)
    # best match due several filters not being provided such as variant type ...

    module_info = {}

    release_start = module_str.rfind('-')
    version_start = module_str.rfind('-', 0, release_start)
    module_info['variant_release'] = module_str[release_start+1:]
    module_info['variant_version'] = module_str[version_start+1:release_start]
    module_info['variant_id'] = module_str[:version_start]
    module_info['variant_type'] = 'module'

    return module_info

def get_module(session, module_info, strict=False):
    """
    :param session : PDCClient instance
    :param module_info: pdc variant_dict, str, mmd or module dict
    :param strict: Normally this function returns None if no module can be
           found.  If strict=True, then a ValueError is raised.

    :return final list of module_info which pass repoclosure
    """

    module_info = get_variant_dict(module_info)

    query = dict(
        variant_id=module_info['variant_id'],
        variant_version=module_info['variant_version'],
    )
    if module_info.get('variant_release'):
        query['variant_release'] = module_info['variant_release']

    retval = session['unreleasedvariants'](page_size=-1, **query) # ordering=variant_release...

    # Error handling
    if not retval:
        if strict:
            raise ValueError("Failed to find module in PDC %r" % query)
        else:
            return None

    module = None
    # If we specify 'variant_release', we expect only single module to be
    # returned, but otherwise we have to pick the one with the highest
    # release ourselves.
    if 'variant_release' in query:
        assert len(retval) <= 1, pprint.pformat(retval)
        module = retval[0]
    else:
        module = retval[0]
        for m in retval:
            if int(m['variant_release']) > int(module['variant_release']):
                module = m

    return module

def get_module_tag(session, module_info, strict=False):
    """
    :param session : PDCClient instance
    :param module_info: list of module_info dicts
    :param strict: Normally this function returns None if no module can be
           found.  If strict=True, then a ValueError is raised.
    :return: koji tag string
    """
    return get_module(session, module_info, strict=strict)['koji_tag']

def get_module_modulemd(session, module_info, strict=False):
    """
    :param session : PDCClient instance
    :param module_info: list of module_info dicts
    :param strict: Normally this function returns None if no module can be
           found.  If strict=True, then a ValueError is raised.
    :return: ModuleMetadata instance
    """
    yaml = get_module(session, module_info, strict=strict)['modulemd']
    if not yaml:
        if strict:
            raise ValueError("Failed to find modulemd entry in PDC for "
                "%r" % module_info)
        else:
            return None

    mmd = modulemd.ModuleMetadata()
    mmd.loads(yaml)
    return mmd

def resolve_profiles(session, mmd, keys, seen=None):
    """
    :param session : PDCClient instance
    :param mmd: ModuleMetadata instance of module
    :param keys: list of modulemd installation profiles to include in
                 the result.
    :return: Dictionary with keys set according to `keys` param and values
             set to union of all components defined in all installation
             profiles matching the key recursively using the buildrequires.

    https://pagure.io/fm-orchestrator/issue/181
    """

    seen = seen or []  # Initialize to an empty list.
    results = {}
    for key in keys:
        results[key] = set()
    for name, stream in mmd.buildrequires.items():
        # First, guard against infinite recursion
        if name in seen:
            continue

        # Find the latest of the dep in our db of built modules.
        module_info = {'variant_id': name, 'variant_stream': stream}
        dep_mmd = get_module_modulemd(session, module_info, True)

        # Take note of what rpms are in this dep's profile.
        for key in keys:
            if key in dep_mmd.profiles:
                results[key] |= dep_mmd.profiles[key].rpms

        # And recurse to all modules that are deps of our dep.
        rec_results = resolve_profiles(session, dep_mmd, keys, seen + [name])
        for rec_key, rec_result in rec_results.items():
            results[rec_key] |= rec_result

    # Return the union of all rpms in all profiles of the given keys.
    return results

def module_depsolving_wrapper(session, module_list, strict=True):
    """
    :param session : PDCClient instance
    :param module_list: list of module_info dicts
    :return final list of module_info which pass repoclosure
    """
    log.debug("module_depsolving_wrapper(%r, strict=%r)" % (module_list, strict))
    # TODO: implement this

    # Make sure that these are dicts from PDC ... ensures all values
    module_list = set([get_module_tag(session, x, strict) for x in module_list])
    # pdc-updater adds "module-" prefix to koji_tag, but here we expect koji_tag
    # is just NVR of a module, so remove the "module-" prefix.
    module_list = set([x[len("module-"):] if x.startswith("module-") else x
                       for x in module_list])
    seen = set() # don't query pdc for the same items all over again

    while True:
        if seen == module_list:
                break

        for module in module_list:
            if module in seen:
                continue
            info = get_module(session, module, strict)
            assert info, "Module '%s' not found in PDC" % module
            module_list.update([x['dependency'] for x in info['build_deps']])
            seen.add(module)
            module_list.update(info['build_deps'])

    return list(module_list)

def get_module_runtime_dependencies(session, module_info, strict=False):
    """
    :param session : PDCClient instance
    :param module_infos : a dict containing filters for pdc
    :param strict: Normally this function returns None if no module can be
           found.  If strict=True, then a ValueError is raised.

    Example minimal module_info {'variant_id': module_name, 'variant_version': module_version, 'variant_type': 'module'}
    """
    log.debug("get_module_runtime_dependencies(%r, strict=%r)" % (module_info, strict))
    # XXX get definitive list of modules

    deps = []
    module_info = get_module(session, module_info, strict=strict)
    if module_info and module_info.get('runtime_deps', None):
        deps = [dict(variant_id=x['dependency'], variant_stream=x['stream'])
                for x in module_info['runtime_deps']]
        deps = module_depsolving_wrapper(session, deps, strict=strict)

    return deps

def get_module_build_dependencies(session, module_info, strict=False):
    """
    :param session : PDCClient instance
    :param module_info : a dict containing filters for pdc
    :param strict: Normally this function returns None if no module can be
           found.  If strict=True, then a ValueError is raised.
    :return final list of module_infos which pass repoclosure

    Example minimal module_info {'variant_id': module_name, 'variant_version': module_version, 'variant_type': 'module'}
    """
    log.debug("get_module_build_dependencies(%r, strict=%r)" % (module_info, strict))
    # XXX get definitive list of modules

    deps = []
    module_info = get_module(session, module_info, strict=strict)
    if module_info and module_info.get('build_deps', None):
        deps = [dict(variant_id=x['dependency'], variant_stream=x['stream'])
                for x in module_info['build_deps']]
        deps = module_depsolving_wrapper(session, deps, strict=strict)

    return deps
