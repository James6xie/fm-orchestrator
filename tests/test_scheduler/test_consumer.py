# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
from mock import patch, MagicMock
from module_build_service.scheduler import events
from module_build_service.scheduler.consumer import MBSConsumer


class TestConsumer:
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
                "release": "1.el7",
            },
        }
        event_info = consumer.get_abstracted_event_info(msg)
        assert event_info["event"] == events.KOJI_TAG_CHANGE
        assert event_info["msg_id"] == msg["msg_id"]
        assert event_info["tag_name"] == msg["msg"]["tag"]

    @patch("module_build_service.scheduler.consumer.models")
    @patch.object(MBSConsumer, "process_message")
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
                    "tag_id": 278,
                },
            },
        }
        consumer.consume(msg)
        assert process_message.call_count == 1
        event_info = process_message.call_args[0][0]
        assert event_info["event"] == events.KOJI_REPO_CHANGE
        assert event_info["msg_id"] == msg["body"]["msg_id"]
        assert event_info["tag_name"] == msg["body"]["msg"]["tag"]
