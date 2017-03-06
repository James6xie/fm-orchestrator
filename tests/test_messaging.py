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
# Written by Jakub Kadlcik <jkadlcik@redhat.com>


import unittest
from module_build_service import messaging


class TestFedmsgMessaging(unittest.TestCase):

    def test_buildsys_state_change(self):
        # https://fedora-fedmsg.readthedocs.io/en/latest/topics.html#id134
        buildsys_state_change_msg = {
            'msg': {
                'attribute': 'state',
                'build_id': 614503,
                'instance': 'primary',
                'name': 'plasma-systemsettings',
                'new': 1,
                'old': 0,
                'owner': 'dvratil',
                'release': '1.fc23',
                'task_id': 9053697,
                'version': '5.2.1'
            },
            'msg_id': '2015-51be4c8e-8ab6-4dcb-ac0d-37b257765c71',
            'timestamp': 1424789698.0,
            'topic': 'org.fedoraproject.prod.buildsys.build.state.change'
        }

        topic = 'org.fedoraproject.prod.buildsys.build.state.change'
        msg = messaging.BaseMessage.from_fedmsg(topic, buildsys_state_change_msg)

        self.assertEqual(msg.build_id, 614503)
        self.assertEqual(msg.build_new_state, 1)
