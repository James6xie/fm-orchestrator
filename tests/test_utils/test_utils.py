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
from sqlalchemy.orm.session import make_transient

from module_build_service.common.utils import import_mmd, load_mmd, load_mmd_file, mmd_to_str
import module_build_service.utils
import module_build_service.scm
from module_build_service import models, conf
from module_build_service.errors import ValidationError, UnprocessableEntity
from module_build_service.utils.reuse import get_reusable_module, get_reusable_component
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
from module_build_service import app, Modulemd

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


@pytest.mark.usefixtures("reuse_component_init_data")
class TestUtilsComponentReuse:
    @pytest.mark.parametrize(
        "changed_component", ["perl-List-Compare", "perl-Tangerine", "tangerine", None]
    )
    def test_get_reusable_component_different_component(self, changed_component):
        second_module_build = models.ModuleBuild.get_by_id(db_session, 3)
        if changed_component:
            mmd = second_module_build.mmd()
            mmd.get_rpm_component("tangerine").set_ref("00ea1da4192a2030f9ae023de3b3143ed647bbab")
            second_module_build.modulemd = mmd_to_str(mmd)

            second_module_changed_component = models.ComponentBuild.from_component_name(
                db_session, changed_component, second_module_build.id)
            second_module_changed_component.ref = "00ea1da4192a2030f9ae023de3b3143ed647bbab"
            db_session.add(second_module_changed_component)
            db_session.commit()

        plc_rv = get_reusable_component(second_module_build, "perl-List-Compare")
        pt_rv = get_reusable_component(second_module_build, "perl-Tangerine")
        tangerine_rv = get_reusable_component(second_module_build, "tangerine")

        if changed_component == "perl-List-Compare":
            # perl-Tangerine can be reused even though a component in its batch has changed
            assert plc_rv is None
            assert pt_rv.package == "perl-Tangerine"
            assert tangerine_rv is None
        elif changed_component == "perl-Tangerine":
            # perl-List-Compare can be reused even though a component in its batch has changed
            assert plc_rv.package == "perl-List-Compare"
            assert pt_rv is None
            assert tangerine_rv is None
        elif changed_component == "tangerine":
            # perl-List-Compare and perl-Tangerine can be reused since they are in an earlier
            # buildorder than tangerine
            assert plc_rv.package == "perl-List-Compare"
            assert pt_rv.package == "perl-Tangerine"
            assert tangerine_rv is None
        elif changed_component is None:
            # Nothing has changed so everthing can be used
            assert plc_rv.package == "perl-List-Compare"
            assert pt_rv.package == "perl-Tangerine"
            assert tangerine_rv.package == "tangerine"

    def test_get_reusable_component_different_rpm_macros(self):
        second_module_build = models.ModuleBuild.get_by_id(db_session, 3)
        mmd = second_module_build.mmd()
        buildopts = Modulemd.Buildopts()
        buildopts.set_rpm_macros("%my_macro 1")
        mmd.set_buildopts(buildopts)
        second_module_build.modulemd = mmd_to_str(mmd)
        db_session.commit()

        plc_rv = get_reusable_component(second_module_build, "perl-List-Compare")
        assert plc_rv is None

        pt_rv = get_reusable_component(second_module_build, "perl-Tangerine")
        assert pt_rv is None

    @pytest.mark.parametrize("set_current_arch", [True, False])
    @pytest.mark.parametrize("set_database_arch", [True, False])
    def test_get_reusable_component_different_arches(
        self, set_database_arch, set_current_arch
    ):
        second_module_build = models.ModuleBuild.get_by_id(db_session, 3)

        if set_current_arch:  # set architecture for current build
            mmd = second_module_build.mmd()
            component = mmd.get_rpm_component("tangerine")
            component.reset_arches()
            component.add_restricted_arch("i686")
            second_module_build.modulemd = mmd_to_str(mmd)
            db_session.commit()

        if set_database_arch:  # set architecture for build in database
            second_module_changed_component = models.ComponentBuild.from_component_name(
                db_session, "tangerine", 2)
            mmd = second_module_changed_component.module_build.mmd()
            component = mmd.get_rpm_component("tangerine")
            component.reset_arches()
            component.add_restricted_arch("i686")
            second_module_changed_component.module_build.modulemd = mmd_to_str(mmd)
            db_session.commit()

        tangerine = get_reusable_component(second_module_build, "tangerine")
        assert bool(tangerine is None) != bool(set_current_arch == set_database_arch)

    @pytest.mark.parametrize(
        "reuse_component",
        ["perl-Tangerine", "perl-List-Compare", "tangerine"])
    @pytest.mark.parametrize(
        "changed_component",
        ["perl-Tangerine", "perl-List-Compare", "tangerine"])
    def test_get_reusable_component_different_batch(
        self, changed_component, reuse_component
    ):
        """
        Test that we get the correct reuse behavior for the changed-and-after strategy. Changes
        to earlier batches should prevent reuse, but changes to later batches should not.
        For context, see https://pagure.io/fm-orchestrator/issue/1298
        """

        if changed_component == reuse_component:
            # we're only testing the cases where these are different
            # this case is already covered by test_get_reusable_component_different_component
            return

        second_module_build = models.ModuleBuild.get_by_id(db_session, 3)

        # update batch for changed component
        changed_component = models.ComponentBuild.from_component_name(
            db_session, changed_component, second_module_build.id)
        orig_batch = changed_component.batch
        changed_component.batch = orig_batch + 1
        db_session.commit()

        reuse_component = models.ComponentBuild.from_component_name(
            db_session, reuse_component, second_module_build.id)

        reuse_result = module_build_service.utils.get_reusable_component(
            second_module_build, reuse_component.package)
        # Component reuse should only be blocked when an earlier batch has been changed.
        # In this case, orig_batch is the earliest batch that has been changed (the changed
        # component has been removed from it and added to the following one).
        assert bool(reuse_result is None) == bool(reuse_component.batch > orig_batch)

    @pytest.mark.parametrize(
        "reuse_component",
        ["perl-Tangerine", "perl-List-Compare", "tangerine"])
    @pytest.mark.parametrize(
        "changed_component",
        ["perl-Tangerine", "perl-List-Compare", "tangerine"])
    def test_get_reusable_component_different_arch_in_batch(
        self, changed_component, reuse_component
    ):
        """
        Test that we get the correct reuse behavior for the changed-and-after strategy. Changes
        to the architectures in earlier batches should prevent reuse, but such changes to later
        batches should not.
        For context, see https://pagure.io/fm-orchestrator/issue/1298
        """
        if changed_component == reuse_component:
            # we're only testing the cases where these are different
            # this case is already covered by test_get_reusable_component_different_arches
            return

        second_module_build = models.ModuleBuild.get_by_id(db_session, 3)

        # update arch for changed component
        mmd = second_module_build.mmd()
        component = mmd.get_rpm_component(changed_component)
        component.reset_arches()
        component.add_restricted_arch("i686")
        second_module_build.modulemd = mmd_to_str(mmd)
        db_session.commit()

        changed_component = models.ComponentBuild.from_component_name(
            db_session, changed_component, second_module_build.id)
        reuse_component = models.ComponentBuild.from_component_name(
            db_session, reuse_component, second_module_build.id)

        reuse_result = module_build_service.utils.get_reusable_component(
            second_module_build, reuse_component.package)
        # Changing the arch of a component should prevent reuse only when the changed component
        # is in a batch earlier than the component being considered for reuse.
        assert bool(reuse_result is None) == bool(reuse_component.batch > changed_component.batch)

    @pytest.mark.parametrize("rebuild_strategy", models.ModuleBuild.rebuild_strategies.keys())
    def test_get_reusable_component_different_buildrequires_stream(self, rebuild_strategy):
        first_module_build = models.ModuleBuild.get_by_id(db_session, 2)
        first_module_build.rebuild_strategy = rebuild_strategy
        db_session.commit()

        second_module_build = models.ModuleBuild.get_by_id(db_session, 3)
        mmd = second_module_build.mmd()
        xmd = mmd.get_xmd()
        xmd["mbs"]["buildrequires"]["platform"]["stream"] = "different"
        deps = Modulemd.Dependencies()
        deps.add_buildtime_stream("platform", "different")
        deps.add_runtime_stream("platform", "different")
        mmd.clear_dependencies()
        mmd.add_dependencies(deps)

        mmd.set_xmd(xmd)
        second_module_build.modulemd = mmd_to_str(mmd)
        second_module_build.build_context = \
            module_build_service.models.ModuleBuild.contexts_from_mmd(
                second_module_build.modulemd
            ).build_context
        second_module_build.rebuild_strategy = rebuild_strategy
        db_session.commit()

        plc_rv = get_reusable_component(second_module_build, "perl-List-Compare")
        pt_rv = get_reusable_component(second_module_build, "perl-Tangerine")
        tangerine_rv = get_reusable_component(second_module_build, "tangerine")

        assert plc_rv is None
        assert pt_rv is None
        assert tangerine_rv is None

    def test_get_reusable_component_different_buildrequires(self):
        second_module_build = models.ModuleBuild.get_by_id(db_session, 3)
        mmd = second_module_build.mmd()
        mmd.get_dependencies()[0].add_buildtime_stream("some_module", "master")
        xmd = mmd.get_xmd()
        xmd["mbs"]["buildrequires"] = {
            "some_module": {
                "ref": "da39a3ee5e6b4b0d3255bfef95601890afd80709",
                "stream": "master",
                "version": "20170123140147",
            }
        }
        mmd.set_xmd(xmd)
        second_module_build.modulemd = mmd_to_str(mmd)
        second_module_build.build_context = models.ModuleBuild.calculate_build_context(
            xmd["mbs"]["buildrequires"])
        db_session.commit()

        plc_rv = get_reusable_component(second_module_build, "perl-List-Compare")
        assert plc_rv is None

        pt_rv = get_reusable_component(second_module_build, "perl-Tangerine")
        assert pt_rv is None

        tangerine_rv = get_reusable_component(second_module_build, "tangerine")
        assert tangerine_rv is None

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


class TestUtils:
    def setup_method(self, test_method):
        clean_database()

    def teardown_method(self, test_method):
        clean_database()

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

    @pytest.mark.usefixtures("reuse_shared_userspace_init_data")
    def test_get_reusable_component_shared_userspace_ordering(self):
        """
        For modules with lot of components per batch, there is big chance that
        the database will return them in different order than what we have for
        current `new_module`. In this case, reuse code should still be able to
        reuse the components.
        """
        old_module = models.ModuleBuild.get_by_id(db_session, 2)
        new_module = models.ModuleBuild.get_by_id(db_session, 3)
        rv = get_reusable_component(new_module, "llvm", previous_module_build=old_module)
        assert rv.package == "llvm"

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


@pytest.mark.usefixtures("reuse_component_init_data")
class TestUtilsModuleReuse:

    def test_get_reusable_module_when_reused_module_not_set(self):
        module = db_session.query(models.ModuleBuild)\
                           .filter_by(name="testmodule")\
                           .order_by(models.ModuleBuild.id.desc())\
                           .first()
        module.state = models.BUILD_STATES["build"]
        db_session.commit()

        assert not module.reused_module

        reusable_module = get_reusable_module(module)

        assert module.reused_module
        assert reusable_module.id == module.reused_module_id

    def test_get_reusable_module_when_reused_module_already_set(self):
        modules = db_session.query(models.ModuleBuild)\
                            .filter_by(name="testmodule")\
                            .order_by(models.ModuleBuild.id.desc())\
                            .limit(2).all()
        build_module = modules[0]
        reused_module = modules[1]
        build_module.state = models.BUILD_STATES["build"]
        build_module.reused_module_id = reused_module.id
        db_session.commit()

        assert build_module.reused_module
        assert reused_module == build_module.reused_module

        reusable_module = get_reusable_module(build_module)

        assert build_module.reused_module
        assert reusable_module.id == build_module.reused_module_id
        assert reusable_module.id == reused_module.id

    @pytest.mark.parametrize("allow_ocbm", (True, False))
    @patch(
        "module_build_service.config.Config.allow_only_compatible_base_modules",
        new_callable=mock.PropertyMock,
    )
    def test_get_reusable_module_use_latest_build(self, cfg, allow_ocbm):
        """
        Test that the `get_reusable_module` tries to reuse the latest module in case when
        multiple modules can be reused allow_only_compatible_base_modules is True.
        """
        cfg.return_value = allow_ocbm
        # Set "fedora" virtual stream to platform:f28.
        platform_f28 = db_session.query(models.ModuleBuild).filter_by(name="platform").one()
        mmd = platform_f28.mmd()
        xmd = mmd.get_xmd()
        xmd["mbs"]["virtual_streams"] = ["fedora"]
        mmd.set_xmd(xmd)
        platform_f28.modulemd = mmd_to_str(mmd)
        platform_f28.update_virtual_streams(db_session, ["fedora"])

        # Create platform:f29 with "fedora" virtual stream.
        mmd = load_mmd(read_staged_data("platform"))
        mmd = mmd.copy("platform", "f29")
        xmd = mmd.get_xmd()
        xmd["mbs"]["virtual_streams"] = ["fedora"]
        mmd.set_xmd(xmd)
        platform_f29 = import_mmd(db_session, mmd)[0]

        # Create another copy of `testmodule:master` which should be reused, because its
        # stream version will be higher than the previous one. Also set its buildrequires
        # to platform:f29.
        latest_module = db_session.query(models.ModuleBuild).filter_by(
            name="testmodule", state=models.BUILD_STATES["ready"]).one()
        # This is used to clone the ModuleBuild SQLAlchemy object without recreating it from
        # scratch.
        db_session.expunge(latest_module)
        make_transient(latest_module)

        # Change the platform:f28 buildrequirement to platform:f29 and recompute the build_context.
        mmd = latest_module.mmd()
        xmd = mmd.get_xmd()
        xmd["mbs"]["buildrequires"]["platform"]["stream"] = "f29"
        mmd.set_xmd(xmd)
        latest_module.modulemd = mmd_to_str(mmd)
        latest_module.build_context = module_build_service.models.ModuleBuild.contexts_from_mmd(
            latest_module.modulemd
        ).build_context
        latest_module.buildrequires = [platform_f29]

        # Set the `id` to None, so new one is generated by SQLAlchemy.
        latest_module.id = None
        db_session.add(latest_module)
        db_session.commit()

        module = db_session.query(models.ModuleBuild)\
                           .filter_by(name="testmodule")\
                           .filter_by(state=models.BUILD_STATES["build"])\
                           .one()
        db_session.commit()

        reusable_module = get_reusable_module(module)

        if allow_ocbm:
            assert reusable_module.id == latest_module.id
        else:
            first_module = db_session.query(models.ModuleBuild).filter_by(
                name="testmodule", state=models.BUILD_STATES["ready"]).first()
            assert reusable_module.id == first_module.id

    @pytest.mark.parametrize("allow_ocbm", (True, False))
    @patch(
        "module_build_service.config.Config.allow_only_compatible_base_modules",
        new_callable=mock.PropertyMock,
    )
    @patch("koji.ClientSession")
    @patch(
        "module_build_service.config.Config.resolver",
        new_callable=mock.PropertyMock, return_value="koji"
    )
    def test_get_reusable_module_koji_resolver(
            self, resolver, ClientSession, cfg, allow_ocbm):
        """
        Test that get_reusable_module works with KojiResolver.
        """
        cfg.return_value = allow_ocbm

        # Mock the listTagged so the testmodule:master is listed as tagged in the
        # module-fedora-27-build Koji tag.
        koji_session = ClientSession.return_value
        koji_session.listTagged.return_value = [
            {
                "build_id": 123, "name": "testmodule", "version": "master",
                "release": "20170109091357.78e4a6fd", "tag_name": "module-fedora-27-build"
            }]

        koji_session.multiCall.return_value = [
            [build] for build in koji_session.listTagged.return_value]

        # Mark platform:f28 as KojiResolver ready by defining "koji_tag_with_modules".
        # Also define the "virtual_streams" to possibly confuse the get_reusable_module.
        platform_f28 = db_session.query(models.ModuleBuild).filter_by(name="platform").one()
        mmd = platform_f28.mmd()
        xmd = mmd.get_xmd()
        xmd["mbs"]["virtual_streams"] = ["fedora"]
        xmd["mbs"]["koji_tag_with_modules"] = "module-fedora-27-build"
        mmd.set_xmd(xmd)
        platform_f28.modulemd = mmd_to_str(mmd)
        platform_f28.update_virtual_streams(db_session, ["fedora"])

        # Create platform:f27 without KojiResolver support.
        mmd = load_mmd(read_staged_data("platform"))
        mmd = mmd.copy("platform", "f27")
        xmd = mmd.get_xmd()
        xmd["mbs"]["virtual_streams"] = ["fedora"]
        mmd.set_xmd(xmd)
        platform_f27 = import_mmd(db_session, mmd)[0]

        # Change the reusable testmodule:master to buildrequire platform:f27.
        latest_module = db_session.query(models.ModuleBuild).filter_by(
            name="testmodule", state=models.BUILD_STATES["ready"]).one()
        mmd = latest_module.mmd()
        xmd = mmd.get_xmd()
        xmd["mbs"]["buildrequires"]["platform"]["stream"] = "f27"
        mmd.set_xmd(xmd)
        latest_module.modulemd = mmd_to_str(mmd)
        latest_module.buildrequires = [platform_f27]

        # Recompute the build_context and ensure that `build_context` changed while
        # `build_context_no_bms` did not change.
        contexts = module_build_service.models.ModuleBuild.contexts_from_mmd(
            latest_module.modulemd)

        assert latest_module.build_context_no_bms == contexts.build_context_no_bms
        assert latest_module.build_context != contexts.build_context

        latest_module.build_context = contexts.build_context
        latest_module.build_context_no_bms = contexts.build_context_no_bms
        db_session.commit()

        # Get the module we want to build.
        module = db_session.query(models.ModuleBuild)\
                           .filter_by(name="testmodule")\
                           .filter_by(state=models.BUILD_STATES["build"])\
                           .one()

        reusable_module = get_reusable_module(module)

        assert reusable_module.id == latest_module.id
