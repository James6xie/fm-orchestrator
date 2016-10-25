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

import logging
log = logging.getLogger()

try:
    from copr.client import CoprClient
except ImportError:
    log.exception("Failed to import CoprClient.")

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

        for attr in ('name', 'version', 'release'):
            if attr not in data.keys():
                return False
        return True

    def is_variant_dict(data):
        if not isinstance(data, dict):
            return False

        for attr in ('variant_id', 'variant_version', 'variant_release'):
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
        result = data
        # ensure that variant_type is in result
        if 'variant_type' not in result.keys():
            result['variant_type'] = 'module'

        if 'variant_release' not in result.keys():
            result['variant_release'] = '0'

    elif is_module_dict(data):
        result = {'variant_id': data['name'], 'variant_version': data['version'], 'variant_release': data['release']}

    if not result:
        raise ValueError("Couldn't get variant_dict from %s" % data)

    return result


def variant_dict_from_str(module_str):
    """
    :param module_str: a string to match in PDC
    :return module_info dict

    Example minimal module_info {'variant_id': module_name, 'variant_version': module_version, 'variant_type': 'module'}
    """
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
    retval = session['unreleasedvariants'](page_size=-1,
                variant_id=module_info['variant_id'],
                variant_version=module_info['variant_version'],
                variant_release=module_info['variant_release'])
    assert len(retval) <= 1

    # Error handling
    if not retval:
        if strict:
            raise ValueError("Failed to find module in PDC %r" % module_info)
        else:
            return None

    return retval[0]

def get_module_tag(session, module_info, strict=False):
    """
    :param session : PDCClient instance
    :param module_info: list of module_info dicts
    :param strict: Normally this function returns None if no module can be
           found.  If strict=True, then a ValueError is raised.
    :return: koji tag string
    """
    return get_module(session, module_info, strict=strict)['koji_tag']

def get_module_repo(session, module_info, strict=False, config=module_build_service.conf):
    """
    :param session : PDCClient instance
    :param module_info: list of module_info dicts
    :param strict: Normally this function returns None if no module can be
           found.  If strict=True, then a ValueError is raised.
    :param config: instance of module_build_service.config.Config
    :return: URL to a DNF repository for the module
    """
    module = get_module(session, module_info, strict=strict)
    if not module:
        return None

    # Module was built in Koji
    # @TODO There should be implemented retrieveing URL to a module repofile in koji
    if module["koji_tag"] != "-":
        raise NotImplementedError

    # Module was built in Copr
    # @TODO get the correct user
    owner, nvr = "@copr", module["variant_id"]
    cl = CoprClient.create_from_file_config(config.copr_config)
    response = cl.get_module_repo(owner, nvr).data

    if response["output"] == "notok":
        raise ValueError(response["error"])
    return response["repo"]

def module_depsolving_wrapper(session, module_list, strict=True):
    """
    :param session : PDCClient instance
    :param module_list: list of module_info dicts
    :return final list of module_info which pass repoclosure
    """
    # TODO: implement this

    # Make sure that these are dicts from PDC ... ensures all values
    module_list = set([get_module_tag(session, x, strict) for x in module_list])
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
    # XXX get definitive list of modules

    deps = []
    module_info = get_module(session, module_info, strict=strict)
    if module_info and module_info.get('runtime_deps', None):
        deps = [x['dependency'] for x in module_info['runtime_deps']]
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
    # XXX get definitive list of modules

    deps = []
    module_info = get_module(session, module_info, strict=strict)
    if module_info and module_info.get('build_deps', None):
        deps = [x['dependency'] for x in module_info['build_deps']]
        deps = module_depsolving_wrapper(session, deps, strict=strict)

    return deps
