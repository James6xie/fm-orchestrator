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



def get_pdc_client_session(config):
    """
    :param config: instance of rida.config.Config
    :return pdc_client.PDCClient instance
    """
    return PDCClient(config.pdc_url, config.pdc_develop, config.pdc_insecure) # hardcoded devel env

def get_variant_dict(data):
    """
    :param data: one of following
                    pdc variant_dict {'variant_name': value, 'variant_version': value, }
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

        for attr in ('variant_name', 'variant_version', 'variant_release'):
            if attr not in data.keys():
                return False
        return True

    def is_modulemd(data):
        return isinstance(data, modulemd.ModuleMetadata)

    def is_module_str(data):
        return isinstance(data, str)

    result = None

    if is_module_str(data):
        result = variant_dict_from_str(data)

    elif is_modulemd(data):
        result = {'variant_name': data.name, 'variant_version': data.version, 'variant_release': data.release }

    elif is_variant_dict(data):
        result = data
        # ensure that variant_type is in result
        if 'variant_type' not in result.keys():
            result['variant_type'] = 'module'

        if 'variant_release' not in result.keys():
            result['variant_release'] = '0'

    elif is_module_dict(data):
        result = {'variant_name': data['name'], 'variant_version': data['version']}

    if not result:
        raise ValueError("Couldn't get variant_dict from %s" % data)

    return result


def variant_dict_from_str(module_str):
    """
    :param module_str: a string to match in PDC
    :return module_info dict

    Example minimal module_info {'variant_name': module_name, 'variant_version': module_version, 'variant_type': 'module'}
    """
    # best match due several filters not being provided such as variant type ...

    module_info = {}

    module_info['variant_name'] = module_str[:module_str.find('-')]
    module_info['variant_version'] = module_str[module_str.find('-')+1:]
    module_info['variant_type'] = 'module'

    return module_info

def get_module(session, module_info, strict=False):
    """
    :param session : PDCClient instance
    :param module_info: pdc variant_dict, str, mmd or module dict
    :return final list of module_info which pass repoclosure
    """

    module_info = get_variant_dict(module_info)

    retval = session['unreleasedvariants'](page_size=-1, **module_info)
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
    :return: koji tag string
    """
    # TODO -- get this from PDC some day... for now, we're just going to
    # construct the module tag name from the module attrs we already know
    # about.
    #return get_module(session, module_info, strict=strict)['koji_tag']
    return "{name}-{version}-{release}".format(**module_info)

def module_depsolving_wrapper(session, module_list, strict=False):
    """
    :param session : PDCClient instance
    :param module_list: list of module_info dicts
    :return final list of module_info which pass repoclosure
    """
    # TODO: implement this

    # Make sure that these are dicts from PDC ... ensures all values
    module_infos = [get_module(session, module, strict=strict) for module in module_list]

    return module_infos

def get_module_dependencies(session, module_info, strict=False):
    """
    :param session : PDCClient instance
    :param module_infos : a dict containing filters for pdc

    Example minimal module_info {'variant_name': module_name, 'variant_version': module_version, 'variant_type': 'module'}
    """
    # XXX get definitive list of modules

    deps = []
    module_info = get_module(session, module_info, strict=strict)
    if module_info and module_info.get('runtime_deps'):
        deps = [x['dependency'] for x in module_info['runtime_deps']]
        deps = module_depsolving_wrapper(session, deps, strict=strict)

    return deps

def get_module_build_dependencies(session, module_info, strict=False):
    """
    :param session : PDCClient instance
    :param module_info : a dict containing filters for pdc
    :return final list of module_infos which pass repoclosure

    Example minimal module_info {'variant_name': module_name, 'variant_version': module_version, 'variant_type': 'module'}
    """
    # XXX get definitive list of modules

    deps = []
    module_info = get_module(session, module_info, strict=strict)
    if module_info and module_info.get('build_deps'):
        deps = [x['dependency'] for x in module_info['build_deps']]
        deps = module_depsolving_wrapper(session, deps, strict=strict)

    return deps
