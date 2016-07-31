#!/usr/bin/python3
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

"""The module build orchestrator for Modularity, the builder.

This is the main component of the orchestrator and is responsible for
proper scheduling component builds in the supported build systems.
"""


import inspect
import logging
import operator
import os
import pprint
import threading
import time

try:
    # Py3
    import queue
except ImportError:
    # Py2
    import Queue as queue


import rida.config
import rida.logger
import rida.messaging
import rida.scheduler.handlers.components
import rida.scheduler.handlers.modules
import rida.scheduler.handlers.repos
import sys

import koji

log = logging.getLogger(__name__)

# Load config from git checkout or the default location
config = None
here = sys.path[0]
if here not in ('/usr/bin', '/bin', '/usr/local/bin'):
    # git checkout
    config = rida.config.from_file("rida.conf")
else:
    # production
    config = rida.config.from_file()


class STOP_WORK(object):
    """ A sentinel value, indicating that work should be stopped. """
    pass


def module_build_state_from_msg(msg):
    state = int(msg['msg']['state'])
    # TODO better handling
    assert state in rida.BUILD_STATES.values(), "state=%s(%s) is not in %s" % (state, type(state), rida.BUILD_STATES.values())
    return state


class MessageIngest(threading.Thread):
    def __init__(self, outgoing_work_queue, *args, **kwargs):
        self.outgoing_work_queue = outgoing_work_queue
        super(MessageIngest, self).__init__(*args, **kwargs)


    def run(self):
        for msg in rida.messaging.listen(backend=config.messaging):
            self.outgoing_work_queue.put(msg)


class MessageWorker(threading.Thread):

    def __init__(self, incoming_work_queue, *args, **kwargs):
        self.incoming_work_queue = incoming_work_queue
        super(MessageWorker, self).__init__(*args, **kwargs)

        # These are our main lookup tables for figuring out what to run in response
        # to what messaging events.
        self.NO_OP = NO_OP = lambda config, session, msg: True
        self.on_build_change = {
            koji.BUILD_STATES["BUILDING"]: NO_OP,
            koji.BUILD_STATES["COMPLETE"]: rida.scheduler.handlers.components.complete,
            koji.BUILD_STATES["FAILED"]: rida.scheduler.handlers.components.failed,
            koji.BUILD_STATES["CANCELED"]: rida.scheduler.handlers.components.canceled,
            koji.BUILD_STATES["DELETED"]: NO_OP,
        }
        self.on_module_change = {
            rida.BUILD_STATES["init"]: NO_OP,
            rida.BUILD_STATES["wait"]: rida.scheduler.handlers.modules.wait,
            rida.BUILD_STATES["build"]: NO_OP,
            rida.BUILD_STATES["failed"]: NO_OP,
            rida.BUILD_STATES["done"]: NO_OP,
            rida.BUILD_STATES["ready"]: NO_OP,
        }
        # Only one kind of repo change event, though...
        self.on_repo_change = rida.scheduler.handlers.repos.done

    def sanity_check(self):
        """ On startup, make sure our implementation is sane. """
        # Ensure we have every state covered
        for state in rida.BUILD_STATES:
            if rida.BUILD_STATES[state] not in self.on_module_change:
                raise KeyError("Module build states %r not handled." % state)
        for state in koji.BUILD_STATES:
            if koji.BUILD_STATES[state] not in self.on_build_change:
                raise KeyError("Koji build states %r not handled." % state)

        all_fns = self.on_build_change.items() + self.on_module_change.items()
        for key, callback in all_fns:
            expected = ['config', 'session', 'msg']
            argspec = inspect.getargspec(callback)[0]
            if argspec != expected:
                raise ValueError("Callback %r, state %r has argspec %r!=%r" % (
                    callback, key, argspec, expected))

    def run(self):
        self.sanity_check()

        while True:
            msg = self.incoming_work_queue.get()

            if msg is STOP_WORK:
                log.info("Worker thread received STOP_WORK, shutting down...")
                break

            try:
                self.process_message(msg)
            except Exception:
                log.exception("Failed while handling %r" % msg['msg_id'])
                # Log the body of the message too, but clear out some spammy
                # fields that are of no use to a human reader.
                msg.pop('certificate', None)
                msg.pop('signature', None)
                log.info(pprint.pformat(msg))

    def process_message(self, msg):
        log.debug("received %r, %r" % (msg['msg_id'], msg['topic']))

        # Choose a handler for this message
        if '.buildsys.repo.done' in msg['topic']:
            handler = self.on_repo_change
        elif '.buildsys.build.state.change' in msg['topic']:
            handler = self.on_build_change[msg['msg']['new']]
        elif '.rida.module.state.change' in msg['topic']:
            handler = self.on_module_change[module_build_state_from_msg(msg)]
        else:
            log.debug("Unhandled message...")
            return

        # Execute our chosen handler
        idx = "%s: %s, %s" % (handler.__name__, msg['topic'], msg['msg_id'])
        if handler is self.NO_OP:
            log.debug("Handler is NO_OP: %s" % idx)
        else:
            with rida.database.Database(config) as session:
                log.info("Calling   %s" % idx)
                handler(config, session, msg)
                log.info("Done with %s" % idx)


class Poller(threading.Thread):
    def __init__(self, outgoing_work_queue, *args, **kwargs):
        self.outgoing_work_queue = outgoing_work_queue
        super(Poller, self).__init__(*args, **kwargs)

    def run(self):
        while True:
            with rida.database.Database(config) as session:
                self.log_summary(session)
            # XXX: detect whether it's really stucked first
            #with rida.database.Database(config) as session:
            #    self.process_waiting_module_builds(session)
            with rida.database.Database(config) as session:
                self.process_open_component_builds(session)
            with rida.database.Database(config) as session:
                self.process_lingering_module_builds(session)
            with rida.database.Database(config) as session:
                self.fail_lost_builds(session)

            log.info("Polling thread sleeping, %rs" % config.polling_interval)
            time.sleep(config.polling_interval)

    def fail_lost_builds(self, session):
        # This function is supposed to be handling only
        # the part which can't be updated trough messaging (srpm-build failures).
        # Please keep it fit `n` slim. We do want rest to be processed elsewhere

        # TODO re-use

        if config.system == "koji":
            koji_session, _ = rida.builder.KojiModuleBuilder.get_session_from_config(config)
            state = koji.BUILD_STATES['BUILDING'] # Check tasks that we track as BUILDING
            log.info("Querying tasks for statuses:")
            query = session.query(rida.database.ComponentBuild)
            res = query.filter(state==koji.BUILD_STATES['BUILDING']).all()

            log.info("Checking status for %d tasks." % len(res))
            for component_build in res:
                log.debug(component_build.json())
                if not component_build.task_id: # Don't check tasks which has not been triggered yet
                    continue

                log.info("Checking status of task_id=%s" % component_build.task_id)
                task_info = koji_session.getTaskInfo(component_build.task_id)

                dead_states = (
                    koji.TASK_STATES['CANCELED'],
                    koji.TASK_STATES['FAILED'],
                )
                log.info("  task %r is in state %r" % (component_build.task_id, task_info['state']))
                if task_info['state'] in dead_states:
                    # Fake a fedmsg message on our internal queue
                    self.outgoing_work_queue.put({
                        'msg_id': 'a faked internal message',
                        'topic': 'org.fedoraproject.prod.buildsys.build.state.change',
                        'msg': {
                            'msg_id': 'a faked internal message',
                            'task_id': component_build.task_id,
                            'new': koji.BUILD_STATES['FAILED'],
                        },
                    })

        else:
            raise NotImplementedError("Buildsystem %r is not supported." % config.system)

    def log_summary(self, session):
        log.info("Current status:")
        backlog = self.outgoing_work_queue.qsize()
        log.info("  * internal queue backlog is %i." % backlog)
        states = sorted(rida.BUILD_STATES.items(), key=operator.itemgetter(1))
        for name, code in states:
            query = session.query(rida.database.ModuleBuild)
            count = query.filter_by(state=code).count()
            if count:
                log.info("  * %i module builds in the %s state." % (count, name))
            if name == 'build':
                for module_build in query.all():
                    log.info("    * %r" % module_build)
                    for component_build in module_build.component_builds:
                        log.info("      * %r" % component_build)


    def process_waiting_module_builds(self, session):
        log.info("Looking for module builds stuck in the wait state.")
        builds = rida.database.ModuleBuild.by_state(session, "wait")
        # TODO -- do throttling calculation here...
        log.info(" %r module builds in the wait state..." % len(builds))
        for build in builds:
            # Fake a message to kickstart the build anew
            msg = {
                'topic': '.module.build.state.change',
                'msg': build.json(),
            }
            rida.scheduler.handlers.modules.wait(config, session, msg)

    def process_open_component_builds(self, session):
        log.warning("process_open_component_builds is not yet implemented...")

    def process_lingering_module_builds(self, session):
        log.warning("process_lingering_module_builds is not yet implemented...")


def main():
    rida.logger.init_logging(config)
    log.info("Starting ridad.")
    try:
        work_queue = queue.Queue()

        # This ingest thread puts work on the queue
        messaging_thread = MessageIngest(work_queue)
        # This poller does other work, but also sometimes puts work in queue.
        polling_thread = Poller(work_queue)
        # This worker takes work off the queue and handles it.
        worker_thread = MessageWorker(work_queue)

        messaging_thread.start()
        polling_thread.start()
        worker_thread.start()

    except KeyboardInterrupt:
        # FIXME: Make this less brutal
        os._exit()
