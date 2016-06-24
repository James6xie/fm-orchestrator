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

# TODO: Pick the configuration format
# TODO: Add properties for all the required options.

def from_file(filename=None):
    """Create the configuration instance from a file.

    The file name is optional and defaults to /etc/rida/rida.conf.

    :param str filename: The configuration file to load, optional.
    """
    if filename is None:
        filename = "/etc/rida/rida.conf"
    if not isinstance(filename, str):
        raise TypeError("The configuration filename must be a string.")
    conf = Config()
    # TODO: Parse the file and set the properties
    return conf

class Config(object):
    """Class representing the orchestrator configuration."""

    def __init__(self):
        """Initialize the Config object."""
        # Buildsystem to use; koji, copr, mock
        self._system = ""
        # SQLAlchemy RDB URL
        self._db = ""
        # PDC URL
        self._pdc = ""
        # Koji URL
        self._koji = ""

    @property
    def system():
        """Buildsystem to use by the orchestrator."""
        return self._system

    @system.setter
    def system(s):
        # XXX: Check if it's one of the supported values
        self._system = str(s)

    @property
    def db():
        """RDB URL for the orchestrator."""
        return self._db

    @db.setter
    def db(s):
        self._db = str(s)

    @property
    def pdc():
        """PDC URL for the orchestrator."""
        return self._pdc

    @pdc.setter
    def pdc(s):
        self._pdc = str(s)

    @property
    def koji():
        """Koji URL for the orchestrator."""
        return self._koji

    @koji.setter
    def koji(s):
        self._koji = str(s)
