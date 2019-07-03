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
import logging
import koji
from module_build_service import models, log, messaging

logging.basicConfig(level=logging.DEBUG)


def tagged(config, session, msg):
    """ Called whenever koji tags a build to tag. """
    if config.system not in ("koji", "test"):
        return []

    # Find our ModuleBuild associated with this tagged artifact.
    tag = msg.tag
    module_build = models.ModuleBuild.from_tag_change_event(session, msg)
    if not module_build:
        log.debug("No module build found associated with koji tag %r" % tag)
        return

    # Find tagged component.
    component = models.ComponentBuild.from_component_nvr(session, msg.nvr, module_build.id)
    if not component:
        log.error("No component %s in module %r", msg.nvr, module_build)
        return

    log.info("Saw relevant component tag of %r from %r." % (component.nvr, msg.msg_id))

    # Mark the component as tagged
    if tag.endswith("-build"):
        component.tagged = True
    else:
        component.tagged_in_final = True
    session.commit()

    unbuilt_components_in_batch = [
        c for c in module_build.current_batch()
        if c.state == koji.BUILD_STATES["BUILDING"] or not c.state
    ]
    if unbuilt_components_in_batch:
        log.info(
            "Not regenerating repo for tag %s, there are still building components in a batch",
            tag,
        )
        return []

    # Get the list of untagged components in current/previous batches which
    # have been built successfully.
    untagged_components = [
        c for c in module_build.up_to_current_batch()
        if (not c.tagged or (not c.tagged_in_final and not c.build_time_only))
        and c.state == koji.BUILD_STATES["COMPLETE"]
    ]

    further_work = []

    # If all components are tagged, start newRepo task.
    if not untagged_components:
        builder = module_build_service.builder.GenericBuilder.create_from_module(
            session, module_build, config)

        unbuilt_components = [
            c for c in module_build.component_builds
            if c.state == koji.BUILD_STATES["BUILDING"] or not c.state
        ]
        if unbuilt_components:
            if not _is_new_repo_generating(module_build, builder.koji_session):
                repo_tag = builder.module_build_tag["name"]
                log.info("All components in batch tagged, regenerating repo for tag %s", repo_tag)
                task_id = builder.koji_session.newRepo(repo_tag)
                module_build.new_repo_task_id = task_id
            else:
                log.info(
                    "newRepo task %s for %r already in progress, not starting another one",
                    str(module_build.new_repo_task_id), module_build,
                )
        else:
            # In case this is the last batch, we do not need to regenerate the
            # buildroot, because we will not build anything else in it. It
            # would be useless to wait for a repository we will not use anyway.
            log.info(
                "All components in module tagged and built, skipping the last repo regeneration")
            further_work += [
                messaging.KojiRepoChange(
                    "components::_finalize: fake msg", builder.module_build_tag["name"])
            ]
        session.commit()

    return further_work


def _is_new_repo_generating(module_build, koji_session):
    """ Return whether or not a new repo is already being generated. """
    if not module_build.new_repo_task_id:
        return False

    log.debug(
        'Checking status of newRepo task "%d" for %s', module_build.new_repo_task_id, module_build)
    task_info = koji_session.getTaskInfo(module_build.new_repo_task_id)

    active_koji_states = [
        koji.TASK_STATES["FREE"], koji.TASK_STATES["OPEN"], koji.TASK_STATES["ASSIGNED"]]

    return task_info["state"] in active_koji_states
