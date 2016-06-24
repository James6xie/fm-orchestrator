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

"""Database handler functions."""

from sqlalchemy import Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class Database(object):
    """Class for handling database connections."""

    def __init__(self, conf):
        """..."""
        if not isinstance(conf, rida.config.Config):
            raise TypeError("Database requires a configuration object.")
        self._conf = conf

    def connect_db():
        # TODO: implement this

    def disconnect_db():
        # TODO: implement this

    def get_db():
        # TODO: Implement this

    @property
    def conf():
        """Database configuration."""
        return self._conf

    @conf.setter
    def conf(o):
        if not isinstance(conf, rida.config.Config):
            raise TypeError("Invalid data passed for conf")
        self._conf = o

class Module(Base):
    __tablename__ = "modules"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    version = Column(String)
    release = Column(String)
    # XXX: Consider making this a proper ENUM
    state = Column(String)
    modulemd = Column(String)

class Build(Base):
    __tablename__ = "builds"
    id = Column(Integer, primary_key=True)
    # XXX: Consider making this a proper foreign key
    module_id = Column(Integer)
    package = Column(String)
    # XXX: Consider making this a proper ENUM
    format = Column(String)
    task = Column(Integer)
    # XXX: Consider making this a proper ENUM
    state = Column(String)
