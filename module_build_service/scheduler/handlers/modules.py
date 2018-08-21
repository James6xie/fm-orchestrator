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

""" Handlers for module change events on the message bus. """

from module_build_service import conf, models, log, build_logs
import module_build_service.builder
import module_build_service.resolver
import module_build_service.utils
import module_build_service.messaging
from module_build_service.utils import (
    attempt_to_reuse_all_components,
    record_component_builds,
    get_rpm_release,
    generate_koji_tag,
    record_filtered_rpms)
from module_build_service.errors import UnprocessableEntity, Forbidden, ValidationError

from requests.exceptions import ConnectionError

import koji

import logging
import os
import time

logging.basicConfig(level=logging.DEBUG)


def get_artifact_from_srpm(srpm_path):
    return os.path.basename(srpm_path).replace(".src.rpm", "")


def failed(config, session, msg):
    """
    Called whenever a module enters the 'failed' state.

    We cancel all the remaining component builds of a module
    and stop the building.
    """

    build = models.ModuleBuild.from_module_event(session, msg)

    module_info = build.json()
    if module_info['state'] != msg.module_build_state:
        log.warn("Note that retrieved module state %r "
                 "doesn't match message module state %r" % (
                     module_info['state'], msg.module_build_state))
        # This is ok.. it's a race condition we can ignore.
        pass

    unbuilt_components = [
        c for c in build.component_builds
        if (c.state != koji.BUILD_STATES['COMPLETE'] and
            c.state != koji.BUILD_STATES["FAILED"])
    ]

    if build.koji_tag:
        builder = module_build_service.builder.GenericBuilder.create_from_module(
            session, build, config)

        if build.new_repo_task_id:
            builder.cancel_build(build.new_repo_task_id)

        for component in unbuilt_components:
            if component.task_id:
                builder.cancel_build(component.task_id)
            component.state = koji.BUILD_STATES['FAILED']
            component.state_reason = build.state_reason
            session.add(component)

        # Tell the external buildsystem to wrap up
        builder.finalize()
    else:
        # Do not overwrite state_reason set by Frontend if any.
        if not build.state_reason:
            reason = "Missing koji tag. Assuming previously failed module lookup."
            log.error(reason)
            build.transition(config, state="failed", state_reason=reason)
            session.commit()
            return

    # Don't transition it again if it's already been transitioned
    if build.state != models.BUILD_STATES["failed"]:
        build.transition(config, state="failed")

    session.commit()

    build_logs.stop(build)
    module_build_service.builder.GenericBuilder.clear_cache(build)


def done(config, session, msg):
    """Called whenever a module enters the 'done' state.

    We currently don't do anything useful, so moving to ready.
    Otherwise the done -> ready state should happen when all
    dependent modules were re-built, at least that's the current plan.
    """
    build = models.ModuleBuild.from_module_event(session, msg)
    module_info = build.json()
    if module_info['state'] != msg.module_build_state:
        log.warn("Note that retrieved module state %r "
                 "doesn't match message module state %r" % (
                     module_info['state'], msg.module_build_state))
        # This is ok.. it's a race condition we can ignore.
        pass

    builder = module_build_service.builder.GenericBuilder.create_from_module(
        session, build, config)

    # Tell the external buildsystem to wrap up (CG import, createrepo, etc.)
    builder.finalize()

    build.transition(config, state="ready")
    session.commit()

    build_logs.stop(build)
    module_build_service.builder.GenericBuilder.clear_cache(build)


def init(config, session, msg):
    """ Called whenever a module enters the 'init' state."""
    # Sleep for a few seconds to make sure the module in the database is committed
    # TODO: Remove this once messaging is implemented in SQLAlchemy hooks
    for i in range(3):
        build = models.ModuleBuild.from_module_event(session, msg)
        if build:
            break
        time.sleep(1)

    try:
        mmd = build.mmd()
        record_component_builds(mmd, build, session=session)
        mmd = record_filtered_rpms(mmd)
        build.modulemd = mmd.dumps()
        build.transition(conf, models.BUILD_STATES["wait"])
    # Catch custom exceptions that we can expose to the user
    except (UnprocessableEntity, Forbidden, ValidationError, RuntimeError) as e:
        # Rollback changes underway
        session.rollback()
        build.transition(conf, models.BUILD_STATES["failed"], state_reason=str(e))
    except Exception as e:
        log.exception(str(e))
        # Rollback changes underway
        session.rollback()
        msg = "An unknown error occurred while validating the modulemd"
        build.transition(conf, models.BUILD_STATES["failed"], state_reason=msg)
    finally:
        session.add(build)
        session.commit()


def wait(config, session, msg):
    """ Called whenever a module enters the 'wait' state.

    We transition to this state shortly after a modulebuild is first requested.

    All we do here is request preparation of the buildroot.
    The kicking off of individual component builds is handled elsewhere,
    in module_build_service.schedulers.handlers.repos.
    """

    # Wait for the db on the frontend to catch up to the message, otherwise the
    # xmd information won't be present when we need it.
    # See https://pagure.io/fm-orchestrator/issue/386
    @module_build_service.utils.retry(interval=10, timeout=120, wait_on=RuntimeError)
    def _get_build_containing_xmd_for_mbs():
        build = models.ModuleBuild.from_module_event(session, msg)
        if 'mbs' in build.mmd().get_xmd():
            return build
        session.expire(build)
        raise RuntimeError("{!r} doesn't contain xmd information for MBS."
                           .format(build))

    build = _get_build_containing_xmd_for_mbs()
    build_logs.start(build)

    log.info("Found build=%r from message" % build)
    log.info("%r", build.modulemd)

    if build.state != msg.module_build_state:
        log.warn("Note that retrieved module state %r "
                 "doesn't match message module state %r" % (
                     build.state, msg.module_build_state))
        # This is ok.. it's a race condition we can ignore.
        pass

    tag = None
    dependencies = []

    resolver = module_build_service.resolver.GenericResolver.create(config)

    @module_build_service.utils.retry(
        interval=10, timeout=120,
        wait_on=(ValueError, RuntimeError, ConnectionError))
    def _get_deps_and_tag():
        """
        Private method to get the dependencies and koji tag of a module we
        are going to build. We use private method here to allow "retry"
        on failure.
        """
        cg_build_koji_tag = conf.koji_cg_default_build_tag
        if conf.system not in ['koji', 'test']:
            # In case of non-koji backend, we want to get the dependencies
            # of the local module build based on ModuleMetadata, because the
            # local build is not stored in the external MBS and therefore we
            # cannot query it using the `query` as for Koji below.
            dependencies = resolver.get_module_build_dependencies(
                mmd=build.mmd(), strict=True).keys()

            # We also don't want to get the tag name from the MBS, but just
            # generate it locally instead.
            tag = '-'.join(['module', build.name, build.stream, build.version])
        else:
            # For Koji backend, query for the module we are going to
            # build to get the koji_tag and deps from it.
            nsvc = ':'.join([build.name, build.stream, build.version])
            log.info("Getting deps for %s" % (nsvc))
            deps_dict = resolver.get_module_build_dependencies(
                build.name, build.stream, build.version, build.context, strict=True)
            dependencies = set(deps_dict.keys())

            # Find out the name of Koji tag to which the module's Content
            # Generator build should be tagged once the build finishes.
            module_names_streams = {mmd.get_name(): mmd.get_stream()
                                    for mmd in deps_dict.values()}
            for base_module_name in conf.base_module_names:
                if base_module_name in module_names_streams:
                    cg_build_koji_tag = conf.koji_cg_build_tag_template.format(
                        module_names_streams[base_module_name])
                    break

            log.info('Getting tag for {0}'.format(nsvc))
            tag = generate_koji_tag(build.name, build.stream, build.version, build.context)

        return dependencies, tag, cg_build_koji_tag

    try:
        dependencies, tag, cg_build_koji_tag = _get_deps_and_tag()
    except ValueError:
        reason = "Failed to get module info from MBS. Max retries reached."
        log.exception(reason)
        build.transition(config, state="failed", state_reason=reason)
        session.commit()
        raise

    log.debug("Found tag=%s for module %r" % (tag, build))
    # Hang on to this information for later.  We need to know which build is
    # associated with which koji tag, so that when their repos are regenerated
    # in koji we can figure out which for which module build that event is
    # relevant.
    log.debug("Assigning koji tag=%s to module build" % tag)
    build.koji_tag = tag

    log.debug("Assigning Content Generator build koji tag=%s to module "
              "build", cg_build_koji_tag)
    build.cg_build_koji_tag = cg_build_koji_tag

    builder = module_build_service.builder.GenericBuilder.create_from_module(
        session, build, config)

    log.debug("Adding dependencies %s into buildroot for module %s" % (dependencies, ':'.join(
        [build.name, build.stream, build.version])))
    builder.buildroot_add_repos(dependencies)

    if not build.component_builds:
        log.info("There are no components in module %r, skipping build" % build)
        build.transition(config, state="build")
        session.add(build)
        session.commit()
        # Return a KojiRepoChange message so that the build can be transitioned to done
        # in the repos handler
        return [module_build_service.messaging.KojiRepoChange(
            'handlers.modules.wait: fake msg', builder.module_build_tag['name'])]

    # If all components in module build will be reused, we don't have to build
    # module-build-macros, because there won't be any build done.
    if attempt_to_reuse_all_components(builder, session, build):
        log.info("All components have been reused for module %r, "
                 "skipping build" % build)
        build.transition(config, state="build")
        session.add(build)
        session.commit()
        return []

    log.debug("Starting build batch 1")
    build.batch = 1
    session.commit()

    artifact_name = "module-build-macros"

    component_build = models.ComponentBuild.from_component_name(
        session, artifact_name, build.id)
    further_work = []
    srpm = builder.get_disttag_srpm(
        disttag=".%s" % get_rpm_release(build),
        module_build=build)
    if not component_build:
        component_build = models.ComponentBuild(
            module_id=build.id,
            package=artifact_name,
            format="rpms",
            scmurl=srpm,
            batch=1,
            build_time_only=True
        )
        session.add(component_build)
        # Commit and refresh so that the SQLAlchemy relationships are available
        session.commit()
        session.refresh(component_build)
        msgs = builder.recover_orphaned_artifact(component_build)
        if msgs:
            log.info('Found an existing module-build-macros build')
            further_work += msgs
        # There was no existing artifact found, so lets submit the build instead
        else:
            task_id, state, reason, nvr = builder.build(artifact_name=artifact_name, source=srpm)
            component_build.task_id = task_id
            component_build.state = state
            component_build.reason = reason
            component_build.nvr = nvr
    elif component_build.state != koji.BUILD_STATES['COMPLETE']:
        # It's possible that the build succeeded in the builder but some other step failed which
        # caused module-build-macros to be marked as failed in MBS, so check to see if it exists
        # first
        msgs = builder.recover_orphaned_artifact(component_build)
        if msgs:
            log.info('Found an existing module-build-macros build')
            further_work += msgs
        else:
            task_id, state, reason, nvr = builder.build(artifact_name=artifact_name, source=srpm)
            component_build.task_id = task_id
            component_build.state = state
            component_build.reason = reason
            component_build.nvr = nvr

    session.add(component_build)
    build.transition(config, state="build")
    session.add(build)
    session.commit()

    # We always have to regenerate the repository.
    if config.system == "koji":
        log.info("Regenerating the repository")
        task_id = builder.koji_session.newRepo(
            builder.module_build_tag['name'])
        build.new_repo_task_id = task_id
        session.commit()
    else:
        further_work.append(module_build_service.messaging.KojiRepoChange(
            'fake msg', builder.module_build_tag['name']))
    return further_work
