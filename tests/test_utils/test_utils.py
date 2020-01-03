# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
import io
import tempfile
import hashlib
from os import path, mkdir
from shutil import copyfile, rmtree
from datetime import datetime
from werkzeug.datastructures import FileStorage
from mock import patch

from module_build_service.common.utils import load_mmd, load_mmd_file, mmd_to_str
import module_build_service.utils
import module_build_service.scm
from module_build_service import app, models, conf
from module_build_service.errors import ValidationError, UnprocessableEntity
from module_build_service.utils.submit import format_mmd
from tests import (
    clean_database,
    init_data,
    scheduler_init_data,
    make_module_in_db,
    make_module,
    read_staged_data, staged_data_filename)
import mock
import pytest
import module_build_service.scheduler.handlers.components
from module_build_service.db_session import db_session
from module_build_service.scheduler import events

BASE_DIR = path.abspath(path.dirname(__file__))


class FakeSCM(object):
    def __init__(self, mocked_scm, name, mmd_filename, commit=None):
        self.mocked_scm = mocked_scm
        self.name = name
        self.commit = commit
        self.mmd_filename = mmd_filename
        self.sourcedir = None

        self.mocked_scm.return_value.checkout = self.checkout
        self.mocked_scm.return_value.name = self.name
        self.mocked_scm.return_value.branch = "master"
        self.mocked_scm.return_value.get_latest = self.get_latest
        self.mocked_scm.return_value.commit = self.commit
        self.mocked_scm.return_value.repository_root = "https://src.stg.fedoraproject.org/modules/"
        self.mocked_scm.return_value.sourcedir = self.sourcedir
        self.mocked_scm.return_value.get_module_yaml = self.get_module_yaml
        self.mocked_scm.return_value.is_full_commit_hash.return_value = commit and len(commit) == 40
        self.mocked_scm.return_value.get_full_commit_hash.return_value = self.get_full_commit_hash

    def checkout(self, temp_dir):
        self.sourcedir = path.join(temp_dir, self.name)
        mkdir(self.sourcedir)
        copyfile(staged_data_filename(self.mmd_filename), self.get_module_yaml())

        return self.sourcedir

    def get_latest(self, ref="master"):
        return self.commit if self.commit else ref

    def get_module_yaml(self):
        return path.join(self.sourcedir, self.name + ".yaml")

    def get_full_commit_hash(self, commit_hash=None):
        if not commit_hash:
            commit_hash = self.commit
        sha1_hash = hashlib.sha1("random").hexdigest()
        return commit_hash + sha1_hash[len(commit_hash):]


class TestUtils:
    def setup_method(self, test_method):
        clean_database()

    def teardown_method(self, test_method):
        clean_database()

    @patch("module_build_service.utils.submit.submit_module_build")
    def test_submit_module_build_from_yaml_with_skiptests(self, mock_submit):
        """
        Tests local module build from a yaml file with the skiptests option

        Args:
            mock_submit (MagickMock): mocked function submit_module_build, which we then
                inspect if it was called with correct arguments
        """
        module_dir = tempfile.mkdtemp()
        module = models.ModuleBuild.get_by_id(db_session, 3)
        mmd = module.mmd()
        modulemd_yaml = mmd_to_str(mmd)
        modulemd_file_path = path.join(module_dir, "testmodule.yaml")

        username = "test"
        stream = "dev"

        with io.open(modulemd_file_path, "w", encoding="utf-8") as fd:
            fd.write(modulemd_yaml)

        with open(modulemd_file_path, "rb") as fd:
            handle = FileStorage(fd)
            module_build_service.utils.submit_module_build_from_yaml(
                db_session, username, handle, {}, stream=stream, skiptests=True)
            mock_submit_args = mock_submit.call_args[0]
            username_arg = mock_submit_args[1]
            mmd_arg = mock_submit_args[2]
            assert mmd_arg.get_stream_name() == stream
            assert "\n\n%__spec_check_pre exit 0\n" in mmd_arg.get_buildopts().get_rpm_macros()
            assert username_arg == username
        rmtree(module_dir)

    @patch("koji.ClientSession")
    def test_get_build_arches(self, ClientSession):
        session = ClientSession.return_value
        session.getTag.return_value = {"arches": "ppc64le"}
        mmd = load_mmd(read_staged_data("formatted_testmodule"))
        r = module_build_service.utils.get_build_arches(mmd, conf)
        assert r == ["ppc64le"]

    @patch("koji.ClientSession")
    def test_get_build_arches_no_arch_set(self, ClientSession):
        """
        When no architecture is set in Koji tag, fallback to conf.arches.
        """
        session = ClientSession.return_value
        session.getTag.return_value = {"arches": ""}
        mmd = load_mmd(read_staged_data("formatted_testmodule"))
        r = module_build_service.utils.get_build_arches(mmd, conf)
        assert set(r) == set(conf.arches)

    @patch(
        "module_build_service.config.Config.allowed_privileged_module_names",
        new_callable=mock.PropertyMock,
        return_value=["testmodule"],
    )
    def test_get_build_arches_koji_tag_arches(self, cfg):
        mmd = load_mmd(read_staged_data("formatted_testmodule"))
        xmd = mmd.get_xmd()
        xmd["mbs"]["koji_tag_arches"] = ["ppc64", "ppc64le"]
        mmd.set_xmd(xmd)

        r = module_build_service.utils.get_build_arches(mmd, conf)
        assert r == ["ppc64", "ppc64le"]

    @patch.object(conf, "base_module_arches", new={"platform:xx": ["x86_64", "i686"]})
    def test_get_build_arches_base_module_override(self):
        mmd = load_mmd(read_staged_data("formatted_testmodule"))
        xmd = mmd.get_xmd()
        mbs_options = xmd["mbs"] if "mbs" in xmd.keys() else {}
        mbs_options["buildrequires"] = {"platform": {"stream": "xx"}}
        xmd["mbs"] = mbs_options
        mmd.set_xmd(xmd)

        r = module_build_service.utils.get_build_arches(mmd, conf)
        assert r == ["x86_64", "i686"]

    @patch("module_build_service.utils.submit.get_build_arches")
    def test_record_module_build_arches(self, get_build_arches):
        get_build_arches.return_value = ["x86_64", "i686"]
        scheduler_init_data(1)
        build = models.ModuleBuild.get_by_id(db_session, 2)
        build.arches = []
        module_build_service.utils.record_module_build_arches(build.mmd(), build)

        arches = {arch.name for arch in build.arches}
        assert arches == set(get_build_arches.return_value)

    @pytest.mark.parametrize(
        "scmurl",
        [
            (
                "https://src.stg.fedoraproject.org/modules/testmodule.git"
                "?#620ec77321b2ea7b0d67d82992dda3e1d67055b4"
            ),
            None,
        ],
    )
    @patch("module_build_service.scm.SCM")
    def test_format_mmd(self, mocked_scm, scmurl):
        mocked_scm.return_value.commit = "620ec77321b2ea7b0d67d82992dda3e1d67055b4"
        # For all the RPMs in testmodule, get_latest is called
        mocked_scm.return_value.get_latest.side_effect = [
            "4ceea43add2366d8b8c5a622a2fb563b625b9abf",
            "fbed359411a1baa08d4a88e0d12d426fbf8f602c",
        ]
        hashes_returned = {
            "master": "fbed359411a1baa08d4a88e0d12d426fbf8f602c",
            "f28": "4ceea43add2366d8b8c5a622a2fb563b625b9abf",
            "f27": "5deef23acd2367d8b8d5a621a2fc568b695bc3bd",
        }

        def mocked_get_latest(ref="master"):
            return hashes_returned[ref]

        mocked_scm.return_value.get_latest = mocked_get_latest
        mmd = load_mmd(read_staged_data("testmodule"))
        # Modify the component branches so we can identify them later on
        mmd.get_rpm_component("perl-Tangerine").set_ref("f28")
        mmd.get_rpm_component("tangerine").set_ref("f27")
        module_build_service.utils.format_mmd(mmd, scmurl)

        # Make sure that original refs are not changed.
        mmd_pkg_refs = [
            mmd.get_rpm_component(pkg_name).get_ref()
            for pkg_name in mmd.get_rpm_component_names()
        ]
        assert set(mmd_pkg_refs) == set(hashes_returned.keys())
        deps = mmd.get_dependencies()[0]
        assert deps.get_buildtime_modules() == ["platform"]
        assert deps.get_buildtime_streams("platform") == ["f28"]
        xmd = {
            "mbs": {
                "commit": "",
                "rpms": {
                    "perl-List-Compare": {"ref": "fbed359411a1baa08d4a88e0d12d426fbf8f602c"},
                    "perl-Tangerine": {"ref": "4ceea43add2366d8b8c5a622a2fb563b625b9abf"},
                    "tangerine": {"ref": "5deef23acd2367d8b8d5a621a2fc568b695bc3bd"},
                },
                "scmurl": "",
            }
        }
        if scmurl:
            xmd["mbs"]["commit"] = "620ec77321b2ea7b0d67d82992dda3e1d67055b4"
            xmd["mbs"]["scmurl"] = scmurl
        mmd_xmd = mmd.get_xmd()
        assert mmd_xmd == xmd

    @patch("module_build_service.scm.SCM")
    def test_record_component_builds_duplicate_components(self, mocked_scm):
        # Mock for format_mmd to get components' latest ref
        mocked_scm.return_value.commit = "620ec77321b2ea7b0d67d82992dda3e1d67055b4"
        mocked_scm.return_value.get_latest.side_effect = [
            "4ceea43add2366d8b8c5a622a2fb563b625b9abf",
            "fbed359411a1baa08d4a88e0d12d426fbf8f602c",
        ]

        mmd = load_mmd(read_staged_data("testmodule"))
        mmd = mmd.copy("testmodule-variant", "master")
        module_build = module_build_service.models.ModuleBuild()
        module_build.name = "testmodule-variant"
        module_build.stream = "master"
        module_build.version = 20170109091357
        module_build.state = models.BUILD_STATES["init"]
        module_build.scmurl = \
            "https://src.stg.fedoraproject.org/modules/testmodule.git?#ff1ea79"
        module_build.batch = 1
        module_build.owner = "Tom Brady"
        module_build.time_submitted = datetime(2017, 2, 15, 16, 8, 18)
        module_build.time_modified = datetime(2017, 2, 15, 16, 19, 35)
        module_build.rebuild_strategy = "changed-and-after"
        module_build.modulemd = mmd_to_str(mmd)
        db_session.add(module_build)
        db_session.commit()
        # Rename the the modulemd to include
        mmd = mmd.copy("testmodule")
        # Remove perl-Tangerine and tangerine from the modulemd to include so only one
        # component conflicts
        mmd.remove_rpm_component("perl-Tangerine")
        mmd.remove_rpm_component("tangerine")

        error_msg = (
            'The included module "testmodule" in "testmodule-variant" have '
            "the following conflicting components: perl-List-Compare"
        )
        format_mmd(mmd, module_build.scmurl)
        with pytest.raises(UnprocessableEntity) as e:
            module_build_service.utils.record_component_builds(
                mmd, module_build, main_mmd=module_build.mmd())

        assert str(e.value) == error_msg

    @patch("module_build_service.scm.SCM")
    def test_record_component_builds_set_weight(self, mocked_scm):
        # Mock for format_mmd to get components' latest ref
        mocked_scm.return_value.commit = "620ec77321b2ea7b0d67d82992dda3e1d67055b4"
        mocked_scm.return_value.get_latest.side_effect = [
            "4ceea43add2366d8b8c5a622a2fb563b625b9abf",
            "fbed359411a1baa08d4a88e0d12d426fbf8f602c",
            "dbed259411a1baa08d4a88e0d12d426fbf8f6037",
        ]

        mmd = load_mmd(read_staged_data("testmodule"))
        # Set the module name and stream
        mmd = mmd.copy("testmodule", "master")

        module_build = module_build_service.models.ModuleBuild()
        module_build.name = "testmodule"
        module_build.stream = "master"
        module_build.version = 20170109091357
        module_build.state = models.BUILD_STATES["init"]
        module_build.scmurl = \
            "https://src.stg.fedoraproject.org/modules/testmodule.git?#ff1ea79"
        module_build.batch = 1
        module_build.owner = "Tom Brady"
        module_build.time_submitted = datetime(2017, 2, 15, 16, 8, 18)
        module_build.time_modified = datetime(2017, 2, 15, 16, 19, 35)
        module_build.rebuild_strategy = "changed-and-after"
        module_build.modulemd = mmd_to_str(mmd)

        db_session.add(module_build)
        db_session.commit()

        format_mmd(mmd, module_build.scmurl)
        module_build_service.utils.record_component_builds(mmd, module_build)
        db_session.commit()

        assert module_build.state == models.BUILD_STATES["init"]
        db_session.refresh(module_build)
        for c in module_build.component_builds:
            assert c.weight == 1.5

    @patch("module_build_service.scm.SCM")
    def test_record_component_builds_component_exists_already(self, mocked_scm):
        mocked_scm.return_value.commit = "620ec77321b2ea7b0d67d82992dda3e1d67055b4"
        mocked_scm.return_value.get_latest.side_effect = [
            "4ceea43add2366d8b8c5a622a2fb563b625b9abf",
            "fbed359411a1baa08d4a88e0d12d426fbf8f602c",
            "dbed259411a1baa08d4a88e0d12d426fbf8f6037",

            "4ceea43add2366d8b8c5a622a2fb563b625b9abf",
            # To simulate that when a module is resubmitted, some ref of
            # its components is changed, which will cause MBS stops
            # recording component to database and raise an error.
            "abcdefg",
            "dbed259411a1baa08d4a88e0d12d426fbf8f6037",
        ]

        original_mmd = load_mmd(read_staged_data("testmodule"))

        # Set the module name and stream
        mmd = original_mmd.copy("testmodule", "master")
        module_build = module_build_service.models.ModuleBuild()
        module_build.name = "testmodule"
        module_build.stream = "master"
        module_build.version = 20170109091357
        module_build.state = models.BUILD_STATES["init"]
        module_build.scmurl = \
            "https://src.stg.fedoraproject.org/modules/testmodule.git?#ff1ea79"
        module_build.batch = 1
        module_build.owner = "Tom Brady"
        module_build.time_submitted = datetime(2017, 2, 15, 16, 8, 18)
        module_build.time_modified = datetime(2017, 2, 15, 16, 19, 35)
        module_build.rebuild_strategy = "changed-and-after"
        module_build.modulemd = mmd_to_str(mmd)
        db_session.add(module_build)
        db_session.commit()

        format_mmd(mmd, module_build.scmurl)
        module_build_service.utils.record_component_builds(mmd, module_build)
        db_session.commit()

        mmd = original_mmd.copy("testmodule", "master")

        from module_build_service.errors import ValidationError
        with pytest.raises(
                ValidationError,
                match=r"Component build .+ of module build .+ already exists in database"):
            format_mmd(mmd, module_build.scmurl)
            module_build_service.utils.record_component_builds(mmd, module_build)

    @patch("module_build_service.scm.SCM")
    def test_format_mmd_arches(self, mocked_scm):
        with app.app_context():
            clean_database()
            mocked_scm.return_value.commit = "620ec77321b2ea7b0d67d82992dda3e1d67055b4"
            mocked_scm.return_value.get_latest.side_effect = [
                "4ceea43add2366d8b8c5a622a2fb563b625b9abf",
                "fbed359411a1baa08d4a88e0d12d426fbf8f602c",
                "dbed259411a1baa08d4a88e0d12d426fbf8f6037",
                "4ceea43add2366d8b8c5a622a2fb563b625b9abf",
                "fbed359411a1baa08d4a88e0d12d426fbf8f602c",
                "dbed259411a1baa08d4a88e0d12d426fbf8f6037",
            ]

            testmodule_mmd_path = staged_data_filename("testmodule.yaml")
            test_archs = ["powerpc", "i486"]

            mmd1 = load_mmd_file(testmodule_mmd_path)
            module_build_service.utils.format_mmd(mmd1, None)

            for pkg_name in mmd1.get_rpm_component_names():
                pkg = mmd1.get_rpm_component(pkg_name)
                assert set(pkg.get_arches()) == set(conf.arches)

            mmd2 = load_mmd_file(testmodule_mmd_path)

            for pkg_name in mmd2.get_rpm_component_names():
                pkg = mmd2.get_rpm_component(pkg_name)
                pkg.reset_arches()
                for arch in test_archs:
                    pkg.add_restricted_arch(arch)

            module_build_service.utils.format_mmd(mmd2, None)

            for pkg_name in mmd2.get_rpm_component_names():
                pkg = mmd2.get_rpm_component(pkg_name)
                assert set(pkg.get_arches()) == set(test_archs)

    @patch("module_build_service.scm.SCM")
    @patch("module_build_service.utils.submit.ThreadPool")
    def test_format_mmd_update_time_modified(self, tp, mocked_scm):
        init_data()
        build = models.ModuleBuild.get_by_id(db_session, 2)

        async_result = mock.MagicMock()
        async_result.ready.side_effect = [False, False, False, True]
        tp.return_value.map_async.return_value = async_result

        test_datetime = datetime(2019, 2, 14, 11, 11, 45, 42968)

        mmd = load_mmd(read_staged_data("testmodule"))

        with patch("module_build_service.utils.submit.datetime") as dt:
            dt.utcnow.return_value = test_datetime
            module_build_service.utils.format_mmd(mmd, None, build, db_session)

        assert build.time_modified == test_datetime

    @patch("module_build_service.utils.submit.requests")
    def test_pdc_eol_check(self, requests):
        """ Push mock pdc responses through the eol check function. """

        response = mock.Mock()
        response.json.return_value = {
            "results": [{
                "id": 347907,
                "global_component": "mariadb",
                "name": "10.1",
                "slas": [{"id": 694207, "sla": "security_fixes", "eol": "2019-12-01"}],
                "type": "module",
                "active": True,
                "critical_path": False,
            }]
        }
        requests.get.return_value = response

        is_eol = module_build_service.utils.submit._is_eol_in_pdc("mariadb", "10.1")
        assert not is_eol

        response.json.return_value["results"][0]["active"] = False

        is_eol = module_build_service.utils.submit._is_eol_in_pdc("mariadb", "10.1")
        assert is_eol

    def test_get_prefixed_version_f28(self):
        scheduler_init_data(1)
        build_one = models.ModuleBuild.get_by_id(db_session, 2)
        v = module_build_service.utils.submit.get_prefixed_version(build_one.mmd())
        assert v == 2820180205135154

    def test_get_prefixed_version_fl701(self):
        scheduler_init_data(1)
        build_one = models.ModuleBuild.get_by_id(db_session, 2)
        mmd = build_one.mmd()
        xmd = mmd.get_xmd()
        xmd["mbs"]["buildrequires"]["platform"]["stream"] = "fl7.0.1-beta"
        mmd.set_xmd(xmd)
        v = module_build_service.utils.submit.get_prefixed_version(mmd)
        assert v == 7000120180205135154

    @patch("module_build_service.utils.submit.generate_expanded_mmds")
    def test_submit_build_new_mse_build(self, generate_expanded_mmds):
        """
        Tests that finished build can be resubmitted in case the resubmitted
        build adds new MSE build (it means there are new expanded
        buildrequires).
        """
        build = make_module_in_db("foo:stream:0:c1")
        assert build.state == models.BUILD_STATES["ready"]

        mmd1 = build.mmd()
        mmd2 = build.mmd()

        mmd2.set_context("c2")
        generate_expanded_mmds.return_value = [mmd1, mmd2]
        # Create a copy of mmd1 without xmd.mbs, since that will cause validate_mmd to fail
        mmd1_copy = mmd1.copy()
        mmd1_copy.set_xmd({})

        builds = module_build_service.utils.submit_module_build(db_session, "foo", mmd1_copy, {})
        ret = {b.mmd().get_context(): b.state for b in builds}
        assert ret == {"c1": models.BUILD_STATES["ready"], "c2": models.BUILD_STATES["init"]}

        assert builds[0].siblings(db_session) == [builds[1].id]
        assert builds[1].siblings(db_session) == [builds[0].id]

    @patch("module_build_service.utils.submit.generate_expanded_mmds")
    @patch(
        "module_build_service.config.Config.scratch_build_only_branches",
        new_callable=mock.PropertyMock,
        return_value=["^private-.*"],
    )
    def test_submit_build_scratch_build_only_branches(self, cfg, generate_expanded_mmds):
        """
        Tests the "scratch_build_only_branches" config option.
        """
        mmd = make_module("foo:stream:0:c1")
        generate_expanded_mmds.return_value = [mmd]
        # Create a copy of mmd1 without xmd.mbs, since that will cause validate_mmd to fail
        mmd_copy = mmd.copy()
        mmd_copy.set_xmd({})

        with pytest.raises(ValidationError,
                           match="Only scratch module builds can be built from this branch."):
            module_build_service.utils.submit_module_build(
                db_session, "foo", mmd_copy, {"branch": "private-foo"})

        module_build_service.utils.submit_module_build(
            db_session, "foo", mmd_copy, {"branch": "otherbranch"})


@patch(
    "module_build_service.config.Config.mock_resultsdir",
    new_callable=mock.PropertyMock,
    return_value=staged_data_filename("local_builds")
)
@patch(
    "module_build_service.config.Config.system", new_callable=mock.PropertyMock, return_value="mock"
)
class TestLocalBuilds:
    def setup_method(self):
        clean_database()
        events.scheduler.reset()

    def teardown_method(self):
        clean_database()
        events.scheduler.reset()

    def test_load_local_builds_name(self, conf_system, conf_resultsdir):
        module_build_service.utils.load_local_builds("testmodule")
        local_modules = models.ModuleBuild.local_modules(db_session)

        assert len(local_modules) == 1
        assert local_modules[0].koji_tag.endswith(
            "/module-testmodule-master-20170816080816/results")

    def test_load_local_builds_name_stream(self, conf_system, conf_resultsdir):
        module_build_service.utils.load_local_builds("testmodule:master")
        local_modules = models.ModuleBuild.local_modules(db_session)

        assert len(local_modules) == 1
        assert local_modules[0].koji_tag.endswith(
            "/module-testmodule-master-20170816080816/results")

    def test_load_local_builds_name_stream_non_existing(
        self, conf_system, conf_resultsdir
    ):
        with pytest.raises(RuntimeError):
            module_build_service.utils.load_local_builds("testmodule:x")
            models.ModuleBuild.local_modules(db_session)

    def test_load_local_builds_name_stream_version(self, conf_system, conf_resultsdir):
        module_build_service.utils.load_local_builds("testmodule:master:20170816080815")
        local_modules = models.ModuleBuild.local_modules(db_session)

        assert len(local_modules) == 1
        assert local_modules[0].koji_tag.endswith(
            "/module-testmodule-master-20170816080815/results")

    def test_load_local_builds_name_stream_version_non_existing(
        self, conf_system, conf_resultsdir
    ):
        with pytest.raises(RuntimeError):
            module_build_service.utils.load_local_builds("testmodule:master:123")
            models.ModuleBuild.local_modules(db_session)

    def test_load_local_builds_platform(self, conf_system, conf_resultsdir):
        module_build_service.utils.load_local_builds("platform")
        local_modules = models.ModuleBuild.local_modules(db_session)

        assert len(local_modules) == 1
        assert local_modules[0].koji_tag.endswith("/module-platform-f28-3/results")

    def test_load_local_builds_platform_f28(self, conf_system, conf_resultsdir):
        module_build_service.utils.load_local_builds("platform:f28")
        local_modules = models.ModuleBuild.local_modules(db_session)

        assert len(local_modules) == 1
        assert local_modules[0].koji_tag.endswith("/module-platform-f28-3/results")
