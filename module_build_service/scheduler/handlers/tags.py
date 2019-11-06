# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
""" Handlers for repo change events on the message bus. """

import logging
import koji
from module_build_service import conf, models, log
from module_build_service.db_session import db_session
from module_build_service.builder import GenericBuilder
from module_build_service.scheduler import events

logging.basicConfig(level=logging.DEBUG)


def tagged(msg_id, tag_name, build_name, build_nvr):
    """Called whenever koji tags a build to tag.

    :param str msg_id: the original id of the message being handled which is
        received from the message bus.
    :param str tag_name: the tag name applied.
    :param str build_name: name of the tagged build.
    :param str build_nvr: nvr of the tagged build.
    """
    if conf.system not in ("koji", "test"):
        return []

    # Find our ModuleBuild associated with this tagged artifact.
    module_build = models.ModuleBuild.get_by_tag(db_session, tag_name)
    if not module_build:
        log.debug("No module build found associated with koji tag %r", tag_name)
        return

    # Find tagged component.
    component = models.ComponentBuild.from_component_nvr(
        db_session, build_nvr, module_build.id)
    if not component:
        log.error("No component %s in module %r", build_nvr, module_build)
        return

    log.info("Saw relevant component tag of %r from %r.", component.nvr, msg_id)

    # Mark the component as tagged
    if tag_name.endswith("-build"):
        component.tagged = True
    else:
        component.tagged_in_final = True
    db_session.commit()

    if any(c.is_unbuilt for c in module_build.current_batch()):
        log.info(
            "Not regenerating repo for tag %s, there are still building components in a batch",
            tag_name,
        )
        return []

    further_work = []

    # If all components are tagged, start newRepo task.
    if not any(c.is_completed and not c.is_tagged for c in module_build.up_to_current_batch()):
        builder = GenericBuilder.create_from_module(
            db_session, module_build, conf)

        if any(c.is_unbuilt for c in module_build.component_builds):
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
            further_work += [{
                "msg_id": "components::_finalize: fake msg",
                "event": events.KOJI_REPO_CHANGE,
                "repo_tag": builder.module_build_tag["name"],
            }]
        db_session.commit()

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
