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
# THE SOFTWARE IS PROVIDED 'AS IS', WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# Written by Matt Prahl <mprahl@redhat.com>
from __future__ import unicode_literals
import unittest
import mock
from datetime import datetime
import rida.messaging


class TestUtilFunctions(unittest.TestCase):

    rida_msg = msg = {
        'component_builds': [1, 2],
        'id': 1,
        'name': 'testmodule',
        'owner': 'some_user',
        'release': '16',
        'scmurl': 'git://domain.local/modules/testmodule.git?#c23acdc',
        'state': 3,
        'state_name': 'done',
        'time_completed': datetime(2016, 9, 1, 2, 30),
        'time_modified': datetime(2016, 9, 1, 2, 30),
        'time_submitted': datetime(2016, 9, 1, 2, 28),
        'version': '4.3.43'
    }

    @mock.patch('fedmsg.tail_messages')
    def test_fedmsg_listen_build_msg(self, mock_tail_messages):
        endpoint = 'tcp://hub.fedoraproject.org:9940'
        topic = 'org.fedoraproject.prod.buildsys.build.state.change'
        msg = {
            'source_name': 'datanommer',
            'i': 2,
            'timestamp': 1473252386.0,
            'msg_id': '2016-e05415d9-9b35-4f13-8b25-0daddeabfb8c',
            'topic': 'org.fedoraproject.prod.buildsys.build.state.change',
            'source_version': '1.2.3',
            'msg': {
                'build_id': 2345678,
                'old': None,
                'name': 'some-package',
                'task_id': 1234567,
                'attribute': 'state',
                'instance': 'arm',
                'version': '2.1.0',
                'owner': 'some_owner',
                'new': 0,
                'release': '1.fc26'
            }
        }
        mock_tail_messages.side_effect = \
            lambda: [('fedora-infrastructure', endpoint, topic, msg)]
        msg_obj = next(rida.messaging._fedmsg_listen(None))
        self.assertEquals(type(msg_obj), rida.messaging.KojiBuildChange)
        self.assertEquals(msg_obj.build_id, 2345678)
        self.assertEquals(msg_obj.build_new_state, 0)
        self.assertEquals(msg_obj.build_name, 'some-package')
        self.assertEquals(msg_obj.build_version, '2.1.0')
        self.assertEquals(msg_obj.build_release, '1.fc26')
        self.assertEquals(msg_obj.msg_id,
                          '2016-e05415d9-9b35-4f13-8b25-0daddeabfb8c')

    @mock.patch('fedmsg.tail_messages')
    def test_fedmsg_listen_repo_msg(self, mock_tail_messages):
        endpoint = 'tcp://hub.fedoraproject.org:9940'
        topic = 'org.fedoraproject.prod.buildsys.repo.done'
        msg = {
            'source_name': 'datanommer',
            'i': 1,
            'timestamp': 1473252506.0,
            'msg_id': '2016-e05415d9-9b35-4f13-8b25-0daddeabfb8c',
            'topic': 'org.fedoraproject.prod.buildsys.repo.done',
            'source_version': '1.2.0',
            'msg': {
                'instance': 'arm',
                'repo_id': 402102,
                'tag': 'f23-build',
                'tag_id': 155
            }
        }
        mock_tail_messages.side_effect = \
            lambda: [('fedora-infrastructure', endpoint, topic, msg)]
        msg_obj = next(rida.messaging._fedmsg_listen(None))
        self.assertEquals(type(msg_obj), rida.messaging.KojiRepoChange)
        self.assertEquals(msg_obj.repo_tag, 'f23-build')
        self.assertEquals(msg_obj.msg_id,
                          '2016-e05415d9-9b35-4f13-8b25-0daddeabfb8c')

    @mock.patch('fedmsg.tail_messages')
    def test_fedmsg_listen_rida_msg(self, mock_tail_messages):
        endpoint = 'tcp://hub.fedoraproject.org:9940'
        topic = 'org.fedoraproject.prod.rida.module.state.change'
        msg = {
            'msg_id': '2016-e05415d9-9b35-4f13-8b25-0daddeabfb8c',
            'topic': 'org.fedoraproject.prod.rida.module.state.change',
            'msg': self.rida_msg
        }
        mock_tail_messages.side_effect = \
            lambda: [('fedora-infrastructure', endpoint, topic, msg)]
        msg_obj = next(rida.messaging._fedmsg_listen(None))
        self.assertEquals(msg_obj.module_build_id, msg['msg']['id'])
        self.assertEquals(msg_obj.module_build_state, msg['msg']['state'])
        self.assertEquals(msg_obj.msg_id,
                          '2016-e05415d9-9b35-4f13-8b25-0daddeabfb8c')
