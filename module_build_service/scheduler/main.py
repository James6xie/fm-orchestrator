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
import operator
import os
import threading
import time
import six.moves.queue as queue

import module_build_service.config
import module_build_service.messaging
import module_build_service.utils
import module_build_service.scheduler.handlers.components
import module_build_service.scheduler.handlers.modules
import module_build_service.scheduler.handlers.repos

import koji

from module_build_service import conf, models, log

from sqlalchemy.orm import lazyload


class STOP_WORK(object):
    """ A sentinel value, indicating that work should be stopped. """
    pass


def module_build_state_from_msg(msg):
    state = int(msg.module_build_state)
    # TODO better handling
    assert state in models.BUILD_STATES.values(), (
        'state=%s(%s) is not in %s'
        % (state, type(state), list(models.BUILD_STATES.values())))
    return state


class MessageIngest(threading.Thread):
    def __init__(self, outgoing_work_queue, stop_after_build, *args, **kwargs):
        self.outgoing_work_queue = outgoing_work_queue
        super(MessageIngest, self).__init__(*args, **kwargs)
        self.stop_after_build = stop_after_build

    def run(self):
        for msg in module_build_service.messaging.listen(conf):
            self.outgoing_work_queue.put(msg)

            if type(msg) == module_build_service.messaging.RidaModule:
                if (self.stop_after_build and module_build_state_from_msg(msg)
                        in [models.BUILD_STATES["failed"], models.BUILD_STATES["ready"]]):
                    break


class MessageWorker(threading.Thread):

    def __init__(self, incoming_work_queue, stop_after_build, *args, **kwargs):
        self.incoming_work_queue = incoming_work_queue
        self.stop_after_build = stop_after_build
        super(MessageWorker, self).__init__(*args, **kwargs)

        # These are our main lookup tables for figuring out what to run in response
        # to what messaging events.
        self.NO_OP = NO_OP = lambda config, session, msg: True
        self.on_build_change = {
            koji.BUILD_STATES["BUILDING"]: NO_OP,
            koji.BUILD_STATES["COMPLETE"]: module_build_service.scheduler.handlers.components.complete,
            koji.BUILD_STATES["FAILED"]: module_build_service.scheduler.handlers.components.failed,
            koji.BUILD_STATES["CANCELED"]: module_build_service.scheduler.handlers.components.canceled,
            koji.BUILD_STATES["DELETED"]: NO_OP,
        }
        self.on_module_change = {
            models.BUILD_STATES["init"]: NO_OP,
            models.BUILD_STATES["wait"]: module_build_service.scheduler.handlers.modules.wait,
            models.BUILD_STATES["build"]: NO_OP,
            models.BUILD_STATES["failed"]: module_build_service.scheduler.handlers.modules.failed,
            models.BUILD_STATES["done"]: module_build_service.scheduler.handlers.modules.done,  # XXX: DIRECT TRANSITION TO READY
            models.BUILD_STATES["ready"]: NO_OP,
        }
        # Only one kind of repo change event, though...
        self.on_repo_change = module_build_service.scheduler.handlers.repos.done

    def sanity_check(self):
        """ On startup, make sure our implementation is sane. """
        # Ensure we have every state covered
        for state in models.BUILD_STATES:
            if models.BUILD_STATES[state] not in self.on_module_change:
                raise KeyError("Module build states %r not handled." % state)
        for state in koji.BUILD_STATES:
            if koji.BUILD_STATES[state] not in self.on_build_change:
                raise KeyError("Koji build states %r not handled." % state)

        all_fns = (list(self.on_build_change.items()) +
                   list(self.on_module_change.items()))
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
                with models.make_session(conf) as session:
                    self.process_message(session, msg)
            except Exception:
                log.exception("Failed while handling %r" % msg.msg_id)
                log.info(msg)

    def process_message(self, session, msg):
        log.debug('Received a message with an ID of "{0}" and of type "{1}"'
                  .format(msg.msg_id, type(msg).__name__))

        # Choose a handler for this message
        if type(msg) == module_build_service.messaging.KojiBuildChange:
            handler = self.on_build_change[msg.build_new_state]
        elif type(msg) == module_build_service.messaging.KojiRepoChange:
            handler = self.on_repo_change
        elif type(msg) == module_build_service.messaging.RidaModule:
            handler = self.on_module_change[module_build_state_from_msg(msg)]
            if (self.stop_after_build and module_build_state_from_msg(msg)
                    in [models.BUILD_STATES["failed"], models.BUILD_STATES["ready"]]):
                self.incoming_work_queue.put(STOP_WORK)
        else:
            log.debug("Unhandled message...")
            return

        # Execute our chosen handler
        idx = "%s: %s, %s" % (handler.__name__, type(msg).__name__,
                              msg.msg_id)
        if handler is self.NO_OP:
            log.debug("Handler is NO_OP: %s" % idx)
        else:
            log.info("Calling %s" % idx)
            further_work = handler(conf, session, msg) or []
            log.info("Done with %s" % idx)

            # Handlers can *optionally* return a list of fake messages that
            # should be re-inserted back into the main work queue. We can use
            # this (for instance) when we submit a new component build but (for
            # some reason) it has already been built, then it can fake its own
            # completion back to the scheduler so that work resumes as if it
            # was submitted for real and koji announced its completion.
            for event in further_work:
                log.info("  Scheduling faked event %r" % event)
                self.incoming_work_queue.put(event)


class Poller(threading.Thread):
    def __init__(self, outgoing_work_queue, *args, **kwargs):
        self.outgoing_work_queue = outgoing_work_queue
        super(Poller, self).__init__(*args, **kwargs)
        self.stop = False

    def run(self):
        while not self.stop:
            with models.make_session(conf) as session:
                self.log_summary(session)
                # XXX: detect whether it's really stucked first
                # self.process_waiting_module_builds(session)
                self.process_open_component_builds(session)
                self.fail_lost_builds(session)
                self.process_paused_module_builds(conf, session)

            log.info("Polling thread sleeping, %rs" % conf.polling_interval)
            for i in range(0, conf.polling_interval):
                time.sleep(1)
                if self.stop:
                    break

    def fail_lost_builds(self, session):
        # This function is supposed to be handling only
        # the part which can't be updated trough messaging (srpm-build failures).
        # Please keep it fit `n` slim. We do want rest to be processed elsewhere

        # TODO re-use

        if conf.system == "koji":
            # we don't do this on behalf of users
            koji_session = (
                module_build_service.builder.KojiModuleBuilder.get_session(conf, None))
            log.info("Querying tasks for statuses:")
            res = models.ComponentBuild.query.filter_by(state=koji.BUILD_STATES['BUILDING']).options(lazyload('module_build')).all()

            log.info("Checking status for %d tasks." % len(res))
            for component_build in res:
                log.debug(component_build.json())
                if not component_build.task_id:  # Don't check tasks which has not been triggered yet
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
                    msg = module_build_service.messaging.KojiBuildChange(
                        msg_id='a faked internal message',
                        build_id=component_build.task_id,
                        task_id=component_build.task_id,
                        build_name=component_build.package,
                        build_new_state=koji.BUILD_STATES['FAILED'],
                        build_release=None,
                        build_version=None
                    )
                    self.outgoing_work_queue.put(msg)

        elif conf.system == "copr":
            # @TODO
            pass

        elif conf.system == "mock":
            pass

    def log_summary(self, session):
        log.info("Current status:")
        backlog = self.outgoing_work_queue.qsize()
        log.info("  * internal queue backlog is %i." % backlog)
        states = sorted(models.BUILD_STATES.items(), key=operator.itemgetter(1))
        for name, code in states:
            query = models.ModuleBuild.query.filter_by(state=code)
            count = query.count()
            if count:
                log.info("  * %i module builds in the %s state." % (count, name))
            if name == 'build':
                for module_build in query.all():
                    log.info("    * %r" % module_build)
                    for i in range(module_build.batch):
                        n = len([c for c in module_build.component_builds
                                 if c.batch == i])
                        log.info("      * %i components in batch %i" % (n, i))

    def process_waiting_module_builds(self, session):
        log.info("Looking for module builds stuck in the wait state.")
        builds = models.ModuleBuild.by_state(session, "wait")
        # TODO -- do throttling calculation here...
        log.info(" %r module builds in the wait state..." % len(builds))
        for build in builds:
            # Fake a message to kickstart the build anew
            msg = {
                'topic': '.module.build.state.change',
                'msg': build.json(),
            }
            module_build_service.scheduler.handlers.modules.wait(conf, session, msg)

    def process_open_component_builds(self, session):
        log.warning("process_open_component_builds is not yet implemented...")

    def process_paused_module_builds(self, config, session):
        if module_build_service.utils.at_concurrent_component_threshold(
                config, session):
            log.debug('Will not attempt to start paused module builds due to '
                      'the concurrent build threshold being met')
            return
        # Check to see if module builds that are in build state but don't have
        # any component builds being built can be worked on
        for module_build in session.query(models.ModuleBuild).filter_by(
                    state=models.BUILD_STATES['build']).all():
            # If there are no components in the build state on the module build,
            # then no possible event will start off new component builds
            if not module_build.current_batch(koji.BUILD_STATES['BUILDING']):
                module_build_service.utils.start_build_batch(
                    config, module_build, session, config.system)


_work_queue = queue.Queue()


def outgoing_work_queue_put(msg):
    _work_queue.put(msg)


def graceful_stop():
    log.warning("graceful_stop is not yet implemented...")
    while True:
        time.sleep(30)


def main(initial_msgs=[], return_after_build=False):
    log.info("Starting module_build_service_daemon.")

    for msg in initial_msgs:
        outgoing_work_queue_put(msg)

    # This ingest thread puts work on the queue
    messaging_thread = MessageIngest(_work_queue, return_after_build)
    # This poller does other work, but also sometimes puts work in queue.
    polling_thread = Poller(_work_queue)
    # This worker takes work off the queue and handles it.
    worker_thread = MessageWorker(_work_queue, return_after_build)

    messaging_thread.start()
    polling_thread.start()
    worker_thread.start()

    try:
        while worker_thread.is_alive():
            time.sleep(3)
    except KeyboardInterrupt:
        log.info("Stopping module_build_service_daemon. Press Ctrl+C again to force.")
        try:
            graceful_stop()
        except KeyboardInterrupt:
            os._exit(0)
    finally:
        polling_thread.stop = True
