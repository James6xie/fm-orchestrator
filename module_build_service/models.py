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
#            Matt Prahl <mprahl@redhat.com>

""" SQLAlchemy Database models for the Flask app
"""

import contextlib

from datetime import datetime
from sqlalchemy import engine_from_config, event
from sqlalchemy.orm import validates, scoped_session, sessionmaker
import modulemd as _modulemd

from module_build_service import db, log, get_url_for
import module_build_service.messaging

from sqlalchemy.orm import lazyload

# Just like koji.BUILD_STATES, except our own codes for modules.
BUILD_STATES = {
    # When you parse the modulemd file and know the nvr and you create a
    # record in the db, and that's it.
    # publish the message
    # validate that components are available
    #   and that you can fetch them.
    # if all is good, go to wait: telling module_build_service_daemon to take over.
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


@contextlib.contextmanager
def make_session(conf):
    # TODO - we could use ZopeTransactionExtension() here some day for
    # improved safety on the backend.
    engine = engine_from_config({
        'sqlalchemy.url': conf.sqlalchemy_database_uri,
    })
    session = scoped_session(sessionmaker(bind=engine))()
    event.listen(session, "before_commit", session_before_commit_handlers)
    try:
        yield session
        session.commit()
    except:
        # This is a no-op if no transaction is in progress.
        session.rollback()
        raise
    finally:
        session.close()


class MBSBase(db.Model):
    # TODO -- we can implement functionality here common to all our model classes
    __abstract__ = True


class ModuleBuild(MBSBase):
    __tablename__ = "module_builds"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    stream = db.Column(db.String, nullable=False)
    version = db.Column(db.String, nullable=False)
    state = db.Column(db.Integer, nullable=False)
    state_reason = db.Column(db.String)
    modulemd = db.Column(db.String, nullable=False)
    koji_tag = db.Column(db.String)  # This gets set after 'wait'
    copr_owner = db.Column(db.String)
    copr_project = db.Column(db.String)
    scmurl = db.Column(db.String)
    owner = db.Column(db.String, nullable=False)
    time_submitted = db.Column(db.DateTime, nullable=False)
    time_modified = db.Column(db.DateTime)
    time_completed = db.Column(db.DateTime)

    # A monotonically increasing integer that represents which batch or
    # iteration this module is currently on for successive rebuilds of its
    # components.  Think like 'mockchain --recurse'
    batch = db.Column(db.Integer, default=0)

    def current_batch(self, state=None):
        """ Returns all components of this module in the current batch. """

        if not self.batch:
            raise ValueError("No batch is in progress: %r" % self.batch)

        if state != None:
            return [
                component for component in self.component_builds
                if component.batch == self.batch and component.state == state
            ]
        else:
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
        if type(event) == module_build_service.messaging.MBSModule:
            return session.query(cls).filter(
                cls.id == event.module_build_id).first()
        else:
            raise ValueError("%r is not a module message."
                             % type(event).__name__)

    @classmethod
    def create(cls, session, conf, name, stream, version, modulemd, scmurl, username,
               copr_owner=None, copr_project=None):
        now = datetime.utcnow()
        module = cls(
            name=name,
            stream=stream,
            version=version,
            state="init",
            modulemd=modulemd,
            scmurl=scmurl,
            owner=username,
            time_submitted=now,
            copr_owner=copr_owner,
            copr_project=copr_project,
        )
        session.add(module)
        session.commit()
        module_build_service.messaging.publish(
            service='mbs',
            topic='module.state.change',
            msg=module.json(),  # Note the state is "init" here...
            conf=conf,
        )
        return module

    def transition(self, conf, state, state_reason=None):
        """ Record that a build has transitioned state. """
        now = datetime.utcnow()
        old_state = self.state
        self.state = state
        self.time_modified = now

        if INVERSE_BUILD_STATES[self.state] in ['done', 'failed']:
            self.time_completed = now

        if state_reason:
            self.state_reason = state_reason

        # record module's state change
        mbt = ModuleBuildTrace(state_time=now,
                               state=self.state,
                               state_reason=state_reason)
        self.module_builds_trace.append(mbt)

        log.info("%r, state %r->%r" % (self, old_state, self.state))
        if old_state != self.state:
            module_build_service.messaging.publish(
                service='mbs',
                topic='module.state.change',
                msg=self.json(),  # Note the state is "init" here...
                conf=conf,
            )

    @classmethod
    def by_state(cls, session, state):
        return session.query(ModuleBuild).filter_by(state=BUILD_STATES[state]).all()

    @classmethod
    def from_repo_done_event(cls, session, event):
        """ Find the ModuleBuilds in our database that should be in-flight...
        ... for a given koji tag.

        There should be at most one.
        """
        tag = event.repo_tag.strip('-build')
        query = session.query(cls)\
            .filter(cls.koji_tag == tag)\
            .filter(cls.state == BUILD_STATES["build"])

        count = query.count()
        if count > 1:
            raise RuntimeError("%r module builds in flight for %r" % (count, tag))

        return query.first()

    def json(self):
        return {
            'id': self.id,
            'name': self.name,
            'stream': self.stream,
            'version': self.version,
            'state': self.state,
            'state_name': INVERSE_BUILD_STATES[self.state],
            'state_reason': self.state_reason,
            'state_url': get_url_for('module_build', id=self.id),
            'scmurl': self.scmurl,
            'owner': self.owner,
            'time_submitted': self.time_submitted,
            'time_modified': self.time_modified,
            'time_completed': self.time_completed,
            "tasks": self.tasks(),
            # TODO, show their entire .json() ?
            'component_builds': [build.id for build in self.component_builds],
            'modulemd': self.modulemd,
            'state_trace': [{'time': record.state_time,
                             'state': record.state,
                             'state_name': INVERSE_BUILD_STATES[record.state],
                             'reason': record.state_reason}
                            for record
                            in self.state_trace(self.id)]
        }

    @staticmethod
    def _utc_datetime_to_iso(datetime_object):
        """
        Takes a UTC datetime object and returns an ISO formatted string
        :param datetime_object: datetime.datetime
        :return: string with datetime in ISO format
        """
        if datetime_object:
            # Converts the datetime to ISO 8601
            return datetime_object.strftime("%Y-%m-%dT%H:%M:%SZ")

        return None

    def api_json(self):
        return {
            "id": self.id,
            "state": self.state,
            'state_name': INVERSE_BUILD_STATES[self.state],
            'state_reason': self.state_reason,
            "owner": self.owner,
            "name": self.name,
            "time_submitted": self._utc_datetime_to_iso(self.time_submitted),
            "time_modified": self._utc_datetime_to_iso(self.time_modified),
            "time_completed": self._utc_datetime_to_iso(self.time_completed),
            "tasks": self.tasks()
        }

    def tasks(self):
        """
        :return: dictionary containing the tasks associated with the build
        """
        tasks = dict()
        if self.id and self.state != 'init':
            for build in ComponentBuild.query\
                    .filter_by(module_id=self.id)\
                    .options(lazyload('module_build'))\
                    .all():
                tasks[build.format] = tasks.get(build.format, {})
                tasks[build.format][build.package] = dict(
                    task_id=build.task_id,
                    state=build.state,
                    state_reason=build.state_reason,
                    nvr=build.nvr,
                    # TODO -- it would be really nice from a UX PoV to get a
                    # link to the remote task here.
                )

        return tasks

    def state_trace(self, module_id):
        return ModuleBuildTrace.query.filter_by(
            module_id=module_id).order_by(ModuleBuildTrace.state_time).all()

    def __repr__(self):
        return "<ModuleBuild %s, stream=%s, version=%s, state %r, batch %r, state_reason %r>" % (
            self.name, self.stream, self.version,
            INVERSE_BUILD_STATES[self.state], self.batch, self.state_reason)


class ModuleBuildTrace(MBSBase):
    __tablename__ = "module_builds_trace"
    id = db.Column(db.Integer, primary_key=True)
    module_id = db.Column(db.Integer, db.ForeignKey('module_builds.id'), nullable=False)
    state_time = db.Column(db.DateTime, nullable=False)
    state = db.Column(db.Integer, nullable=True)
    state_reason = db.Column(db.String, nullable=True)

    module_build = db.relationship('ModuleBuild', backref='module_builds_trace', lazy=False)

    def json(self):
        retval = {
            'id': self.id,
            'module_id': self.module_id,
            'state_time': self.state_time,
            'state': self.state,
            'state_reason': self.state_reason,
        }

        return retval

    def __repr__(self):
        return "<ModuleBuildTrace %s, module_id: %s, state_time: %r, state: %s, state_reason: %s>" % (
            self.id, self.module_id, self.state_time, self.state, self.state_reason)


class ComponentBuild(MBSBase):
    __tablename__ = "component_builds"
    id = db.Column(db.Integer, primary_key=True)
    package = db.Column(db.String, nullable=False)
    scmurl = db.Column(db.String, nullable=False)
    # XXX: Consider making this a proper ENUM
    format = db.Column(db.String, nullable=False)
    task_id = db.Column(db.Integer)  # This is the id of the build in koji
    # This is the commit hash that component was built with
    ref = db.Column(db.String, nullable=True)
    # XXX: Consider making this a proper ENUM (or an int)
    state = db.Column(db.Integer)
    # Reason why the build failed
    state_reason = db.Column(db.String)
    # This stays as None until the build completes.
    nvr = db.Column(db.String)

    # A monotonically increasing integer that represents which batch or
    # iteration this *component* is currently in.  This relates to the owning
    # module's batch.  This one defaults to None, which means that this
    # component is not currently part of a batch.
    batch = db.Column(db.Integer, default=0)

    module_id = db.Column(db.Integer, db.ForeignKey('module_builds.id'), nullable=False)
    module_build = db.relationship('ModuleBuild', backref='component_builds', lazy=False)
    reused_component_id = db.Column(
        db.Integer, db.ForeignKey('component_builds.id'))

    @classmethod
    def from_component_event(cls, session, event):
        if type(event) == module_build_service.messaging.KojiBuildChange:
            if event.module_build_id:
                return session.query(cls).filter_by(
                    task_id=event.task_id, module_id=event.module_build_id)\
                    .one()
            else:
                return session.query(cls).filter(
                    cls.task_id == event.task_id).first()
        else:
            raise ValueError("%r is not a koji message." % event['topic'])

    @classmethod
    def from_component_name(cls, session, component_name, module_id):
        return session.query(cls).filter_by(
            package=component_name, module_id=module_id).first()

    def json(self):
        retval = {
            'id': self.id,
            'package': self.package,
            'format': self.format,
            'task_id': self.task_id,
            'state': self.state,
            'state_reason': self.state_reason,
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
        return "<ComponentBuild %s, %r, state: %r, task_id: %r, batch: %r, state_reason: %s>" % (
            self.package, self.module_id, self.state, self.task_id, self.batch, self.state_reason)


class ComponentBuildTrace(MBSBase):
    __tablename__ = "component_builds_trace"
    id = db.Column(db.Integer, primary_key=True)
    component_id = db.Column(db.Integer, db.ForeignKey('component_builds.id'), nullable=False)
    state_time = db.Column(db.DateTime, nullable=False)
    state = db.Column(db.Integer, nullable=True)
    state_reason = db.Column(db.String, nullable=True)
    task_id = db.Column(db.Integer, nullable=True)

    component_build = db.relationship('ComponentBuild', backref='component_builds_trace', lazy=False)

    def json(self):
        retval = {
            'id': self.id,
            'component_id': self.component_id,
            'state_time': self.state_time,
            'state': self.state,
            'state_reason': self.state_reason,
            'task_id': self.task_id,
        }

        return retval

    def __repr__(self):
        return "<ComponentBuildTrace %s, component_id: %s, state_time: %r, state: %s, state_reason: %s, task_id: %s>" % (
            self.id, self.component_id, self.state_time, self.state, self.state_reason, self.task_id)


def session_before_commit_handlers(session):
    # new and updated items
    for item in (set(session.new) | set(session.dirty)):

        # handlers for module builds
        if isinstance(item, ModuleBuild):
            mbt = ModuleBuildTrace(
                state_time=datetime.utcnow(),
                state=item.state,
                state_reason=item.state_reason)
            item.module_builds_trace.append(mbt)

        # handlers for component builds
        elif isinstance(item, ComponentBuild):
            cbt = ComponentBuildTrace(
                state_time=datetime.utcnow(),
                state=item.state,
                state_reason=item.state_reason,
                task_id=item.task_id)
            item.component_builds_trace.append(cbt)
