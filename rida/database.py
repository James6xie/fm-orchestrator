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
#            Ralph Bean <rbean@redhat.com>

"""Database handler functions."""

from sqlalchemy import (
    Column,
    Integer,
    String,
    ForeignKey,
    create_engine,
)
from sqlalchemy.orm import (
    sessionmaker,
    relationship,
    validates,
)
from sqlalchemy.ext.declarative import declarative_base

import modulemd as _modulemd

import rida.messaging

import logging
log = logging.getLogger(__name__)


# Just like koji.BUILD_STATES, except our own codes for modules.
BUILD_STATES = {
    # When you parse the modulemd file and know the nvr and you create a
    # record in the db, and that's it.
    # publish the message
    # validate that components are available
    #   and that you can fetch them.
    # if all is good, go to wait: telling ridad to take over.
    # if something is bad, go straight to failed.
    "init": 0,
    # Here, the scheduler picks up tasks in wait.
    # switch to build immediately.
    # throttling logic (when we write it) goes here.
    "wait": 1,
    # Actively working on it.
    "build": 2,
    # All is good
    "done": 3,
    # Something failed
    "failed": 4,
    # This is a state to be set when a module is ready to be part of a
    # larger compose.  perhaps it is set by an external service that knows
    # about the Grand Plan.
    "ready": 5,
}

INVERSE_BUILD_STATES = {v: k for k, v in BUILD_STATES.items()}


class RidaBase(object):
    # TODO -- we can implement functionality here common to all our model
    # classes.
    pass


Base = declarative_base(cls=RidaBase)


class Database(object):
    """Class for handling database connections."""

    def __init__(self, config, debug=False):
        """Initialize the database object."""
        self.engine = create_engine(config.db, echo=debug)
        self._session = None  # Lazilly created..

    def __enter__(self):
        return self.session

    def __exit__(self, *args, **kwargs):
        self._session.close()
        self._session = None

    @property
    def session(self):
        """Database session object."""
        if not self._session:
            Session = sessionmaker(bind=self.engine)
            self._session = Session()
        return self._session

    @classmethod
    def create_tables(cls, config, debug=False):
        """ Creates our tables in the database.

        :arg config, config object with a 'db' URL attached to it.
        ie: <engine>://<user>:<password>@<host>/<dbname>
        :kwarg debug, a boolean specifying wether we should have the verbose
        output of sqlalchemy or not.
        :return a Database connection that can be used to query to db.
        """
        engine = create_engine(config.db, echo=debug)
        Base.metadata.create_all(engine)
        return cls(config, debug=debug)


class Module(Base):
    __tablename__ = "modules"
    name = Column(String, primary_key=True)


class ModuleBuild(Base):
    __tablename__ = "module_builds"
    id = Column(Integer, primary_key=True)
    name = Column(String, ForeignKey('modules.name'), nullable=False)
    version = Column(String, nullable=False)
    release = Column(String, nullable=False)
    state = Column(Integer, nullable=False)
    modulemd = Column(String, nullable=False)
    koji_tag = Column(String)  # This gets set after 'wait'
    scmurl = Column(String)

    # A monotonically increasing integer that represents which batch or
    # iteration this module is currently on for successive rebuilds of its
    # components.  Think like 'mockchain --recurse'
    batch = Column(Integer, default=0)

    module = relationship('Module', backref='module_builds', lazy=False)

    def current_batch(self):
        """ Returns all components of this module in the current batch. """

        if not self.batch:
            raise ValueError("No batch is in progress: %r" % self.batch)

        return [
            component for component in self.component_builds
            if component.batch == self.batch
        ]

    def mmd(self):
        mmd = _modulemd.ModuleMetadata()
        try:
            mmd.loads(self.modulemd)
        except:
            raise ValueError("Invalid modulemd")
        return mmd

    @validates('state')
    def validate_state(self, key, field):
        if field in BUILD_STATES.values():
            return field
        if field in BUILD_STATES:
            return BUILD_STATES[field]
        raise ValueError("%s: %s, not in %r" % (key, field, BUILD_STATES))

    @classmethod
    def from_module_event(cls, session, event):
        if '.module.' not in event['topic']:
            raise ValueError("%r is not a module message." % event['topic'])
        return session.query(cls).filter(cls.id==event['msg']['id']).first()

    @classmethod
    def create(cls, session, conf, name, version, release, modulemd, scmurl):
        module = cls(
            name=name,
            version=version,
            release=release,
            state="init",
            modulemd=modulemd,
            scmurl=scmurl,
        )
        session.add(module)
        session.commit()
        rida.messaging.publish(
            modname='rida',
            topic='module.state.change',
            msg=module.json(),  # Note the state is "init" here...
            backend=conf.messaging,
        )
        return module

    def transition(self, conf, state):
        """ Record that a build has transitioned state. """
        old_state = self.state
        self.state = state
        log.debug("%r, state %r->%r" % (self, old_state, self.state))
        rida.messaging.publish(
            modname='rida',
            topic='module.state.change',
            msg=self.json(),  # Note the state is "init" here...
            backend=conf.messaging,
        )

    @classmethod
    def by_state(cls, session, state):
        return session.query(rida.database.ModuleBuild)\
            .filter_by(state=BUILD_STATES[state]).all()

    @classmethod
    def from_repo_done_event(cls, session, event):
        """ Find the ModuleBuilds in our database that should be in-flight...
        ... for a given koji tag.

        There should be at most one.
        """
        tag = event['msg']['tag'].strip('-build')
        query = session.query(cls)\
            .filter(cls.koji_tag==tag)\
            .filter(cls.state==BUILD_STATES["build"])

        count = query.count()
        if count > 1:
            raise RuntimeError("%r module builds in flight for %r" % (count, tag))

        return query.first()

    def json(self):
        return {
            'id': self.id,
            'name': self.name,
            'version': self.version,
            'release': self.release,
            'state': self.state,
            'state_name': INVERSE_BUILD_STATES[self.state],
            'scmurl': self.scmurl,

            # TODO, show their entire .json() ?
            'component_builds': [build.id for build in self.component_builds],
        }

    def __repr__(self):
        return "<ModuleBuild %s-%s-%s, state %r, batch %r>" % (
            self.name, self.version, self.release,
            INVERSE_BUILD_STATES[self.state], self.batch)


class ComponentBuild(Base):
    __tablename__ = "component_builds"
    id = Column(Integer, primary_key=True)
    package = Column(String, nullable=False)
    scmurl = Column(String, nullable=False)
    # XXX: Consider making this a proper ENUM
    format = Column(String, nullable=False)
    task_id = Column(Integer)  # This is the id of the build in koji
    # XXX: Consider making this a proper ENUM (or an int)
    state = Column(Integer)
    # This stays as None until the build completes.
    nvr = Column(String)

    # A monotonically increasing integer that represents which batch or
    # iteration this *component* is currently in.  This relates to the owning
    # module's batch.  This one defaults to None, which means that this
    # component is not currently part of a batch.
    batch = Column(Integer, default=0)

    module_id = Column(Integer, ForeignKey('module_builds.id'), nullable=False)
    module_build = relationship('ModuleBuild', backref='component_builds', lazy=False)

    @classmethod
    def from_component_event(cls, session, event):
        if 'component.state.change' not in event['topic'] and '.buildsys.build.state.change' not in event['topic']:
            raise ValueError("%r is not a koji message." % event['topic'])
        return session.query(cls).filter(cls.task_id==event['msg']['task_id']).first()

    def json(self):
        retval = {
            'id': self.id,
            'package': self.package,
            'format': self.format,
            'task_id': self.task_id,
            'state': self.state,
            'module_build': self.module_id,
        }

        try:
            # Koji is py2 only, so this fails if the main web process is
            # running on py3.
            import koji
            retval['state_name'] = koji.BUILD_STATES.get(self.state)
        except ImportError:
            pass

        return retval



    def __repr__(self):
        return "<ComponentBuild %s, %r, state: %r, task_id: %r, batch: %r>" % (
            self.package, self.module_id, self.state, self.task_id, self.batch)
