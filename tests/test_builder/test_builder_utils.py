# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
import tempfile
import shutil

from mock import patch, Mock, call

from module_build_service import conf
from module_build_service.builder import utils


class TestBuilderUtils:
    @patch("requests.get")
    @patch("koji.ClientSession")
    @patch("module_build_service.builder.utils.execute_cmd")
    def test_create_local_repo_from_koji_tag(self, mock_exec_cmd, mock_koji_session, mock_get):
        session = Mock()
        rpms = [
            {
                "arch": "src",
                "build_id": 875991,
                "name": "module-build-macros",
                "release": "1.module_92011fe6",
                "size": 6890,
                "version": "0.1",
            },
            {
                "arch": "noarch",
                "build_id": 875991,
                "name": "module-build-macros",
                "release": "1.module_92011fe6",
                "size": 6890,
                "version": "0.1",
            },
            {
                "arch": "x86_64",
                "build_id": 875636,
                "name": "ed-debuginfo",
                "release": "2.module_bd6e0eb1",
                "size": 81438,
                "version": "1.14.1",
            },
            {
                "arch": "x86_64",
                "build_id": 875636,
                "name": "ed",
                "release": "2.module_bd6e0eb1",
                "size": 80438,
                "version": "1.14.1",
            },
            {
                "arch": "x86_64",
                "build_id": 875640,
                "name": "mksh-debuginfo",
                "release": "2.module_bd6e0eb1",
                "size": 578774,
                "version": "54",
            },
            {
                "arch": "x86_64",
                "build_id": 875640,
                "name": "mksh",
                "release": "2.module_bd6e0eb1",
                "size": 267042,
                "version": "54",
            },
        ]

        builds = [
            {
                "build_id": 875640,
                "name": "mksh",
                "release": "2.module_bd6e0eb1",
                "version": "54",
                "volume_name": "prod",
            },
            {
                "build_id": 875636,
                "name": "ed",
                "release": "2.module_bd6e0eb1",
                "version": "1.14.1",
                "volume_name": "prod",
            },
            {
                "build_id": 875991,
                "name": "module-build-macros",
                "release": "1.module_92011fe6",
                "version": "0.1",
                "volume_name": "prod",
            },
        ]

        session.listTaggedRPMS.return_value = (rpms, builds)
        session.opts = {"topurl": "https://kojipkgs.stg.fedoraproject.org/"}
        mock_koji_session.return_value = session

        tag = "module-testmodule-master-20170405123740-build"
        temp_dir = tempfile.mkdtemp()
        try:
            utils.create_local_repo_from_koji_tag(conf, tag, temp_dir)
        finally:
            shutil.rmtree(temp_dir)

        url_one = (
            "https://kojipkgs.stg.fedoraproject.org//vol/prod/packages/module-build-macros/"
            "0.1/1.module_92011fe6/noarch/module-build-macros-0.1-1.module_92011fe6.noarch.rpm"
        )
        url_two = (
            "https://kojipkgs.stg.fedoraproject.org//vol/prod/packages/ed/1.14.1/"
            "2.module_bd6e0eb1/x86_64/ed-1.14.1-2.module_bd6e0eb1.x86_64.rpm"
        )
        url_three = (
            "https://kojipkgs.stg.fedoraproject.org//vol/prod/packages/mksh/54/"
            "2.module_bd6e0eb1/x86_64/mksh-54-2.module_bd6e0eb1.x86_64.rpm"
        )

        expected_calls = [
            call(url_one, stream=True, timeout=60),
            call(url_two, stream=True, timeout=60),
            call(url_three, stream=True, timeout=60),
        ]
        for expected_call in expected_calls:
            assert expected_call in mock_get.call_args_list
        assert len(mock_get.call_args_list) == len(expected_calls)
