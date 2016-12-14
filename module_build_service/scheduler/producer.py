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

""" The PollingProducer class that acts as a producer entry point for
fedmsg-hub. This class polls the database for tasks to do.
"""

import koji
import operator
from datetime import timedelta
from sqlalchemy.orm import lazyload
from moksha.hub.api.producer import PollingProducer

import module_build_service.messaging
import module_build_service.scheduler
import module_build_service.scheduler.consumer
from module_build_service import conf, models, log


class MBSProducer(PollingProducer):
    frequency = timedelta(seconds=conf.polling_interval)

    def poll(self):
        with models.make_session(conf) as session:
            self.log_summary(session)
            # XXX: detect whether it's actually stuck first
            # self.process_waiting_module_builds(session)
            self.process_open_component_builds(session)
            self.fail_lost_builds(session)
            self.process_paused_module_builds(conf, session)

        log.info('Poller will now sleep for "{}" seconds'
                 .format(conf.polling_interval))

    def fail_lost_builds(self, session):
        # This function is supposed to be handling only the part which can't be
        # updated through messaging (e.g. srpm-build failures). Please keep it
        # fit `n` slim. We do want rest to be processed elsewhere
        # TODO re-use

        if conf.system == 'koji':
            # We don't do this on behalf of users
            koji_session = module_build_service.builder.KojiModuleBuilder\
                .get_session(conf, None)
            log.info('Querying tasks for statuses:')
            res = models.ComponentBuild.query.filter_by(
                state=koji.BUILD_STATES['BUILDING']).options(
                    lazyload('module_build')).all()

            log.info('Checking status for {0} tasks'.format(len(res)))
            for component_build in res:
                log.debug(component_build.json())
                # Don't check tasks which haven't been triggered yet
                if not component_build.task_id:
                    continue

                log.info('Checking status of task_id "{0}"'
                         .format(component_build.task_id))
                task_info = koji_session.getTaskInfo(component_build.task_id)

                dead_states = (
                    koji.TASK_STATES['CANCELED'],
                    koji.TASK_STATES['FAILED'],
                )

                log.info('  task {0!r} is in state {0!r}'.format(
                    component_build.task_id, task_info['state']))
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
                    module_build_service.scheduler.consumer.work_queue_put(msg)

        elif conf.system == 'copr':
            # @TODO
            pass

        elif conf.system == 'mock':
            pass

    def log_summary(self, session):
        log.info('Current status:')
        consumer = module_build_service.scheduler.consumer.get_global_consumer()
        backlog = consumer.incoming.qsize()
        log.info('  * internal queue backlog is {0}'.format(backlog))
        states = sorted(models.BUILD_STATES.items(), key=operator.itemgetter(1))
        for name, code in states:
            query = models.ModuleBuild.query.filter_by(state=code)
            count = query.count()
            if count:
                log.info('  * {0} module builds in the {1} state'.format(
                    count, name))
            if name == 'build':
                for module_build in query.all():
                    log.info('    * {0!r}'.format(module_build))
                    for i in range(module_build.batch):
                        n = len([c for c in module_build.component_builds
                                 if c.batch == i ])
                        log.info('      * {0} components in batch {1}'
                                 .format(n, i))

    def process_waiting_module_builds(self, session):
        log.info('Looking for module builds stuck in the wait state')
        builds = models.ModuleBuild.by_state(session, 'wait')
        log.info(' {0!r} module builds in the wait state...'
                 .format(len(builds)))
        for build in builds:
            # Fake a message to kickstart the build anew
            msg = module_build_service.messaging.RidaModule(
                'fake message',
                build.id,
                module_build_service.models.BUILD_STATES['wait']
            )
            further_work = module_build_service.scheduler.handlers.modules.wait(
                conf, session, msg) or []
            for event in further_work:
                log.info("  Scheduling faked event %r" % event)
                module_build_service.scheduler.consumer.work_queue_put(event)

    def process_open_component_builds(self, session):
        log.warning('process_open_component_builds is not yet implemented...')

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
                further_work = module_build_service.utils.start_build_batch(
                    config, module_build, session, config.system)
                for event in further_work:
                    log.info("  Scheduling faked event %r" % event)
                    module_build_service.scheduler.consumer.work_queue_put(event)
