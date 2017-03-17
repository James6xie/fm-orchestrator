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

from module_build_service import conf, models, log
import module_build_service.builder
import module_build_service.pdc
import module_build_service.utils
import module_build_service.messaging

import koji
import hashlib

import logging
import os

logging.basicConfig(level=logging.DEBUG)


def get_rpm_release_from_mmd(mmd):
    """
    Returns the dist tag based on the modulemd metadata and MBS configuration.
    """

    dist_str = '.'.join([mmd.name, mmd.stream, str(mmd.version)])
    dist_hash = hashlib.sha1(dist_str).hexdigest()[:8]
    return conf.default_dist_tag_prefix + dist_hash

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
        if (c.state != koji.BUILD_STATES['COMPLETE']
            and c.state != koji.BUILD_STATES["FAILED"])
    ]

    groups = module_build_service.builder.GenericBuilder.default_buildroot_groups(
        session, build)

    if build.koji_tag:
        builder = module_build_service.builder.GenericBuilder.create(
            build.owner, build.name, config.system, config, tag_name=build.koji_tag,
            components=[c.package for c in build.component_builds])
        builder.buildroot_connect(groups)

        for component in unbuilt_components:
            if component.task_id:
                builder.cancel_build(component.task_id)
            component.state = koji.BUILD_STATES['FAILED']
            component.state_reason = build.state_reason
            session.add(component)
    else:
        reason = "Missing koji tag. Assuming previously failed module lookup in PDC."
        log.error(reason)
        build.transition(config, state="failed", state_reason=reason)
        session.commit()
        return

    build.transition(config, state="failed")
    session.commit()


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

    build.transition(config, state="ready")
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
        if 'mbs' in build.mmd().xmd:
            return build
        session.expire(build)
        raise RuntimeError("{!r} doesn't contain xmd information for MBS."
                           .format(build))

    build = _get_build_containing_xmd_for_mbs()
    log.info("Found build=%r from message" % build)

    module_info = build.json()
    if module_info['state'] != msg.module_build_state:
        log.warn("Note that retrieved module state %r "
                 "doesn't match message module state %r" % (
                     module_info['state'], msg.module_build_state))
        # This is ok.. it's a race condition we can ignore.
        pass

    tag = None
    dependencies = []

    if conf.system in ["mock", "copr"]:
        # In case of mock, we do not try to get anything from pdc,
        # just generate our own koji_tag to identify the module in messages.
        tag = '-'.join(['module', module_info['name'],
            str(module_info['stream']), str(module_info['version'])])


        for name, stream in build.mmd().buildrequires.items():

            pdc_session = module_build_service.pdc.get_pdc_client_session(config)
            pdc_query = {
                'name': name,
                'version': stream
            }

            @module_build_service.utils.retry(interval=10, timeout=30, wait_on=ValueError)
            def _get_module():
                log.info("Getting %s from pdc (query %r)" % (module_info['name'], pdc_query))
                return module_build_service.pdc.get_module_tag(
                    pdc_session, pdc_query, strict=True)

            try:
                dependencies.append(_get_module())
            except ValueError:
                reason = "Failed to get module info from PDC. Max retries reached."
                log.exception(reason)
                build.transition(config, state="failed", state_reason=reason)
                session.commit()
                raise
    else:
        # TODO: Move this to separate func
        pdc_session = module_build_service.pdc.get_pdc_client_session(config)
        pdc_query = {
            'name': module_info['name'],
            'version': module_info['stream'],
            'release': module_info['version'],
        }

        @module_build_service.utils.retry(interval=10, timeout=30, wait_on=ValueError)
        def _get_deps_and_tag():
            log.info("Getting %s deps from pdc (query %r)" % (module_info['name'], pdc_query))
            dependencies = module_build_service.pdc.get_module_build_dependencies(
                pdc_session, pdc_query, strict=True)
            log.info("Getting %s tag from pdc (query %r)" % (module_info['name'], pdc_query))
            tag = module_build_service.pdc.get_module_tag(
                pdc_session, pdc_query, strict=True)
            return dependencies, tag

        try:
            dependencies, tag = _get_deps_and_tag()
        except ValueError:
            reason = "Failed to get module info from PDC. Max retries reached."
            log.exception(reason)
            build.transition(config, state="failed", state_reason=reason)
            session.commit()
            raise

    groups = module_build_service.builder.GenericBuilder.default_buildroot_groups(
        session, build)

    log.debug("Found tag=%s for module %r" % (tag, build))
    # Hang on to this information for later.  We need to know which build is
    # associated with which koji tag, so that when their repos are regenerated
    # in koji we can figure out which for which module build that event is
    # relevant.
    log.debug("Assigning koji tag=%s to module build" % tag)
    build.koji_tag = tag

    builder = module_build_service.builder.GenericBuilder.create(
        build.owner, build.name, config.system, config, tag_name=tag,
        components=[c.package for c in build.component_builds])
    builder.buildroot_connect(groups)
    log.debug("Adding dependencies %s into buildroot for module %s" % (dependencies, module_info))
    builder.buildroot_add_repos(dependencies)
    # inject dist-tag into buildroot
    srpm = builder.get_disttag_srpm(disttag=".%s" % get_rpm_release_from_mmd(build.mmd()))

    log.debug("Starting build batch 1")
    build.batch = 1

    artifact_name = "module-build-macros"
    task_id, state, reason, nvr = builder.build(artifact_name=artifact_name, source=srpm)

    component_build = models.ComponentBuild(
        module_id=build.id,
        package=artifact_name,
        format="rpms",
        scmurl=srpm,
        task_id=task_id,
        state=state,
        state_reason=reason,
        nvr=nvr,
        batch=1,
    )
    session.add(component_build)
    build.transition(config, state="build")
    session.add(build)
    session.commit()

    # If this build already exists and is done, then fake the repo change event
    # back to the scheduler
    if state == koji.BUILD_STATES['COMPLETE']:
        # TODO: builder.module_build_tag only works for Koji, figure out if
        # other backends need this implemented (e.g. COPR)
        return [module_build_service.messaging.KojiRepoChange(
            'fake msg', builder.module_build_tag['name'])]

    # We don't have copr implementation finished yet, Let's fake the repo change event,
    # as if copr builds finished successfully
    if config.system == "copr":
        return [module_build_service.messaging.KojiRepoChange('fake msg', build.koji_tag)]
