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
# Written by Petr Šabata <contyk@redhat.com>

"""Configuration handler functions."""

import os.path
import configparser
import json

def from_file(filename=None):
    """Create the configuration instance from a file.

    The file name is optional and defaults to /etc/rida/rida.conf.

    :param str filename: The configuration file to load, optional.
    """
    if filename is None:
        filename = "/etc/rida/rida.conf"
    if not isinstance(filename, str):
        raise TypeError("The configuration filename must be a string.")
    if not os.path.isfile(filename):
        raise IOError("The configuration file doesn't exist.")
    cp = configparser.ConfigParser(allow_no_value=True)
    cp.read(filename)
    default = cp["DEFAULT"]
    conf = Config()
    conf.db = default.get("db")
    conf.system = default.get("system")
    conf.pdc = default.get("pdc")
    conf.koji = default.get("koji")
    conf.scmurls = json.loads(default.get("scmurls"))
    return conf

class Config(object):
    """Class representing the orchestrator configuration."""

    def __init__(self):
        """Initialize the Config object."""
        self._system = ""
        self._db = ""
        self._pdc = ""
        self._koji = ""

    @property
    def system(self):
        """The buildsystem to use."""
        return self._system

    @system.setter
    def system(self, s):
        s = str(s)
        if s not in ("koji"):
            raise ValueError("Unsupported buildsystem.")
        self._system = s

    @property
    def db(self):
        """RDB URL."""
        return self._db

    @db.setter
    def db(self, s):
        self._db = str(s)

    @property
    def pdc(self):
        """PDC URL."""
        return self._pdc

    @pdc.setter
    def pdc(self, s):
        self._pdc = str(s)

    @property
    def koji(self):
        """Koji URL."""
        return self._koji

    @koji.setter
    def koji(self, s):
        self._koji = str(s)

    @property
    def scmurls(self):
        """Allowed SCM URLs."""
        return self._scmurls

    @scmurls.setter
    def scmurls(self, l):
        if not isinstance(l, list):
            raise TypeError("scmurls needs to be a list.")
        self._scmurls = [str(x) for x in l]
