# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT


def deps_to_dict(deps, deps_type):
    """
    Helper method to convert a Modulemd.Dependencies object to a dictionary.

    :param Modulemd.Dependencies deps: the Modulemd.Dependencies object to convert
    :param str deps_type: the type of dependency (buildtime or runtime)
    :return: a dictionary with the keys as module names and values as a list of strings
    :rtype dict
    """
    names_func = getattr(deps, 'get_{}_modules'.format(deps_type))
    streams_func = getattr(deps, 'get_{}_streams'.format(deps_type))
    return {
        module: streams_func(module)
        for module in names_func()
    }
