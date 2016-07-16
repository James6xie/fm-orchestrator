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

log = logging.getLogger(__name__)


def done(config, session, msg):
    """ Called whenever koji rebuilds a repo, any repo. """

    # First, find our ModuleBuild associated with this repo, if any.
    tag = msg['msg']['tag']
    module_build = rida.database.ModuleBuild.get_active_by_koji_tag(
        session, koji_tag=tag)
    if not module_build:
        log.debug("No module build found associated with koji tag %r" % tag)
        return

    unbuilt_components = (
        component_build for component_build in module_build.component_builds
        if component_build.state is None
    )

    builder = rida.builder.KojiModuleBuilder(module_build.name, config)
    builder.buildroot_resume()

    for component_build in unbuilt_components:
        scmurl = "{dist_git}/rpms/{package}?#{gitref}".format(
            dist_git=config.dist_git_url,
            package=component_build.package,
            gitref=component_build.gitref,  # This is the update stream
        )
        artifact_name = 'TODO'
        component_build.state = koji.BUILD_STATES['BUILDING']
        component_build.build_id = builder.build(artifact_name, scmurl)
    session.commit()
