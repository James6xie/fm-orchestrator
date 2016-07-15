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

import rida.builder
import rida.database
import rida.pdc
import logging
import koji

log = logging.getLogger(__name__)


def wait(config, session, msg):
    """ Called whenever a module enters the 'wait' state.

    We transition to this state shortly after a modulebuild is first requested.

    All we do here is request preparation of the buildroot.
    The kicking off of individual component builds is handled elsewhere,
    in rida.schedulers.handlers.repos.
    """
    build = rida.database.ModuleBuild.from_fedmsg(session, msg)
    pdc_session = rida.pdc.get_pdc_client_session(config)

    module_info = build.json()
    log.debug("Received module_info=%s from pdc" % module_info)
    tag = rida.pdc.get_module_tag(pdc_session, module_info)
    log.info("Found tag=%s for module %r" % (tag, build))

    dependencies = rida.pdc.get_module_dependencies(pdc_session, module_info)
    builder = rida.builder.KojiModuleBuilder(build.name, config)
    builder.buildroot_add_dependency(dependencies)
    build.buildroot_task_id = builder.buildroot_prep()
    # TODO: build srpm with dist_tag macros
    # TODO submit build from srpm to koji
    # TODO: buildroot.add_artifact(build_with_dist_tags)
    # TODO: buildroot.ready(artifact=$artifact)
    build.transition(state="build")  # Wait for the buildroot to be ready.
    session.commit()


def build(config, session, msg):
    """ Called whenever a module enters the "build" state.

    We usually transition to this state once the buildroot is ready.

    All we do here is kick off builds of all our components.
    """
    module_build = rida.database.ModuleBuild.from_fedmsg(session, msg)
    builder = rida.builder.KojiModuleBuilder(build.name, config)
    builder.buildroot_resume()

    for component_build in module_build.component_builds:
        scmurl = "{dist_git}/rpms/{package}?#{gitref}".format(
            dist_git=config.dist_git_url,
            package=component_build.package,
            gitref=component_build.gitref,  # This is the update stream
        )
        artifact_name = 'TODO'
        component_build.task = builder.build(artifact_name, scmurl)
        component_build.state = koji.BUILD_STATES['BUILDING']

    build.transition(state="build")  # Now wait for all of those to finish.
    session.commit()
