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
from module_build_service.messaging import KojiRepoChange # noqa
from mock import patch, PropertyMock


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

        msg = messaging.FedmsgMessageParser().parse(buildsys_state_change_msg)

        self.assertEqual(msg.build_id, 614503)
        self.assertEqual(msg.build_new_state, 1)

    @patch("module_build_service.config.Config.system",
           new_callable=PropertyMock, return_value="copr")
    def test_copr_build_end(self, conf_system):
        # http://fedora-fedmsg.readthedocs.io/en/latest/topics.html#copr-build-end
        copr_build_end_msg = {
            'msg': {
                'build': 100,
                'chroot': 'fedora-20-x86_64',
                'copr': 'mutt-kz',
                'ip': '172.16.3.3',
                'pid': 12010,
                'pkg': 'mutt-kz',  # Reality doesnt match the linked docs
                'status': 1,
                'user': 'fatka',
                'version': '1.5.23.1-1.20150203.git.c8504a8a.fc21',
                'what': ('build end: user:fatka copr:mutt-kz build:100 ip:172.16.3.3  '
                         'pid:12010 status:1'),
                'who': 'worker-2'
            },
            'msg_id': '2013-b05a323d-37ee-4396-9635-7b5dfaf5441b',
            'timestamp': 1383956707.634,
            'topic': 'org.fedoraproject.prod.copr.build.end',
            'username': 'copr'
        }

        msg = messaging.FedmsgMessageParser().parse(copr_build_end_msg)
        self.assertIsInstance(msg, messaging.KojiBuildChange)
        self.assertEqual(msg.msg_id, '2013-b05a323d-37ee-4396-9635-7b5dfaf5441b')
        self.assertEqual(msg.build_id, 100)
        self.assertEqual(msg.task_id, 100)
        self.assertEqual(msg.build_new_state, 1)
        self.assertEqual(msg.build_name, 'mutt-kz')
        self.assertEqual(msg.build_version, '1.5.23.1')
        self.assertEqual(msg.build_release, '1.20150203.git.c8504a8a.fc21')
        self.assertEqual(msg.state_reason,
                         ('build end: user:fatka copr:mutt-kz build:100 ip:172.16.3.3  '
                          'pid:12010 status:1'))

    def test_buildsys_tag(self):
        # https://fedora-fedmsg.readthedocs.io/en/latest/topics.html#id134
        buildsys_tag_msg = {
            "msg": {
                "build_id": 875961,
                "name": "module-build-macros",
                "tag_id": 619,
                "instance": "primary",
                "tag": "module-debugging-tools-master-20170405115403-build",
                "user": "mbs/mbs.fedoraproject.org",
                "version": "0.1",
                "owner": "mbs/mbs.fedoraproject.org",
                "release": "1.module_0c3d13fd"
            },
            'msg_id': '2015-51be4c8e-8ab6-4dcb-ac0d-37b257765c71',
            'timestamp': 1424789698.0,
            'topic': 'org.fedoraproject.prod.buildsys.tag'
        }

        msg = messaging.FedmsgMessageParser().parse(buildsys_tag_msg)

        self.assertEqual(msg.tag, "module-debugging-tools-master-20170405115403-build")
        self.assertEqual(msg.artifact, "module-build-macros")

    def test_buildsys_repo_done(self):
        # https://fedora-fedmsg.readthedocs.io/en/latest/topics.html#id134
        buildsys_tag_msg = {
            "msg": {
                "instance": "primary",
                "repo_id": 728809,
                "tag": "module-f0f7e44f3c6cccab-build",
                "tag_id": 653
            },
            'msg_id': '2015-51be4c8e-8ab6-4dcb-ac0d-37b257765c71',
            'timestamp': 1424789698.0,
            'topic': 'org.fedoraproject.prod.buildsys.repo.done'
        }

        msg = messaging.FedmsgMessageParser().parse(buildsys_tag_msg)

        self.assertEqual(msg.repo_tag, "module-f0f7e44f3c6cccab-build")
