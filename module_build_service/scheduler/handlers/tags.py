# -*- coding: utf-8 -*-
# Copyright (c) 2017  Red Hat, Inc.
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
# Written by Jan Kaluza <jkaluza@redhat.com>

""" Handlers for repo change events on the message bus. """

import module_build_service.builder
import module_build_service.pdc
import logging
import koji
from module_build_service import models, log
from module_build_service.utils import start_next_batch_build

logging.basicConfig(level=logging.DEBUG)


def tagged(config, session, msg):
    """ Called whenever koji tags a build to tag. """

    if not config.system == "koji":
        return []

    # Find our ModuleBuild associated with this tagged artifact.
    tag = msg.tag
    if not tag.endswith('-build'):
        log.debug("Tag %r does not end with '-build' suffix, ignoring" % tag)
        return
    module_build = models.ModuleBuild.from_tag_change_event(session, msg)
    if not module_build:
        log.debug("No module build found associated with koji tag %r" % tag)
        return

    # Find tagged component.
    component = models.ComponentBuild.from_component_name(
        session, msg.artifact, module_build.id)
    if not component:
        log.error("No component %s in module %r", msg.artifact, module_build)
        return

    log.info("Saw relevant component tag of %r from %r." % (component.nvr,
                                                            msg.msg_id))

    # Mark the component as tagged
    component.tagged = True
    session.commit()

    unbuilt_components_in_batch = [
        c for c in module_build.current_batch()
        if c.state == koji.BUILD_STATES['BUILDING'] or not c.state
    ]
    if unbuilt_components_in_batch:
        log.info("Not regenerating repo for tag %s, there are still "
                 "building components in a batch", tag)
        return []

    # Get the list of untagged components in current/previous batches which
    # have been built successfully.
    untagged_components = [
        c for c in module_build.up_to_current_batch()
        if not c.tagged and c.state == koji.BUILD_STATES['COMPLETE']
    ]

    # If all components are tagged, start newRepo task.
    if not untagged_components:
        log.info("All components tagged, regenerating repo for tag %s", tag)
        builder = module_build_service.builder.GenericBuilder.create_from_module(
            session, module_build, config)
        task_id = builder.koji_session.newRepo(tag)
        module_build.new_repo_task_id = task_id
        session.commit()

    return []
