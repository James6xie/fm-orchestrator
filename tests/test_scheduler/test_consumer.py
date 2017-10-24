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

import unittest
from mock import patch, MagicMock
from module_build_service.scheduler.consumer import MBSConsumer
from module_build_service.messaging import KojiTagChange, KojiRepoChange


class TestConsumer(unittest.TestCase):

    @patch('module_build_service.messaging.conf.messaging', new='fedmsg')
    def test_get_abstracted_msg_fedmsg(self):
        """
        Test the output of get_abstracted_msg() when using the
        fedmsg backend.
        """
        hub = MagicMock(config={})
        consumer = MBSConsumer(hub)
        msg = {
            "username": "apache",
            "source_name": "datanommer",
            "i": 1,
            "timestamp": 1505492681.0,
            "msg_id": "2017-0627b798-f241-4230-b365-8a8a111a8ec5",
            "crypto": "x509",
            "topic": "org.fedoraproject.prod.buildsys.tag",
            "headers": {},
            "source_version": "0.8.1",
            "msg": {
                "build_id": 962861,
                "name": "python3-virtualenv",
                "tag_id": 263,
                "instance": "primary",
                "tag": "epel7-pending",
                "user": "bodhi",
                "version": "15.1.0",
                "owner": "orion",
                "release": "1.el7"
            }
        }
        msg_obj = consumer.get_abstracted_msg(msg)
        self.assertIsInstance(msg_obj, KojiTagChange)
        self.assertEqual(msg_obj.msg_id, msg['msg_id'])
        self.assertEqual(msg_obj.tag, msg['msg']['tag'])
        self.assertEqual(msg_obj.artifact, msg['msg']['name'])

    @patch('module_build_service.scheduler.consumer.models')
    @patch.object(MBSConsumer, 'process_message')
    @patch('module_build_service.messaging.conf.messaging', new='fedmsg')
    def test_consume_fedmsg(self, process_message, models):
        """
        Test the MBSConsumer.consume() method when using the
        fedmsg backend.
        """
        hub = MagicMock(config={})
        consumer = MBSConsumer(hub)
        msg = {
            "topic": "org.fedoraproject.prod.buildsys.repo.done",
            "headers": {},
            "body": {
                "username": "apache",
                "source_name": "datanommer",
                "i": 1,
                "timestamp": 1405126329.0,
                "msg_id": "2014-adbc33f6-51b0-4fce-aa0d-3c699a9920e4",
                "crypto": "x509",
                "topic": "org.fedoraproject.prod.buildsys.repo.done",
                "headers": {},
                "source_version": "0.6.4",
                "msg": {
                    "instance": "primary",
                    "repo_id": 400859,
                    "tag": "f22-build",
                    "tag_id": 278
                }
            }
        }
        consumer.consume(msg)
        self.assertEqual(process_message.call_count, 1)
        msg_obj = process_message.call_args[0][1]
        self.assertIsInstance(msg_obj, KojiRepoChange)
        self.assertEqual(msg_obj.msg_id, msg['body']['msg_id'])
        self.assertEqual(msg_obj.repo_tag, msg['body']['msg']['tag'])
