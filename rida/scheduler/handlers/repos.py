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

""" Handlers for repo change events on the message bus. """

import rida.builder
import rida.database
import rida.pdc
import logging
import koji

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger(__name__)


def done(config, session, msg):
    """ Called whenever koji rebuilds a repo, any repo. """

    # First, find our ModuleBuild associated with this repo, if any.
    tag = msg['msg']['tag'].strip('-build')
    module_build = rida.database.ModuleBuild.get_active_by_koji_tag(
        session, koji_tag=tag)
    if not module_build:
        log.info("No module build found associated with koji tag %r" % tag)
        return

    unbuilt_components = (
        component_build for component_build in module_build.component_builds
        if component_build.state is None
    )

    builder = rida.builder.KojiModuleBuilder(module_build.name, config, tag_name=tag)
    builder.buildroot_resume()

    for component_build in unbuilt_components:
        component_build.state = koji.BUILD_STATES['BUILDING']
        log.debug("Using scmurl=%s for package=%s" % (
            component_build.scmurl,
            component_build.package,
        ))
        component_build.task_id = builder.build(
            artifact=component_build.package,
            source=component_build.scmurl,
        )
    session.commit()
