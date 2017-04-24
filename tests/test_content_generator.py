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

from os import path
from os.path import dirname


import module_build_service.messaging
import module_build_service.scheduler.handlers.repos
import module_build_service.utils
from module_build_service import models, conf

from mock import patch, Mock

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
        self.cg = KojiContentGenerator(module, conf)

        filename = cassette_dir + self.id()
        self.vcr = vcr.use_cassette(filename)
        self.vcr.__enter__()


    def tearDown(self):
        # Necessary to restart the twisted reactor for the next test.
        import sys
        del sys.modules['twisted.internet.reactor']
        del sys.modules['moksha.hub.reactor']
        del sys.modules['moksha.hub']
        import moksha.hub.reactor
        self.vcr.__exit__()

    @patch("pkg_resources.get_distribution")
    @patch("platform.linux_distribution")
    @patch("platform.machine")
    @patch("module_build_service.builder.KojiContentGenerator.KojiContentGenerator._koji_rpms_in_tag")
    def test_get_generator_json(self, rpms_in_tag, machine, distro, pkg_res):
        self.maxDiff = None
        distro.return_value = ("Fedora", "25", "Twenty Five")
        machine.return_value = "i686"
        pkg_res.return_value = Mock()
        pkg_res.return_value.version = "current-tested-version"

        tests_dir = path.abspath(path.dirname(__file__))
        rpm_in_tag_path = path.join(tests_dir,
                                    "test_get_generator_json_rpms_in_tag.json")
        with open(rpm_in_tag_path) as rpms_in_tag_file:
            rpms_in_tag.return_value = json.load(rpms_in_tag_file)

        expected_output_path = path.join(tests_dir,
                                         "test_get_generator_json_expected_output.json")
        with open(expected_output_path) as expected_output_file:
            expected_output = json.load(expected_output_file)
        ret = self.cg._get_content_generator_metadata()
        rpms_in_tag.assert_called_once()
        self.assertEqual(expected_output, ret)
