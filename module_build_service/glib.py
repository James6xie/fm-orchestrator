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
"""
GLib Related helper functions
Originally written by Nils Philippsen in https://pagure.io/modulemd/pull-request/63
"""
from six import text_type
from gi.repository import GLib


def from_variant_dict(d):
    """ Converts a variant dictionary to a Python dictionary
    """
    rv = {}
    for key, value in d.items():
        rv[key] = value.unpack()
    return rv


def variant_str(s):
    """ Converts a string to a GLib.Variant
    """
    if not isinstance(s, str):
        raise TypeError('Only strings are supported for scalars')

    return GLib.Variant('s', s)


def variant_list(l):
    """ Converts a list to a GLib.Variant
    """
    l_variant = list()
    for item in l:
        if item is None:
            item = ''
        if type(item) == str:
            l_variant.append(variant_str(item))
        elif type(item) == text_type:
            l_variant.append(variant_str(item.encode('utf-8')))
        elif type(item) == list:
            l_variant.append(variant_list(item))
        elif type(item) == dict:
            l_variant.append(variant_dict(item))
        elif type(item) == bool:
            l_variant.append(variant_bool(item))
        else:
            raise TypeError('Cannot convert unknown type')
    return GLib.Variant('av', l_variant)


def variant_bool(b):
    """ Converts a boolean to a GLib.Varant
    """
    if not isinstance(b, bool):
        raise TypeError('Only booleans are supported')

    return GLib.Variant('b', b)


def dict_values(d):
    """ Converts each dictionary value to a GLib.Variant
    """
    if not isinstance(d, dict):
        raise TypeError('Only dictionaries are supported for mappings')

    d_variant = dict()
    for k, v in d.items():
        if v is None:
            v = ''
        if type(v) == str:
            d_variant[k] = variant_str(v)
        elif type(v) == text_type:
            d_variant[k] = variant_str(v.encode('utf-8'))
        elif type(v) == list:
            d_variant[k] = variant_list(v)
        elif type(v) == dict:
            d_variant[k] = variant_dict(v)
        elif type(v) == bool:
            d_variant[k] = variant_bool(v)
        else:
            raise TypeError('Cannot convert unknown type')
    return d_variant


def variant_dict(d):
    """ Converts a dictionary to a dictionary of GLib.Variant
    """
    if not isinstance(d, dict):
        raise TypeError('Only dictionaries are supported for mappings')

    d_variant = dict_values(d)
    return GLib.Variant('a{sv}', d_variant)
