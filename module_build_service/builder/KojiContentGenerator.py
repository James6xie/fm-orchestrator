# -*- coding: utf-8 -*-
# Copyright (c) 2017  Red Hat, Inc.
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
# Written by Stanislav Ochotnicky <sochotnicky@redhat.com>


import calendar
import logging
import platform
import hashlib

import koji

import module_build_service
from module_build_service import log
from module_build_service.builder.KojiModuleBuilder import KojiModuleBuilder

logging.basicConfig(level=logging.DEBUG)


class KojiContentGenerator(object):
    """ Class for handling content generator imports of module builds into Koji """

    def __init__(self, module, config):
        """
        :param owner: a string representing who kicked off the builds
        :param module: module_build_service.models.ModuleBuild instance.
        :param config: module_build_service.config.Config instance
        """
        self.owner = module.owner
        self.module = module
        self.module_name = module.name
        self.mmd = module.modulemd
        self.config = config


    def __repr__(self):
        return "<KojiContentGenerator module: %s>" % (self.module_name)

    def _koji_rpms_in_tag(self, tag):
        """ Return the list of koji rpms in a tag. """
        log.debug("Listing rpms in koji tag %s", tag)
        session = KojiModuleBuilder.get_session(self.config, self.owner)

        try:
            rpms, builds = session.listTaggedRPMS(tag, latest=True)
        except koji.GenericError as e:
            log.exception("Failed to list rpms in tag %r", tag)
            # If the tag doesn't exist.. then there are no rpms in that tag.
            return []

        # Extract some srpm-level info from the build attach it to each rpm
        builds = {build['build_id']: build for build in builds}
        for rpm in rpms:
            idx = rpm['build_id']
            rpm['srpm_name'] = builds[idx]['name']
            rpm['srpm_nevra'] = builds[idx]['nvr']

        return rpms

    def _get_build(self):
        ret = {}
        ret['name'] = self.module.name
        ret['version'] = self.module.stream
        ret['release'] = self.module.version
        ret['source'] = self.module.scmurl
        ret['start_time'] = calendar.timegm(
            self.module.time_submitted.utctimetuple())
        ret['end_time'] = calendar.timegm(
            self.module.time_completed.utctimetuple())
        ret['extra'] = {
            "typeinfo": {
                "modulemd": {
                    "module_build_service_id": self.module.id,
                    "modulemd_str": self.module.modulemd
                }
            }
        }
        return ret

    def _get_buildroot(self):
        import pkg_resources
        version = pkg_resources.get_distribution("module-build-service").version
        distro = platform.linux_distribution()
        ret = {
            "id": 1,
            "host": {
                "arch": platform.machine(),
                'os': "%s %s" % (distro[0], distro[1])
            },
            "content_generator": {
                "name": "module-build-service",
                "version": version
            },
            "container": {
                "arch": platform.machine(),
                "type": "none"
            },
            "components": [],
            "tools": []
        }
        return ret



    def _get_output(self):
        ret = []
        rpms = self._koji_rpms_in_tag(self.module.koji_tag)
        components = []
        for rpm in rpms:
            components.append(
                {
                    "name": rpm["name"],
                    "version": rpm["version"],
                    "release": rpm["release"],
                    "arch": rpm["arch"],
                    "epoch": rpm["epoch"],
                    "sigmd5": rpm["payloadhash"],
                    "type": "rpm"
                }
            )

        ret.append(
            {
                'buildroot_id': 1,
                'arch': "noarch",
                'type': 'modulemd',
                'filesize': len(self.mmd),
                'checksum_type': 'md5',
                'checksum': hashlib.md5(self.mmd).hexdigest(),
                'filename': 'modulemd.yaml',
                'components': components
            }
        )
        # TODO add logs output
        return ret


    def _get_content_generator_metadata(self):
        ret = {
            "metadata_version": 0,
            "buildroots": [self._get_buildroot()],
            "build": self._get_build(),
            "output": self._get_output()
        }

        return ret

    def koji_import(self):
        session = KojiModuleBuilder.get_session(self.config, self.owner)

        metadata = self._get_content_generator_metadata()
