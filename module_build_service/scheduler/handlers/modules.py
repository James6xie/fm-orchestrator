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

import logging
import os

logging.basicConfig(level=logging.DEBUG)


def get_rpm_release_from_tag(tag):
    return tag.replace("-", "_")


def get_artifact_from_srpm(srpm_path):
    return os.path.basename(srpm_path).replace(".src.rpm", "")

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
    build = models.ModuleBuild.from_module_event(session, msg)
    log.info("Found build=%r from message" % build)

    module_info = build.json()
    if module_info['state'] != msg.module_build_state:
        log.warn("Note that retrieved module state %r "
                 "doesn't match message module state %r" % (
                     module_info['state'], msg.module_build_state))
        # This is ok.. it's a race condition we can ignore.
        pass

    tag = None
    dependencies = None

    if conf.system == "mock":
        # In case of mock, we do not try to get anything from pdc,
        # just generate our own koji_tag to identify the module in messages.
        tag = '-'.join(['module', module_info['name'],
            str(module_info['stream']), str(module_info['version'])])
        # TODO: Dependencies
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
            log.exception("Failed to get module info from PDC. Max retries reached.")
            build.transition(config, state="failed")
            session.commit()
            raise

    log.debug("Found tag=%s for module %r" % (tag, build))
    # Hang on to this information for later.  We need to know which build is
    # associated with which koji tag, so that when their repos are regenerated
    # in koji we can figure out which for which module build that event is
    # relevant.
    log.debug("Assigning koji tag=%s to module build" % tag)
    build.koji_tag = tag

    builder = module_build_service.builder.GenericBuilder.create(
        build.owner, build.name, config.system, config, tag_name=tag)
    build.buildroot_task_id = builder.buildroot_connect()
    log.debug("Adding dependencies %s into buildroot for module %s" % (dependencies, module_info))
    builder.buildroot_add_repos(dependencies)
    # inject dist-tag into buildroot
    srpm = builder.get_disttag_srpm(disttag=".%s" % get_rpm_release_from_tag(tag))

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
        return [module_build_service.messaging.KojiRepoChange('fake msg', build.koji_tag)]
