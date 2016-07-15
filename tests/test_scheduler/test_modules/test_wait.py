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

import rida.scheduler.handlers.modules


class TestWait(unittest.TestCase):

    def setUp(self):
        self.config = mock.Mock()
        self.session = mock.Mock()
        self.fn = rida.scheduler.handlers.modules.wait

    @mock.patch('rida.builder.KojiModuleBuilder')
    @mock.patch('rida.database.ModuleBuild.from_fedmsg')
    @mock.patch('rida.pdc.get_pdc_client_session')
    def test_init_basic(self, pdc, from_fedmsg, KojiModuleBuilder):
        builder = mock.Mock()
        KojiModuleBuilder.return_value = builder
        mocked_module_build = mock.Mock()
        mocked_module_build.json.return_value = {
            'name': 'foo',
            'version': 1,
            'release': 1,
        }
        from_fedmsg.return_value = mocked_module_build

        msg = {
            'topic': 'org.fedoraproject.prod.rida.module.state.change',
            'msg': {
                'id': 1,
            },
        }
        self.fn(config=self.config, session=self.session, msg=msg)
