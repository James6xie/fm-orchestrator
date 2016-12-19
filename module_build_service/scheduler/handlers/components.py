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

from module_build_service import models, log

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

    if state != koji.BUILD_STATES['COMPLETE']:
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
    if (component_build.package == 'module-build-macros'
            and state != koji.BUILD_STATES['COMPLETE']):
        parent.transition(config, state=models.BUILD_STATES['failed'],
                            state_reason=state_reason)
        session.commit()
        return

    # If there are no other components still building in a batch,
    # we can tag all successfully built components in the batch.
    unbuilt_components_in_batch = [
        c for c in parent.current_batch()
        if c.state == koji.BUILD_STATES['BUILDING'] or not c.state
    ]
    if not unbuilt_components_in_batch:
        built_components_in_batch = [
            c.nvr for c in parent.current_batch()
            if c.state == koji.BUILD_STATES['COMPLETE']
        ]

        module_name = parent.name
        tag = parent.koji_tag
        builder = module_build_service.builder.GenericBuilder.create(
            parent.owner, module_name, config.system, config, tag_name=tag)

        try:
            groups = {
                'build': parent.resolve_profiles(session, 'buildroot'),
                'srpm-build': parent.resolve_profiles(session, 'srpm-buildroot'),
            }
        except ValueError:
            reason = "Failed to gather buildroot groups from SCM."
            log.exception(reason)
            parent.transition(config, state=models.BUILD_STATES["failed"],
                              state_reason=reason)
            session.commit()
            raise

        builder.buildroot_connect(groups)
        # tag && add to srpm-build group if neccessary
        install = bool(component_build.package == 'module-build-macros')
        builder.buildroot_add_artifacts(built_components_in_batch, install=install)
        builder.tag_artifacts(built_components_in_batch)
        session.commit()


def complete(config, session, msg):
    return _finalize(config, session, msg, state=koji.BUILD_STATES['COMPLETE'])

def failed(config, session, msg):
    return _finalize(config, session, msg, state=koji.BUILD_STATES['FAILED'])

def canceled(config, session, msg):
    return _finalize(config, session, msg, state=koji.BUILD_STATES['CANCELED'])
