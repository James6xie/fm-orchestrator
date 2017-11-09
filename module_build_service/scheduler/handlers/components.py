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
# Written by Ralph Bean <rbean@redhat.com>

""" Handlers for koji component build events on the message bus. """

import logging

import module_build_service.builder
import module_build_service.pdc

import koji

from module_build_service import models, log, messaging

logging.basicConfig(level=logging.DEBUG)


def _finalize(config, session, msg, state):
    """ Called whenever a koji build completes or fails. """

    # First, find our ModuleBuild associated with this component, if any.
    component_build = models.ComponentBuild.from_component_event(session, msg)
    try:
        nvr = "{}-{}-{}".format(msg.build_name, msg.build_version,
                                msg.build_release)
    except KeyError:
        nvr = None

    if not component_build:
        log.debug("We have no record of %s" % nvr)
        return

    log.info("Saw relevant component build of %r from %r." % (nvr, msg.msg_id))

    if msg.state_reason:
        state_reason = msg.state_reason
    elif state != koji.BUILD_STATES['COMPLETE']:
        state_reason = "Failed to build artifact %s in Koji" % (msg.build_name)
    else:
        state_reason = ""

    # Mark the state in the db.
    component_build.state = state
    component_build.nvr = nvr
    component_build.state_reason = state_reason
    session.commit()

    parent = component_build.module_build

    # If the macro build failed, then the module is doomed.
    if (component_build.package == 'module-build-macros' and
       state != koji.BUILD_STATES['COMPLETE']):
        parent.transition(config, state=models.BUILD_STATES['failed'],
                          state_reason=state_reason)
        session.commit()
        return

    further_work = []

    # If there are no other components still building in a batch,
    # we can tag all successfully built components in the batch.
    unbuilt_components_in_batch = [
        c for c in parent.current_batch()
        if c.state == koji.BUILD_STATES['BUILDING'] or not c.state
    ]
    if not unbuilt_components_in_batch:
        failed_components_in_batch = [
            c.nvr for c in parent.current_batch()
            if (c.state in [koji.BUILD_STATES['FAILED'],
                            koji.BUILD_STATES['CANCELED']])
        ]

        built_components_in_batch = [
            c.nvr for c in parent.current_batch()
            if c.state == koji.BUILD_STATES['COMPLETE']
        ]

        builder = module_build_service.builder.GenericBuilder.create_from_module(
            session, parent, config)

        if not built_components_in_batch or failed_components_in_batch:
            # If there are no successfully built components in a batch,
            # there is nothing to tag. If there is some failed component build,
            # we should not tag even the successfully built components, because
            # the module build will fail anyway. Repository won't be
            # regenerated in these cases and therefore we generate fake repo
            # change message here.
            if failed_components_in_batch:
                log.info("Batch done, but not tagging because of failed "
                         "component builds.")
            else:
                log.info("Batch done. No component to tag")
            further_work += [messaging.KojiRepoChange(
                'components::_finalize: fake msg',
                builder.module_build_tag['name'])]
        else:
            # tag && add to srpm-build group if neccessary
            log.info("Batch done.  Tagging %i components." % len(
                built_components_in_batch))
            log.debug("%r" % built_components_in_batch)
            builder.buildroot_add_artifacts(
                built_components_in_batch, install=component_build.build_time_only)

            # Do not tag packages which belong to -build tag to final tag.
            if not component_build.build_time_only:
                builder.tag_artifacts(built_components_in_batch)

        session.commit()
    elif (any([c.state != koji.BUILD_STATES['BUILDING']
          for c in unbuilt_components_in_batch])):
        # We are not in the middle of the batch building and
        # we have some unbuilt components in this batch. We might hit the
        # concurrent builds threshold in previous call of continue_batch_build
        # done in repos.py:done(...), but because we have just finished one
        # build, try to call continue_batch_build again so in case we hit the
        # threshold previously, we will submit another build from this batch.
        builder = module_build_service.builder.GenericBuilder.create_from_module(
            session, parent, config)
        further_work += module_build_service.utils.continue_batch_build(
            config, parent, session, builder)
    return further_work


def complete(config, session, msg):
    return _finalize(config, session, msg, state=koji.BUILD_STATES['COMPLETE'])


def failed(config, session, msg):
    return _finalize(config, session, msg, state=koji.BUILD_STATES['FAILED'])


def canceled(config, session, msg):
    return _finalize(config, session, msg, state=koji.BUILD_STATES['CANCELED'])
