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
import time
import logging
import koji

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger()

def init(config, session, msg):
    """ Called whenever a module enters the 'init' state.

    We usually transition to this state when the modulebuild is first requested.

    All we do here is request preparation of the buildroot.
    """
    build = rida.database.ModuleBuild.from_fedmsg(session, msg)
    pdc = rida.pdc.get_pdc_client_session(config)
    # TODO do some periodical polling of variant_info since it's being created based on the same message
    #log.warn("HACK: waiting 10s for pdc")
    #time.sleep(10)
    log.debug("Getting module from pdc with following input_data=%s" % build.json())
    module_info = pdc.get_module(build.json())

    log.debug("Received module_info=%s from pdc" % module_info)

    tag = rida.pdc.get_module_tag(pdc, module_info)
    log.info("Found tag=%s for module %s-%s-%s" % (tag, build['name'], build['version'], build['release']))

    dependencies = rida.pdc.get_module_dependencies(pdc, module_info)
    builder = rida.builder.KojiModuleBuilder(build.name, config)
    builder.buildroot_add_dependency(dependencies)
    build.buildroot_task_id = builder.buildroot_prep()
    # TODO: build srpm with dist_tag macros
    # TODO submit build from srpm to koji
    # TODO: buildroot.add_artifact(build_with_dist_tags)
    # TODO: buildroot.ready(artifact=$artifact)
    build.state = "wait"  # Wait for the buildroot to be ready.
    log.debug("Done with init")


def build(config, session, msg):
    """ Called whenever a module enters the "build" state.

    We usually transition to this state once the buildroot is ready.

    All we do here is kick off builds of all our components.
    """
    module_build = rida.database.ModuleBuild.from_fedmsg(session, msg)
    for component_build in module_build.component_builds:
        scmurl = "{dist_git}/rpms/{package}?#{gitref}".format(
            dist_git=config.dist_git_url,
            package=component_build.package,
            gitref=component_build.gitref,  # This is the update stream
        )
        artifact_name = 'TODO'
        component_build.task = builder.build(artifact_name, scmurl)
        component_build.state = koji.BUILD_STATES['BUILDING']

    build.state = "build"  # Now wait for all of those to finish.
