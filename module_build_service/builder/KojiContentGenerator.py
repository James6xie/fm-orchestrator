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
import hashlib
import logging
import json
import os
import pkg_resources
import platform
import shutil
import subprocess
import tempfile
import time

import koji

from module_build_service import log, build_logs
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

    @staticmethod
    def parse_rpm_output(output, tags, separator=';'):
        """
        Copied from:
        https://github.com/projectatomic/atomic-reactor/blob/master/atomic_reactor/plugins/exit_koji_promote.py
        License: BSD 3-clause

        Parse output of the rpm query.
        :param output: list, decoded output (str) from the rpm subprocess
        :param tags: list, str fields used for query output
        :return: list, dicts describing each rpm package
        """ # noqa

        def field(tag):
            """
            Get a field value by name
            """
            try:
                value = fields[tags.index(tag)]
            except ValueError:
                return None

            if value == '(none)':
                return None

            return value

        components = []
        sigmarker = 'Key ID '
        for rpm in output:
            fields = rpm.rstrip('\n').split(separator)
            if len(fields) < len(tags):
                continue

            signature = field('SIGPGP:pgpsig') or field('SIGGPG:pgpsig')
            if signature:
                parts = signature.split(sigmarker, 1)
                if len(parts) > 1:
                    signature = parts[1]

            component_rpm = {
                u'type': u'rpm',
                u'name': field('NAME'),
                u'version': field('VERSION'),
                u'release': field('RELEASE'),
                u'arch': field('ARCH'),
                u'sigmd5': field('SIGMD5'),
                u'signature': signature,
            }

            # Special handling for epoch as it must be an integer or None
            epoch = field('EPOCH')
            if epoch is not None:
                epoch = int(epoch)

            component_rpm[u'epoch'] = epoch

            if component_rpm['name'] != 'gpg-pubkey':
                components.append(component_rpm)

        return components

    def __get_rpms(self):
        """
        Copied from https://github.com/projectatomic/atomic-reactor/blob/master/atomic_reactor/plugins/exit_koji_promote.py
        License: BSD 3-clause

        Build a list of installed RPMs in the format required for the
        metadata.
        """ # noqa

        tags = [
            'NAME',
            'VERSION',
            'RELEASE',
            'ARCH',
            'EPOCH',
            'SIGMD5',
            'SIGPGP:pgpsig',
            'SIGGPG:pgpsig',
        ]

        sep = ';'
        fmt = sep.join(["%%{%s}" % tag for tag in tags])
        cmd = "/bin/rpm -qa --qf '{0}\n'".format(fmt)
        try:
            # py3
            (status, output) = subprocess.getstatusoutput(cmd)
        except AttributeError:
            # py2
            with open('/dev/null', 'r+') as devnull:
                p = subprocess.Popen(cmd,
                                     shell=True,
                                     stdin=devnull,
                                     stdout=subprocess.PIPE,
                                     stderr=devnull)

                (stdout, stderr) = p.communicate()
                status = p.wait()
                output = stdout.decode()

        if status != 0:
            log.debug("%s: stderr output: %s", cmd, stderr)
            raise RuntimeError("%s: exit code %s" % (cmd, status))

        return self.parse_rpm_output(output.splitlines(), tags, separator=sep)

    def __get_tools(self):
        """Return list of tools which are important for reproducing mbs outputs"""

        tools = [u"modulemd"]
        ret = []
        for tool in tools:
            version = unicode(pkg_resources.get_distribution(tool).version)
            ret.append({u"name": tool,
                        u"version": version})
        return ret

    def _koji_rpms_in_tag(self, tag):
        """ Return the list of koji rpms in a tag. """
        log.debug("Listing rpms in koji tag %s", tag)
        session = KojiModuleBuilder.get_session(self.config, self.owner)

        try:
            rpms, builds = session.listTaggedRPMS(tag, latest=True)
        except koji.GenericError:
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
        ret[u'name'] = self.module.name
        ret[u'version'] = self.module.stream.replace("-", "_")
        ret[u'release'] = self.module.version
        ret[u'source'] = self.module.scmurl
        ret[u'start_time'] = calendar.timegm(
            self.module.time_submitted.utctimetuple())
        ret[u'end_time'] = calendar.timegm(
            self.module.time_completed.utctimetuple())
        ret[u'extra'] = {
            u"typeinfo": {
                u"module": {
                    u"module_build_service_id": self.module.id,
                    u"content_koji_tag": self.module.koji_tag,
                    u"modulemd_str": self.module.modulemd,
                    u"name": self.module.name,
                    u"stream": self.module.stream,
                    u"version": self.module.version
                }
            }
        }
        return ret

    def _get_buildroot(self):
        version = pkg_resources.get_distribution("module-build-service").version
        distro = platform.linux_distribution()
        ret = {
            u"id": 1,
            u"host": {
                u"arch": unicode(platform.machine()),
                u'os': u"%s %s" % (distro[0], distro[1])
            },
            u"content_generator": {
                u"name": u"module-build-service",
                u"version": unicode(version)
            },
            u"container": {
                u"arch": unicode(platform.machine()),
                u"type": u"none"
            },
            u"components": self.__get_rpms(),
            u"tools": self.__get_tools()
        }
        return ret

    def _get_output(self, output_path):
        ret = []
        rpms = self._koji_rpms_in_tag(self.module.koji_tag)
        components = []
        for rpm in rpms:
            components.append(
                {
                    u"name": rpm["name"],
                    u"version": rpm["version"],
                    u"release": rpm["release"],
                    u"arch": rpm["arch"],
                    u"epoch": rpm["epoch"],
                    u"sigmd5": rpm["payloadhash"],
                    u"type": u"rpm"
                }
            )

        ret.append(
            {
                u'buildroot_id': 1,
                u'arch': u'noarch',
                u'type': u'file',
                u'extra': {
                    u'typeinfo': {
                        u'module': {}
                    }
                },
                u'filesize': len(self.mmd),
                u'checksum_type': u'md5',
                u'checksum': unicode(hashlib.md5(self.mmd).hexdigest()),
                u'filename': u'modulemd.txt',
                u'components': components
            }
        )

        try:
            log_path = os.path.join(output_path, "build.log")
            with open(log_path) as build_log:
                checksum = hashlib.md5(build_log.read()).hexdigest()
            stat = os.stat(log_path)
            ret.append(
                {
                    u'buildroot_id': 1,
                    u'arch': u'noarch',
                    u'type': u'log',
                    u'filename': u'build.log',
                    u'filesize': stat.st_size,
                    u'checksum_type': u'md5',
                    u'checksum': checksum
                }
            )
        except IOError:
            # no log file?
            log.error("No module build log file found. Excluding from import")

        return ret

    def _get_content_generator_metadata(self, output_path):
        ret = {
            u"metadata_version": 0,
            u"buildroots": [self._get_buildroot()],
            u"build": self._get_build(),
            u"output": self._get_output(output_path)
        }

        return ret

    def _prepare_file_directory(self):
        """ Creates a temporary directory that will contain all the files
        mentioned in the outputs section

        Returns path to the temporary directory
        """
        prepdir = tempfile.mkdtemp(prefix="koji-cg-import")
        mmd_path = os.path.join(prepdir, "modulemd.txt")
        log.info("Writing modulemd.yaml to %r" % mmd_path)
        with open(mmd_path, "w") as mmd_f:
            mmd_f.write(self.mmd)

        log_path = os.path.join(prepdir, "build.log")
        try:
            source = build_logs.path(self.module)
            log.info("Moving logs from %r to %r" % (source, log_path))
            shutil.copy(source, log_path)
        except IOError as e:
            log.exception(e)
        return prepdir

    def _upload_outputs(self, session, metadata, file_dir):
        """
        Uploads output files to Koji hub.
        """
        to_upload = []
        for info in metadata['output']:
            if info.get('metadata_only', False):
                continue
            localpath = os.path.join(file_dir, info['filename'])
            if not os.path.exists(localpath):
                err = "Cannot upload %s to Koji. No such file." % localpath
                log.error(err)
                raise RuntimeError(err)

            to_upload.append([localpath, info])

        # Create unique server directory.
        serverdir = 'mbs/%r.%d' % (time.time(), self.module.id)

        for localpath, info in to_upload:
            log.info("Uploading %s to Koji" % localpath)
            session.uploadWrapper(localpath, serverdir, callback=None)
            log.info("Upload of %s to Koji done" % localpath)

        return serverdir

    def _tag_cg_build(self):
        """
        Tags the Content Generator build to module.cg_build_koji_tag.
        """
        session = KojiModuleBuilder.get_session(self.config, self.owner)

        tag_name = self.module.cg_build_koji_tag
        if not tag_name:
            log.info("%r: Not tagging Content Generator build, no "
                     "cg_build_koji_tag set", self.module)
            return

        tag_names_to_try = [tag_name, self.config.koji_cg_default_build_tag]
        for tag in tag_names_to_try:
            log.info("Trying %s", tag)
            tag_info = session.getTag(tag)
            if tag_info:
                break

            log.info("%r: Tag %s not found in Koji, trying next one.",
                     self.module, tag)

        if not tag_info:
            log.warn("%r:, Not tagging Content Generator build, no "
                     "available tag found, tried %r", self.module,
                     tag_names_to_try)
            return

        build = self._get_build()
        nvr = "%s-%s-%s" % (build["name"], build["version"], build["release"])

        log.info("Content generator build %s will be tagged as %s in "
                 "Koji", nvr, tag)
        session.tagBuild(tag_info["id"], nvr)

    def koji_import(self):
        """This method imports given module into the configured koji instance as
        a content generator based build

        Raises an exception when error is encountered during import"""
        session = KojiModuleBuilder.get_session(self.config, self.owner)

        file_dir = self._prepare_file_directory()
        metadata = self._get_content_generator_metadata(file_dir)
        try:
            serverdir = self._upload_outputs(session, metadata, file_dir)
            build_info = session.CGImport(metadata, serverdir)
            self._tag_cg_build()
            log.info("Content generator import done.")
            log.debug(json.dumps(build_info, sort_keys=True, indent=4))

            # Only remove the logs if CG import was successful.  If it fails,
            # then we want to keep them around for debugging.
            log.info("Removing %r" % file_dir)
            shutil.rmtree(file_dir)
        except Exception as e:
            log.exception("Content generator import failed: %s", e)
            raise e
