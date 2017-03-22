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

import copy
import inspect
import pprint
import logging
log = logging.getLogger()

import six


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

    log.debug("get_module(%r, strict=%r)" % (module_info, strict))
    module_info = get_variant_dict(module_info)

    query = dict(
        variant_id=module_info['variant_id'],
        variant_version=module_info['variant_version'],
    )
    if module_info.get('variant_release'):
        query['variant_release'] = module_info['variant_release']
    if module_info.get('active'):
        query['active'] = module_info['active']

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
    yaml = None
    module = get_module(session, module_info, strict=strict)
    if module:
        yaml = module['modulemd']

    if not yaml:
        if strict:
            raise ValueError("Failed to find modulemd entry in PDC for "
                "%r" % module_info)
        else:
            return None

    return _extract_modulemd(yaml, strict=strict)

def _extract_modulemd(yaml, strict=False):
    mmd = modulemd.ModuleMetadata()
    mmd.loads(yaml)
    return mmd

def resolve_profiles(session, mmd, keys):
    """
    :param session : PDCClient instance
    :param mmd: ModuleMetadata instance of module
    :param keys: list of modulemd installation profiles to include in
                 the result.
    :return: Dictionary with keys set according to `keys` param and values
             set to union of all components defined in all installation
             profiles matching the key using the buildrequires.

    https://pagure.io/fm-orchestrator/issue/181
    """

    results = {}
    for key in keys:
        results[key] = set()
    for module_name, module_info in mmd.xmd['mbs']['buildrequires'].items():
        # Find the dep in the built modules in PDC
        module_info = {
            'variant_id': module_name,
            'variant_stream': module_info['stream'],
            'variant_release': module_info['version']}
        dep_mmd = get_module_modulemd(session, module_info, True)

        # Take note of what rpms are in this dep's profile.
        for key in keys:
            if key in dep_mmd.profiles:
                results[key] |= dep_mmd.profiles[key].rpms

    # Return the union of all rpms in all profiles of the given keys.
    return results

def module_depsolving_wrapper(session, modules, strict=True):
    """
    :param session : PDCClient instance
    :param modules: list of module_info dicts
    :return final list of the names of tags.
    """
    log.debug("module_depsolving_wrapper(%r, strict=%r)" % (modules, strict))

    # This is the set we're going to build up and return.
    module_tags = set()

    # We want to take only single 
    for module_dict in modules:
        # Get enhanced info on this module from pdc.
        info = get_module(session, module_dict, strict)

        # Take note of the tag of this module, but only if it is a dep and
        # not in the original list.
         # XXX - But, for now go ahead and include it because that's how this
        # code used to work.
        module_tags.add(info['koji_tag'])

        # Now, when we look for the deps of this module, use the mmd.xmd
        # attributes because they contain the promise of *exactly* which
        # versions of which deps we say we're going to build *this* module
        # against.
        if not info['modulemd']:
            raise ValueError("No PDC modulemd found for %r" % info)
        mmd = _extract_modulemd(info['modulemd'])

        # Queue up the next tier of deps that we should look at..
        for name, details in mmd.xmd['mbs']['buildrequires'].items():
            modified_dep = {
                'name': name,
                'version': details['stream'],
                'release': details['version'],
                # Only return details about module builds that finished
                'active': True,
            }
            info = get_module(session, modified_dep, strict)
            module_tags.add(info['koji_tag'])

    return list(module_tags)


def get_module_build_dependencies(session, module_info, strict=False):
    """
    :param session : PDCClient instance
    :param module_info : a dict containing filters for pdc
    :param strict: Normally this function returns None if no module can be
           found.  If strict=True, then a ValueError is raised.
    :return final list of koji tags

    Example minimal module_info {'variant_id': module_name, 'variant_version': module_version, 'variant_type': 'module'}
    """
    log.debug("get_module_build_dependencies(%r, strict=%r)" % (module_info, strict))
    # XXX get definitive list of modules

    deps = []
    queried_mmd = get_module_modulemd(session, module_info, strict=strict)
    if not queried_mmd or not queried_mmd.xmd.get('mbs') or not \
            queried_mmd.xmd['mbs'].get('buildrequires'):
        raise RuntimeError(
            'The module "{0!r}" did not contain its modulemd or did not have '
            'its xmd attribute filled out in PDC'.format(module_info))

    buildrequires = queried_mmd.xmd['mbs']['buildrequires']
    deps = [dict(
        name=dep_name,
        version=dep_info['stream'],
        release=dep_info['version'],
    ) for dep_name, dep_info in buildrequires.items()]

    deps = module_depsolving_wrapper(session, deps, strict=strict)

    return deps

def get_module_commit_hash_and_version(session, module_info):
    """
    Gets the commit hash and version of a module stored in PDC
    :param module_info: a dict containing filters for PDC
    :param session: a PDC session instance
    :return: a tuple containing the string of the commit hash and the version
    of the module stored in PDC. If a value is not found, None is
    returned for the values that aren't found.
    """
    commit_hash = None
    version = None
    module = get_module(session, module_info)
    if module:
        if module.get('modulemd'):
            mmd = modulemd.ModuleMetadata()
            mmd.loads(module['modulemd'])
            if mmd.xmd.get('mbs') and mmd.xmd['mbs'].get('commit'):
                commit_hash = mmd.xmd['mbs']['commit']
        if module.get('variant_release'):
            version = module['variant_release']
    if not commit_hash:
        # TODO: Should this eventually be an exception?
        log.warn(
            'The commit hash for {0!r} was not part of the modulemd in PDC'
            .format(module_info))
    if not version:
        # TODO: Should this eventually be an exception?
        log.warn(
            'The version for {0!r} was not in PDC'.format(module_info))
    return commit_hash, version
