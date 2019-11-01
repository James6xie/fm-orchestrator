# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
import os
import mock
import koji
import tempfile
import shutil
from textwrap import dedent

import kobo.rpmlib

from module_build_service import conf
from module_build_service.db_session import db_session
from module_build_service.models import ModuleBuild, ComponentBuild
from module_build_service.builder.MockModuleBuilder import MockModuleBuilder
from module_build_service.utils import import_fake_base_module, mmd_to_str, load_mmd
from tests import clean_database, make_module_in_db, read_staged_data


class TestMockModuleBuilder:
    def setup_method(self, test_method):
        clean_database()
        self.resultdir = tempfile.mkdtemp()

    def teardown_method(self, test_method):
        clean_database()
        shutil.rmtree(self.resultdir)

    def _create_module_with_filters(self, db_session, batch, state):
        mmd = load_mmd(read_staged_data("testmodule-with-filters"))
        # Set the name and stream
        mmd = mmd.copy("mbs-testmodule", "test")
        mmd.set_xmd({
            "mbs": {
                "rpms": {
                    "ed": {"ref": "01bf8330812fea798671925cc537f2f29b0bd216"},
                    "mksh": {"ref": "f70fd11ddf96bce0e2c64309706c29156b39141d"},
                },
                "buildrequires": {
                    "host": {
                        "version": "20171024133034",
                        "filtered_rpms": [],
                        "stream": "master",
                        "ref": "6df253bb3c53e84706c01b8ab2d5cac24f0b6d45",
                        "context": "00000000",
                    },
                    "platform": {
                        "version": "20171028112959",
                        "filtered_rpms": [],
                        "stream": "master",
                        "ref": "4f7787370a931d57421f9f9555fc41c3e31ff1fa",
                        "context": "00000000",
                    },
                },
                "scmurl": "file:///testdir",
                "commit": "5566bc792ec7a03bb0e28edd1b104a96ba342bd8",
                "requires": {
                    "platform": {
                        "version": "20171028112959",
                        "filtered_rpms": [],
                        "stream": "master",
                        "ref": "4f7787370a931d57421f9f9555fc41c3e31ff1fa",
                        "context": "00000000",
                    }
                },
            }
        })
        module = ModuleBuild.create(
            db_session,
            conf,
            name="mbs-testmodule",
            stream="test",
            version="20171027111452",
            modulemd=mmd_to_str(mmd),
            scmurl="file:///testdir",
            username="test",
        )
        module.koji_tag = "module-mbs-testmodule-test-20171027111452"
        module.batch = batch
        db_session.add(module)
        db_session.commit()

        comp_builds = [
            {
                "module_id": module.id,
                "state": state,
                "package": "ed",
                "format": "rpms",
                "scmurl": (
                    "https://src.fedoraproject.org/rpms/ed"
                    "?#01bf8330812fea798671925cc537f2f29b0bd216"
                ),
                "batch": 2,
                "ref": "01bf8330812fea798671925cc537f2f29b0bd216",
            },
            {
                "module_id": module.id,
                "state": state,
                "package": "mksh",
                "format": "rpms",
                "scmurl": (
                    "https://src.fedoraproject.org/rpms/mksh"
                    "?#f70fd11ddf96bce0e2c64309706c29156b39141d"
                ),
                "batch": 3,
                "ref": "f70fd11ddf96bce0e2c64309706c29156b39141d",
            },
        ]

        for build in comp_builds:
            db_session.add(ComponentBuild(**build))
        db_session.commit()

        return module

    @mock.patch("module_build_service.conf.system", new="mock")
    def test_createrepo_filter_last_batch(self):
        module = self._create_module_with_filters(db_session, 3, koji.BUILD_STATES["COMPLETE"])

        builder = MockModuleBuilder(
            db_session, "mcurlej", module, conf, module.koji_tag, module.component_builds
        )
        builder.resultsdir = self.resultdir
        rpms = [
            "ed-1.14.1-4.module+24957a32.x86_64.rpm",
            "mksh-56b-1.module+24957a32.x86_64.rpm",
            "module-build-macros-0.1-1.module+24957a32.noarch.rpm",
        ]
        rpm_qf_output = dedent("""\
            ed 0 1.14.1 4.module+24957a32 x86_64
            mksh 0 56b-1 module+24957a32 x86_64
            module-build-macros 0 0.1 1.module+24957a32 noarch
        """)
        with mock.patch("os.listdir", return_value=rpms):
            with mock.patch("subprocess.check_output", return_value=rpm_qf_output):
                builder._createrepo()

        with open(os.path.join(self.resultdir, "pkglist"), "r") as fd:
            pkglist = fd.read().strip()
            rpm_names = [kobo.rpmlib.parse_nvr(rpm)["name"] for rpm in pkglist.split("\n")]
            assert "ed" not in rpm_names

    @mock.patch("module_build_service.conf.system", new="mock")
    def test_createrepo_not_last_batch(self):
        module = self._create_module_with_filters(db_session, 2, koji.BUILD_STATES["COMPLETE"])

        builder = MockModuleBuilder(
            db_session, "mcurlej", module, conf, module.koji_tag, module.component_builds
        )
        builder.resultsdir = self.resultdir
        rpms = [
            "ed-1.14.1-4.module+24957a32.x86_64.rpm",
            "mksh-56b-1.module+24957a32.x86_64.rpm",
        ]
        rpm_qf_output = dedent("""\
            ed 0 1.14.1 4.module+24957a32 x86_64
            mksh 0 56b-1 module+24957a32 x86_64
        """)
        with mock.patch("os.listdir", return_value=rpms):
            with mock.patch("subprocess.check_output", return_value=rpm_qf_output):
                builder._createrepo()

        with open(os.path.join(self.resultdir, "pkglist"), "r") as fd:
            pkglist = fd.read().strip()
            rpm_names = [kobo.rpmlib.parse_nvr(rpm)["name"] for rpm in pkglist.split("\n")]
            assert "ed" in rpm_names

    @mock.patch("module_build_service.conf.system", new="mock")
    def test_createrepo_empty_rmp_list(self):
        module = self._create_module_with_filters(db_session, 3, koji.BUILD_STATES["COMPLETE"])

        builder = MockModuleBuilder(
            db_session, "mcurlej", module, conf, module.koji_tag, module.component_builds)
        builder.resultsdir = self.resultdir
        rpms = []
        with mock.patch("os.listdir", return_value=rpms):
            builder._createrepo()

        with open(os.path.join(self.resultdir, "pkglist"), "r") as fd:
            pkglist = fd.read().strip()
            assert not pkglist


class TestMockModuleBuilderAddRepos:
    def setup_method(self, test_method):
        clean_database(add_platform_module=False)

    @mock.patch("module_build_service.conf.system", new="mock")
    @mock.patch(
        "module_build_service.config.Config.base_module_repofiles",
        new_callable=mock.PropertyMock,
        return_value=["/etc/yum.repos.d/bar.repo", "/etc/yum.repos.d/bar-updates.repo"],
        create=True,
    )
    @mock.patch("module_build_service.builder.MockModuleBuilder.open", create=True)
    @mock.patch(
        "module_build_service.builder.MockModuleBuilder.MockModuleBuilder._load_mock_config"
    )
    @mock.patch(
        "module_build_service.builder.MockModuleBuilder.MockModuleBuilder._write_mock_config"
    )
    def test_buildroot_add_repos(
        self, write_config, load_config, patched_open, base_module_repofiles
    ):
        import_fake_base_module("platform:f29:1:000000")

        platform = ModuleBuild.get_last_build_in_stream(db_session, "platform", "f29")
        module_deps = [{
            "requires": {"platform": ["f29"]},
            "buildrequires": {"platform": ["f29"]},
        }]
        foo = make_module_in_db("foo:1:1:1", module_deps)
        app = make_module_in_db("app:1:1:1", module_deps)

        patched_open.side_effect = [
            mock.mock_open(read_data="[fake]\nrepofile 1\n").return_value,
            mock.mock_open(read_data="[fake]\nrepofile 2\n").return_value,
            mock.mock_open(read_data="[fake]\nrepofile 3\n").return_value,
        ]

        builder = MockModuleBuilder(db_session, "user", app, conf, "module-app", [])

        dependencies = {
            "repofile://": [platform.mmd()],
            "repofile:///etc/yum.repos.d/foo.repo": [foo.mmd(), app.mmd()],
        }

        builder.buildroot_add_repos(dependencies)

        assert "repofile 1" in builder.yum_conf
        assert "repofile 2" in builder.yum_conf
        assert "repofile 3" in builder.yum_conf

        assert set(builder.enabled_modules) == {"foo:1", "app:1"}
