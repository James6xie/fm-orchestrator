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
import os

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger(__name__)


def get_rpm_release_from_tag(tag):
    return tag.replace("-", "_")

def get_artifact_from_srpm(srpm_path):
    return os.path.basename(srpm_path).replace(".src.rpm", "")

def wait(config, session, msg):
    """ Called whenever a module enters the 'wait' state.

    We transition to this state shortly after a modulebuild is first requested.

    All we do here is request preparation of the buildroot.
    The kicking off of individual component builds is handled elsewhere,
    in rida.schedulers.handlers.repos.
    """
    build = rida.database.ModuleBuild.from_module_event(session, msg)
    log.info("Found build=%r from message" % build)

    module_info = build.json()
    if module_info['state'] != msg['msg']['state']:
        log.warn("Note that retrieved module state %r "
                 "doesn't match message module state %r" % (
                     module_info['state'], msg['msg']['state']))
        # This is ok.. it's a race condition we can ignore.
        pass

    pdc_session = rida.pdc.get_pdc_client_session(config)
    tag = rida.pdc.get_module_tag(pdc_session, module_info, strict=True)
    log.info("Found tag=%s for module %r" % (tag, build))

    # Hang on to this information for later.  We need to know which build is
    # associated with which koji tag, so that when their repos are regenerated
    # in koji we can figure out which for which module build that event is
    # relevant.
    log.debug("Assigning koji tag=%s to module build" % tag)
    build.koji_tag = tag

    dependencies = rida.pdc.get_module_build_dependencies(pdc_session, module_info, strict=True)
    builder = rida.builder.KojiModuleBuilder(build.name, config, tag_name=tag)
    build.buildroot_task_id = builder.buildroot_prep()
    log.debug("Adding dependencies %s into buildroot for module %s" % (dependencies, module_info))
    builder.buildroot_add_dependency(dependencies)
    # inject dist-tag into buildroot
    srpm = builder.get_disttag_srpm(disttag=".%s" % get_rpm_release_from_tag(tag))
    task_id = builder.build(artifact_name="module-build-macros", source=srpm)

    # TODO -- this has to go eventually.. otherwise, we can only build one
    # module at a time and that just won't scale.
    builder.wait_task(task_id)
    # TODO -- do cleanup if this fails

    artifact = get_artifact_from_srpm(srpm)
    builder.buildroot_add_artifacts([artifact,], install=True) # tag && add to srpm-build group
    builder.buildroot_ready(artifacts=[artifact,])

    build.transition(config, state="build")  # Wait for the buildroot to be ready.
    session.commit()
