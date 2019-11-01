# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
""" Handlers for koji component build events on the message bus. """

import logging
import koji
import module_build_service.builder

from module_build_service.builder.KojiModuleBuilder import KojiModuleBuilder
from module_build_service.utils.general import mmd_to_str
from module_build_service import models, log, messaging
from module_build_service.db_session import db_session

logging.basicConfig(level=logging.DEBUG)


def _finalize(config, msg, state):
    """ Called whenever a koji build completes or fails. """

    # First, find our ModuleBuild associated with this component, if any.
    component_build = models.ComponentBuild.from_component_event(db_session, msg)
    try:
        nvr = "{}-{}-{}".format(msg.build_name, msg.build_version, msg.build_release)
    except KeyError:
        nvr = None

    if not component_build:
        log.debug("We have no record of %s" % nvr)
        return

    log.info("Saw relevant component build of %r from %r." % (nvr, msg.msg_id))

    if msg.state_reason:
        state_reason = msg.state_reason
    elif state != koji.BUILD_STATES["COMPLETE"]:
        state_reason = "Failed to build artifact %s in Koji" % (msg.build_name)
    else:
        state_reason = ""

    # Mark the state in the db.
    component_build.state = state
    component_build.nvr = nvr
    component_build.state_reason = state_reason
    db_session.commit()

    parent = component_build.module_build

    # If the macro build failed, then the module is doomed.
    if component_build.package == "module-build-macros" and state != koji.BUILD_STATES["COMPLETE"]:
        parent.transition(
            db_session,
            config,
            state=models.BUILD_STATES["failed"],
            state_reason=state_reason,
            failure_type="user",
        )
        db_session.commit()
        return

    if (
        component_build.buildonly
        and config.system in ["koji", "test"]
        and state == koji.BUILD_STATES["COMPLETE"]
    ):
        koji_session = KojiModuleBuilder.get_session(config)
        rpms = koji_session.listBuildRPMs(component_build.nvr)
        mmd = parent.mmd()
        for artifact in rpms:
            mmd.add_rpm_filter(artifact["name"])
        parent.modulemd = mmd_to_str(mmd)
        db_session.commit()

    further_work = []

    parent_current_batch = parent.current_batch()

    # If there are no other components still building in a batch,
    # we can tag all successfully built components in the batch.
    unbuilt_components_in_batch = [
        c for c in parent_current_batch
        if c.is_waiting_for_build or c.is_building
    ]
    if not unbuilt_components_in_batch:
        failed_components_in_batch = [c for c in parent_current_batch if c.is_unsuccessful]
        built_components_in_batch = [c for c in parent_current_batch if c.is_completed]

        builder = module_build_service.builder.GenericBuilder.create_from_module(
            db_session, parent, config
        )

        if failed_components_in_batch:
            log.info(
                "Batch done, but not tagging because of failed component builds. Will "
                'transition the module to "failed"'
            )
            state_reason = "Component(s) {} failed to build.".format(
                ", ".join(c.package for c in failed_components_in_batch))
            parent.transition(
                db_session,
                config,
                state=models.BUILD_STATES["failed"],
                state_reason=state_reason,
                failure_type="user",
            )
            db_session.commit()
            return []
        elif not built_components_in_batch:
            # If there are no successfully built components in a batch, there is nothing to tag.
            # The repository won't be regenerated in this case and therefore we generate fake repo
            # change message here.
            log.info("Batch done. No component to tag")
            further_work += [
                messaging.KojiRepoChange(
                    "components::_finalize: fake msg", builder.module_build_tag["name"])
            ]
        else:
            built_component_nvrs_in_batch = [c.nvr for c in built_components_in_batch]
            # tag && add to srpm-build group if neccessary
            log.info(
                "Batch done.  Tagging %i component(s) in the build tag."
                % len(built_component_nvrs_in_batch)
            )
            log.debug("%r" % built_component_nvrs_in_batch)
            # TODO: install=component_build.build_time_only works here because module-build-macros
            # is alone in its batch and the only component with build_time_only set. All other
            # batches will have install=False. If we expand to have batches with a mix of
            # build_time_only and not components, then this logic will need to change.
            builder.buildroot_add_artifacts(
                built_component_nvrs_in_batch, install=component_build.build_time_only)

            # Do not tag packages which only belong to the build tag to the dest tag
            component_nvrs_to_tag_in_dest = [
                c.nvr for c in built_components_in_batch
                if c.build_time_only is False
            ]
            log.info(
                "Tagging %i component(s) in the dest tag." % len(component_nvrs_to_tag_in_dest))
            if component_nvrs_to_tag_in_dest:
                builder.tag_artifacts(component_nvrs_to_tag_in_dest)

        db_session.commit()

    elif any(not c.is_building for c in unbuilt_components_in_batch):
        # We are not in the middle of the batch building and
        # we have some unbuilt components in this batch. We might hit the
        # concurrent builds threshold in previous call of continue_batch_build
        # done in repos.py:done(...), but because we have just finished one
        # build, try to call continue_batch_build again so in case we hit the
        # threshold previously, we will submit another build from this batch.
        builder = module_build_service.builder.GenericBuilder.create_from_module(
            db_session, parent, config)
        further_work += module_build_service.utils.continue_batch_build(
            config, parent, builder)

    return further_work


def complete(config, msg):
    return _finalize(config, msg, state=koji.BUILD_STATES["COMPLETE"])


def failed(config, msg):
    return _finalize(config, msg, state=koji.BUILD_STATES["FAILED"])


def canceled(config, msg):
    return _finalize(config, msg, state=koji.BUILD_STATES["CANCELED"])
