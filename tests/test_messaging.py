# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
from module_build_service import messaging
from module_build_service.messaging import KojiRepoChange  # noqa


class TestFedmsgMessaging:
    def test_buildsys_state_change(self):
        # https://fedora-fedmsg.readthedocs.io/en/latest/topics.html#id134
        buildsys_state_change_msg = {
            "msg": {
                "attribute": "state",
                "build_id": 614503,
                "instance": "primary",
                "name": "plasma-systemsettings",
                "new": 1,
                "old": 0,
                "owner": "dvratil",
                "release": "1.fc23",
                "task_id": 9053697,
                "version": "5.2.1",
            },
            "msg_id": "2015-51be4c8e-8ab6-4dcb-ac0d-37b257765c71",
            "timestamp": 1424789698.0,
            "topic": "org.fedoraproject.prod.buildsys.build.state.change",
        }

        msg = messaging.FedmsgMessageParser().parse(buildsys_state_change_msg)

        assert msg.build_id == 614503
        assert msg.build_new_state == 1

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
                "release": "1.module_0c3d13fd",
            },
            "msg_id": "2015-51be4c8e-8ab6-4dcb-ac0d-37b257765c71",
            "timestamp": 1424789698.0,
            "topic": "org.fedoraproject.prod.buildsys.tag",
        }

        msg = messaging.FedmsgMessageParser().parse(buildsys_tag_msg)

        assert msg.tag == "module-debugging-tools-master-20170405115403-build"
        assert msg.artifact == "module-build-macros"

    def test_buildsys_repo_done(self):
        # https://fedora-fedmsg.readthedocs.io/en/latest/topics.html#id134
        buildsys_tag_msg = {
            "msg": {
                "instance": "primary",
                "repo_id": 728809,
                "tag": "module-f0f7e44f3c6cccab-build",
                "tag_id": 653,
            },
            "msg_id": "2015-51be4c8e-8ab6-4dcb-ac0d-37b257765c71",
            "timestamp": 1424789698.0,
            "topic": "org.fedoraproject.prod.buildsys.repo.done",
        }

        msg = messaging.FedmsgMessageParser().parse(buildsys_tag_msg)

        assert msg.repo_tag == "module-f0f7e44f3c6cccab-build"
