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
# Written by Stanislav Ochotnicky <sochotnicky@redhat.com>

import unittest
import json
import vcr

import os
from os import path
from os.path import dirname

import module_build_service.messaging
import module_build_service.scheduler.handlers.repos # noqa
from module_build_service import models, conf, build_logs

from mock import patch, Mock, MagicMock, call

from tests import init_data

from module_build_service.builder.KojiContentGenerator import KojiContentGenerator

base_dir = dirname(dirname(__file__))
cassette_dir = base_dir + '/vcr-request-data/'

user = ('Homer J. Simpson', set(['packager']))


class TestBuild(unittest.TestCase):

    # Global variable used for tests if needed
    _global_var = None

    def setUp(self):
        init_data()
        module = models.ModuleBuild.query.filter_by(id=1).one()
        module.cg_build_koji_tag = "f27-module-candidate"
        self.cg = KojiContentGenerator(module, conf)

        filename = cassette_dir + self.id()
        self.vcr = vcr.use_cassette(filename)
        self.vcr.__enter__()

        # Ensure that there is no build log from other tests
        try:
            path = build_logs.path(self.cg.module)
            os.remove(path)
        except OSError:
            pass

    def tearDown(self):
        # Necessary to restart the twisted reactor for the next test.
        import sys
        del sys.modules['twisted.internet.reactor']
        del sys.modules['moksha.hub.reactor']
        del sys.modules['moksha.hub']
        import moksha.hub.reactor # noqa
        self.vcr.__exit__()
        try:
            path = build_logs.path(self.cg.module)
            os.remove(path)
        except OSError:
            pass

    @patch("subprocess.Popen")
    @patch("pkg_resources.get_distribution")
    @patch("platform.linux_distribution")
    @patch("platform.machine")
    @patch(("module_build_service.builder.KojiContentGenerator.KojiContentGenerator."
           "_koji_rpms_in_tag"))
    def test_get_generator_json(self, rpms_in_tag, machine, distro, pkg_res, popen):
        """ Test generation of content generator json """
        distro.return_value = ("Fedora", "25", "Twenty Five")
        self.maxDiff = None
        machine.return_value = "i686"
        pkg_res.return_value = Mock()
        pkg_res.return_value.version = "current-tested-version"
        rpm_mock = Mock()
        rpm_out = "rpm-name;1.0;r1;x86_64;(none);sigmd5:1;sigpgp:p;siggpg:g\n" \
                  "rpm-name-2;2.0;r2;i686;1;sigmd5:2;sigpgp:p2;siggpg:g2"
        attrs = {'communicate.return_value': (rpm_out, 'error'),
                 'wait.return_value': 0}
        rpm_mock.configure_mock(**attrs)
        popen.return_value = rpm_mock

        tests_dir = path.abspath(path.dirname(__file__))
        rpm_in_tag_path = path.join(tests_dir,
                                    "test_get_generator_json_rpms_in_tag.json")
        with open(rpm_in_tag_path) as rpms_in_tag_file:
            rpms_in_tag.return_value = json.load(rpms_in_tag_file)

        expected_output_path = path.join(tests_dir,
                                         "test_get_generator_json_expected_output_with_log.json")
        with open(expected_output_path) as expected_output_file:
            expected_output = json.load(expected_output_file)

        # create the build.log
        build_logs.start(self.cg.module)
        build_logs.stop(self.cg.module)

        file_dir = self.cg._prepare_file_directory()
        ret = self.cg._get_content_generator_metadata(file_dir)
        rpms_in_tag.assert_called_once()
        self.assertEqual(expected_output, ret)

    @patch("subprocess.Popen")
    @patch("pkg_resources.get_distribution")
    @patch("platform.linux_distribution")
    @patch("platform.machine")
    @patch(("module_build_service.builder.KojiContentGenerator.KojiContentGenerator."
           "_koji_rpms_in_tag"))
    def test_get_generator_json_no_log(self, rpms_in_tag, machine, distro, pkg_res, popen):
        """ Test generation of content generator json """
        distro.return_value = ("Fedora", "25", "Twenty Five")
        machine.return_value = "i686"
        pkg_res.return_value = Mock()
        pkg_res.return_value.version = "current-tested-version"
        rpm_mock = Mock()
        rpm_out = "rpm-name;1.0;r1;x86_64;(none);sigmd5:1;sigpgp:p;siggpg:g\n" \
                  "rpm-name-2;2.0;r2;i686;1;sigmd5:2;sigpgp:p2;siggpg:g2"
        attrs = {'communicate.return_value': (rpm_out, 'error'),
                 'wait.return_value': 0}
        rpm_mock.configure_mock(**attrs)
        popen.return_value = rpm_mock

        tests_dir = path.abspath(path.dirname(__file__))
        rpm_in_tag_path = path.join(tests_dir,
                                    "test_get_generator_json_rpms_in_tag.json")
        with open(rpm_in_tag_path) as rpms_in_tag_file:
            rpms_in_tag.return_value = json.load(rpms_in_tag_file)

        expected_output_path = path.join(tests_dir,
                                         "test_get_generator_json_expected_output.json")
        with open(expected_output_path) as expected_output_file:
            expected_output = json.load(expected_output_file)
        file_dir = self.cg._prepare_file_directory()
        ret = self.cg._get_content_generator_metadata(file_dir)
        rpms_in_tag.assert_called_once()
        self.assertEqual(expected_output, ret)

    def test_prepare_file_directory(self):
        """ Test preparation of directory with output files """
        dir_path = self.cg._prepare_file_directory()
        with open(path.join(dir_path, "modulemd.txt")) as mmd:
            self.assertEqual(len(mmd.read()), 1134)

    @patch("module_build_service.builder.KojiModuleBuilder.KojiModuleBuilder.get_session")
    def test_tag_cg_build(self, get_session):
        """ Test that the CG build is tagged. """
        koji_session = MagicMock()
        koji_session.getTag.return_value = {'id': 123}
        get_session.return_value = koji_session

        self.cg._tag_cg_build()

        koji_session.getTag.assert_called_once_with(self.cg.module.cg_build_koji_tag)
        koji_session.tagBuild.assert_called_once_with(123, "nginx-1-2")

    @patch("module_build_service.builder.KojiModuleBuilder.KojiModuleBuilder.get_session")
    def test_tag_cg_build_fallback_to_default_tag(self, get_session):
        """ Test that the CG build is tagged to default tag. """
        koji_session = MagicMock()
        koji_session.getTag.side_effect = [{}, {'id': 123}]
        get_session.return_value = koji_session

        self.cg._tag_cg_build()

        self.assertEqual(koji_session.getTag.mock_calls,
                         [call(self.cg.module.cg_build_koji_tag),
                          call(conf.koji_cg_default_build_tag)])
        koji_session.tagBuild.assert_called_once_with(123, "nginx-1-2")

    @patch("module_build_service.builder.KojiModuleBuilder.KojiModuleBuilder.get_session")
    def test_tag_cg_build_no_tag_set(self, get_session):
        """ Test that the CG build is not tagged when no tag set. """
        koji_session = MagicMock()
        koji_session.getTag.side_effect = [{}, {'id': 123}]
        get_session.return_value = koji_session

        self.cg.module.cg_build_koji_tag = None
        self.cg._tag_cg_build()

        koji_session.tagBuild.assert_not_called()

    @patch("module_build_service.builder.KojiModuleBuilder.KojiModuleBuilder.get_session")
    def test_tag_cg_build_no_tag_available(self, get_session):
        """ Test that the CG build is not tagged when no tag available. """
        koji_session = MagicMock()
        koji_session.getTag.side_effect = [{}, {}]
        get_session.return_value = koji_session

        self.cg._tag_cg_build()

        koji_session.tagBuild.assert_not_called()
