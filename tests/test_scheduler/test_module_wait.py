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

import unittest
import mock
import module_build_service.messaging
import module_build_service.scheduler.handlers.modules
import modulemd as _modulemd
import os
import vcr

base_dir = os.path.dirname(os.path.dirname(__file__))
cassette_dir = base_dir + '/vcr-request-data/'


class TestModuleWait(unittest.TestCase):

    def setUp(self):
        self.config = mock.Mock()
        self.session = mock.Mock()
        self.fn = module_build_service.scheduler.handlers.modules.wait

        filename = cassette_dir + self.id()
        self.vcr = vcr.use_cassette(filename)
        self.vcr.__enter__()

    def tearDown(self):
        self.vcr.__exit__()

    @mock.patch('module_build_service.builder.KojiModuleBuilder')
    @mock.patch('module_build_service.models.ModuleBuild.from_module_event')
    @mock.patch('module_build_service.pdc')
    def test_init_basic(self, pdc, from_module_event, KojiModuleBuilder):
        builder = mock.Mock()
        builder.get_disttag_srpm.return_value = 'some srpm disttag'
        builder.build.return_value = 1234, 1, "", None
        builder.module_build_tag = {'name': 'some-tag-build'}
        KojiModuleBuilder.return_value = builder
        mocked_module_build = mock.Mock()
        mocked_module_build.json.return_value = {
            'name': 'foo',
            'stream': 1,
            'version': 1,
            'state': 'some state',
        }

        mmd = _modulemd.ModuleMetadata()
        formatted_testmodule_yml_path = os.path.join(
            base_dir, 'staged_data', 'formatted_testmodule.yaml')
        with open(formatted_testmodule_yml_path, 'r') as f:
            mmd.loads(f)

        mocked_module_build.mmd.return_value = mmd
        mocked_module_build.component_builds = []

        from_module_event.return_value = mocked_module_build

        msg = module_build_service.messaging.MBSModule(msg_id=None, module_build_id=1,
                                                        module_build_state='some state')
        self.fn(config=self.config, session=self.session, msg=msg)
