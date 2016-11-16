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

    # First, find our ModuleBuild associated with this repo, if any.
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

    if component_build.package == 'module-build-macros':
        if state != koji.BUILD_STATES['COMPLETE']:
            # If the macro build failed, then the module is doomed.
            parent.transition(config, state=models.BUILD_STATES['failed'],
                              state_reason=state_reason)
            session.commit()
            return

    # TODO -- we should just do this with a koji target that feeds -build.
    # Otherwise.. if it didn't fail, then tag it.
    if state == koji.BUILD_STATES['COMPLETE']:
        # And install the macros.
        module_name = parent.name
        tag = parent.koji_tag
        builder = module_build_service.builder.GenericBuilder.create(
            parent.owner, module_name, config.system, config, tag_name=tag)
        builder.buildroot_connect()
        # tag && add to srpm-build group
        nvr = "{}-{}-{}".format(msg.build_name, msg.build_version,
                                msg.build_release)
        install = bool(component_build.package == 'module-build-macros')
        builder.buildroot_add_artifacts([nvr,], install=install)
        session.commit()


def complete(config, session, msg):
    return _finalize(config, session, msg, state=koji.BUILD_STATES['COMPLETE'])

def failed(config, session, msg):
    return _finalize(config, session, msg, state=koji.BUILD_STATES['FAILED'])

def canceled(config, session, msg):
    return _finalize(config, session, msg, state=koji.BUILD_STATES['CANCELED'])
