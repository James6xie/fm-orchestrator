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

from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class Database(object):
    """Class for handling database connections."""

    def __init__(self, rdburl=None, debug=False):
        """Initialize the database object."""
        if not isinstance(rdburl, str):
            rdburl = "sqlite:///rida.db"
        engine = create_engine(rdburl, echo=debug)
        Session = sessionmaker(bind=engine)
        self._session = Session()

    @property
    def session(self):
        """Database session object."""
        return self._session

    @classmethod
    def create_tables(cls, db_url, debug=False):
        """ Creates our tables in the database.

        :arg db_url, URL used to connect to the database. The URL contains
        information with regards to the database engine, the host to connect
        to, the user and password and the database name.
        ie: <engine>://<user>:<password>@<host>/<dbname>
        :kwarg debug, a boolean specifying wether we should have the verbose
        output of sqlalchemy or not.
        :return a Database connection that can be used to query to db.
        """
        engine = create_engine(db_url, echo=debug)
        Base.metadata.create_all(engine)
        return cls(db_url, debug=debug)


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
