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
from datetime import timedelta, datetime
from sqlalchemy.orm import lazyload
from moksha.hub.api.producer import PollingProducer

import module_build_service.messaging
import module_build_service.scheduler
import module_build_service.scheduler.consumer
from module_build_service import conf, models, log
from module_build_service.builder import GenericBuilder


class MBSProducer(PollingProducer):
    frequency = timedelta(seconds=conf.polling_interval)

    def poll(self):
        with models.make_session(conf) as session:
            try:
                self.log_summary(session)
                # XXX: detect whether it's actually stuck first
                # self.process_waiting_module_builds(session)
                self.process_open_component_builds(session)
                self.fail_lost_builds(session)
                self.process_paused_module_builds(conf, session)
                self.trigger_new_repo_when_stalled(conf, session)
                self.delete_old_koji_targets(conf, session)
            except Exception:
                msg = 'Error in poller execution:'
                log.exception(msg)

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

                # Don't check tasks for components which have been reused,
                # they may have BUILDING state temporarily before we tag them
                # to new module tag. Checking them would be waste of resources.
                if component_build.reused_component_id:
                    log.debug('Skipping check for task "{0}", '
                              'the component has been reused.'.format(task_id))
                    continue

                task_id = component_build.task_id

                log.info('Checking status of task_id "{0}"'.format(task_id))
                task_info = koji_session.getTaskInfo(task_id)

                state_mapping = {
                    # Cancelled and failed builds should be marked as failed.
                    koji.TASK_STATES['CANCELED']: koji.BUILD_STATES['FAILED'],
                    koji.TASK_STATES['FAILED']: koji.BUILD_STATES['FAILED'],
                    # Completed tasks should be marked as complete.
                    koji.TASK_STATES['CLOSED']: koji.BUILD_STATES['COMPLETE'],
                }

                # If it is a closed/completed task, then we can extract the NVR
                build_version, build_release = None, None  # defaults
                if task_info['state'] == koji.TASK_STATES['CLOSED']:
                    builds = koji_session.listBuilds(taskID=task_id)
                    if not builds:
                        log.warn("Task ID %r is closed, but we found no "
                                 "builds in koji." % task_id)
                    elif len(builds) > 1:
                        log.warn("Task ID %r is closed, but more than one "
                                 "build is present!" % task_id)
                    else:
                        build_version = builds[0]['version']
                        build_release = builds[0]['release']

                log.info('  task {0!r} is in state {1!r}'.format(
                    task_id, task_info['state']))
                if task_info['state'] in state_mapping:
                    # Fake a fedmsg message on our internal queue
                    msg = module_build_service.messaging.KojiBuildChange(
                        msg_id='producer::fail_lost_builds fake msg',
                        build_id=component_build.task_id,
                        task_id=component_build.task_id,
                        build_name=component_build.package,
                        build_new_state=state_mapping[task_info['state']],
                        build_release=build_release,
                        build_version=build_version,
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
                    # First batch is number '1'.
                    for i in range(1, module_build.batch + 1):
                        n = len([c for c in module_build.component_builds
                                 if c.batch == i])
                        log.info('      * {0} components in batch {1}'
                                 .format(n, i))

    def process_waiting_module_builds(self, session):
        log.info('Looking for module builds stuck in the wait state')
        builds = models.ModuleBuild.by_state(session, 'wait')
        log.info(' {0!r} module builds in the wait state...'
                 .format(len(builds)))
        for build in builds:
            # Fake a message to kickstart the build anew
            msg = module_build_service.messaging.MBSModule(
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
        for module_build in session.query(models.ModuleBuild).filter_by(state=models.BUILD_STATES['build']).all():
            # If there are no components in the build state on the module build,
            # then no possible event will start off new component builds.
            # But do not try to start new builds when we are waiting for the
            # repo-regen.
            if (not module_build.current_batch(koji.BUILD_STATES['BUILDING']) and
               not module_build.new_repo_task_id):
                # Initialize the builder...
                builder = GenericBuilder.create_from_module(
                    session, module_build, config)

                further_work = module_build_service.utils.start_next_batch_build(
                    config, module_build, session, builder)
                for event in further_work:
                    log.info("  Scheduling faked event %r" % event)
                    module_build_service.scheduler.consumer.work_queue_put(event)

            # Check if we have met the threshold.
            if module_build_service.utils.at_concurrent_component_threshold(
                    config, session):
                break

    def trigger_new_repo_when_stalled(self, config, session):
        """
        Sometimes the Koji repo regeneration stays in "init" state without
        doing anything and our module build stucks. In case the module build
        gets stuck on that, we trigger newRepo again to rebuild it.
        """
        if config.system != 'koji':
            return

        koji_session = module_build_service.builder.KojiModuleBuilder\
            .get_session(config, None)

        for module_build in session.query(models.ModuleBuild).filter_by(state=models.BUILD_STATES['build']).all():
            if not module_build.new_repo_task_id:
                continue

            task_info = koji_session.getTaskInfo(module_build.new_repo_task_id)
            if (task_info["state"] in [koji.TASK_STATES['CANCELED'],
                                       koji.TASK_STATES['FAILED']]):
                log.info("newRepo task %s for %r failed, starting another one",
                         str(module_build.new_repo_task_id), module_build)
                taginfo = koji_session.getTag(module_build.koji_tag + "-build")
                module_build.new_repo_task_id = koji_session.newRepo(taginfo["name"])
            else:
                module_build.new_repo_task_id = 0

        session.commit()

    def delete_old_koji_targets(self, config, session):
        """
        Deletes targets older than `config.koji_target_delete_time` seconds
        from Koji to cleanup after the module builds.
        """
        if config.system != 'koji':
            return

        log.info('Looking for module builds which Koji target can be removed')

        now = datetime.utcnow()

        koji_session = module_build_service.builder.KojiModuleBuilder\
            .get_session(config, None)
        for target in koji_session.getBuildTargets():
            koji_tag = target["dest_tag_name"]
            module = session.query(models.ModuleBuild).filter_by(
                koji_tag=koji_tag).first()
            if not module or module.state in [models.BUILD_STATES["init"],
                                              models.BUILD_STATES["wait"],
                                              models.BUILD_STATES["build"]]:
                continue

            # Double-check that the target we are going to remove is prefixed
            # by our prefix, so we won't remove f26 when there is some garbage
            # in DB or Koji.
            for allowed_prefix in config.koji_tag_prefixes:
                if target['name'].startswith(allowed_prefix + "-"):
                    break
            else:
                log.error("Module %r has Koji target with not allowed prefix.",
                          module)
                continue

            delta = now - module.time_completed
            if delta.total_seconds() > config.koji_target_delete_time:
                log.info("Removing target of module %r", module)
                koji_session.deleteBuildTarget(target['id'])
