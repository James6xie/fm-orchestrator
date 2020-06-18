# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
from __future__ import absolute_import
from datetime import datetime
import os

import mock
import pytest

import module_build_service
from module_build_service.common.models import BUILD_STATES
from module_build_service.common.utils import load_mmd, mmd_to_str, import_mmd
from module_build_service.scheduler.db_session import db_session
from tests import (
    clean_database,
    init_data,
    truncate_tables,
    read_staged_data,
    reuse_component_init_data as reuse_component_init_data_impl,
)

BASE_DIR = os.path.dirname(__file__)
STAGED_DATA_DIR = os.path.join(BASE_DIR, "staged_data")

_mmd = load_mmd(read_staged_data("platform"))
PLATFORM_MODULEMD = mmd_to_str(_mmd)

_mmd2 = load_mmd(read_staged_data("formatted_testmodule"))
TESTMODULE_MODULEMD = mmd_to_str(_mmd2)

_mmd3 = load_mmd(read_staged_data("formatted_testmodule"))
_mmd3.set_context("c2c572ed")
TESTMODULE_MODULEMD_SECOND_CONTEXT = mmd_to_str(_mmd3)


@pytest.fixture()
def testmodule_mmd_9c690d0e():
    return TESTMODULE_MODULEMD


@pytest.fixture()
def testmodule_mmd_c2c572ed():
    return TESTMODULE_MODULEMD_SECOND_CONTEXT


@pytest.fixture()
def formatted_testmodule_mmd():
    return _mmd2


@pytest.fixture()
def platform_mmd():
    return PLATFORM_MODULEMD


@pytest.fixture(scope="class")
def require_empty_database_cls():
    """Provides cleared database"""
    truncate_tables()


@pytest.fixture(scope="class")
def require_platform_and_default_arch_cls(require_empty_database_cls):
    """Provides clean database with platform module and default arch"""
    arch_obj = module_build_service.common.models.ModuleArch(name="x86_64")
    db_session.add(arch_obj)
    db_session.commit()

    mmd = load_mmd(read_staged_data("platform"))
    import_mmd(db_session, mmd)


@pytest.fixture(scope="function")
def require_empty_database():
    """Provides cleared database"""
    truncate_tables()


@pytest.fixture(scope="function")
def require_default_arch(require_empty_database):
    """Provides empty database with x86_64 arch"""
    arch_obj = module_build_service.common.models.ModuleArch(name="x86_64")
    db_session.add(arch_obj)
    db_session.commit()


@pytest.fixture(scope="function")
def require_platform_and_default_arch(require_default_arch):
    """Provides clean database with platform module and a default arch"""
    mmd = load_mmd(read_staged_data("platform"))
    import_mmd(db_session, mmd)


def provide_test_data_impl(request):
    """Provides clean database with fresh test data based on supplied params:

    e.g.: @pytest.mark.parametrize("provide_test_data",
            [{"data_size": 1, "contexts": True, "multiple_stream_versions": True}], indirect=True)

    This is a fixture version of tests.init_data function.
    """
    size = 1
    contexts = False
    scratch = False
    multiple_stream_versions = False
    if hasattr(request, "param") and type(request.param) is dict:
        if "data_size" in request.param:
            size = request.param.get("data_size")
        if "contexts" in request.param:
            contexts = True
        if "multiple_stream_versions" in request.param:
            multiple_stream_versions = True
        if "scratch" in request.param:
            scratch = True
    init_data(data_size=size, contexts=contexts,
              multiple_stream_versions=multiple_stream_versions,
              scratch=scratch)


@pytest.fixture(scope="function")
def provide_test_data(request, require_platform_and_default_arch):
    provide_test_data_impl(request)


@pytest.fixture(scope="class")
def provide_test_data_cls(request, require_platform_and_default_arch_cls):
    provide_test_data_impl(request)


@pytest.fixture()
def reuse_component_init_data(require_platform_and_default_arch):
    reuse_component_init_data_impl()


@pytest.fixture(scope="class")
def reuse_component_init_data_cls(require_platform_and_default_arch_cls):
    reuse_component_init_data_impl()


@pytest.fixture()
def reuse_shared_userspace_init_data():
    # Create shared-userspace-570, state is COMPLETE, all components
    # are properly built.
    scmurl = "https://src.stg.fedoraproject.org/modules/testmodule.git?#7fea453"
    mmd = load_mmd(read_staged_data("shared-userspace-570"))
    xmd = mmd.get_xmd()
    xmd["mbs"]["scmurl"] = scmurl
    xmd["mbs"]["commit"] = "55f4a0a2e6cc255c88712a905157ab39315b8fd8"
    mmd.set_xmd(xmd)

    module_build = module_build_service.common.models.ModuleBuild(
        name=mmd.get_module_name(),
        stream=mmd.get_stream_name(),
        version=mmd.get_version(),
        build_context=module_build_service.common.models.ModuleBuild.calculate_build_context(
            xmd["mbs"]["buildrequires"]
        ),
        runtime_context="50dd3eb5dde600d072e45d4120e1548ce66bc94a",
        state=BUILD_STATES["ready"],
        modulemd=mmd_to_str(mmd),
        koji_tag="module-shared-userspace-f26-20170601141014-75f92abb",
        scmurl=scmurl,
        batch=16,
        owner="Tom Brady",
        time_submitted=datetime(2017, 2, 15, 16, 8, 18),
        time_modified=datetime(2017, 2, 15, 16, 19, 35),
        time_completed=datetime(2017, 2, 15, 16, 19, 35),
        rebuild_strategy="changed-and-after",
    )

    components = [
        mmd.get_rpm_component(rpm)
        for rpm in mmd.get_rpm_component_names()
    ]
    components.sort(key=lambda x: x.get_buildorder())
    previous_buildorder = None
    batch = 1
    xmd_mbs_rpms = xmd["mbs"]["rpms"]
    for pkg in components:
        # Increment the batch number when buildorder increases.
        if previous_buildorder != pkg.get_buildorder():
            previous_buildorder = pkg.get_buildorder()
            batch += 1

        pkgref = xmd_mbs_rpms[pkg.get_name()]["ref"]
        full_url = pkg.get_repository() + "?#" + pkgref

        module_build.component_builds.append(
            module_build_service.common.models.ComponentBuild(
                package=pkg.get_name(),
                format="rpms",
                scmurl=full_url,
                batch=batch,
                ref=pkgref,
                state=1,
                tagged=True,
                tagged_in_final=True,
            )
        )

    db_session.add(module_build)
    db_session.commit()

    # Create shared-userspace-577, state is WAIT, no component built
    scmurl = "https://src.stg.fedoraproject.org/modules/testmodule.git?#7fea453"
    mmd2 = load_mmd(read_staged_data("shared-userspace-577"))
    xmd = mmd2.get_xmd()
    xmd["mbs"]["scmurl"] = scmurl
    xmd["mbs"]["commit"] = "55f4a0a2e6cc255c88712a905157ab39315b8fd8"
    mmd2.set_xmd(xmd)

    module_build = module_build_service.common.models.ModuleBuild(
        name=mmd2.get_module_name(),
        stream=mmd2.get_stream_name(),
        version=mmd2.get_version(),
        build_context=module_build_service.common.models.ModuleBuild.calculate_build_context(
            xmd["mbs"]["buildrequires"]
        ),
        runtime_context="50dd3eb5dde600d072e45d4120e1548ce66bc94a",
        state=BUILD_STATES["done"],
        modulemd=mmd_to_str(mmd2),
        koji_tag="module-shared-userspace-f26-20170605091544-75f92abb",
        scmurl=scmurl,
        batch=0,
        owner="Tom Brady",
        time_submitted=datetime(2017, 2, 15, 16, 8, 18),
        time_modified=datetime(2017, 2, 15, 16, 19, 35),
        time_completed=datetime(2017, 2, 15, 16, 19, 35),
        rebuild_strategy="changed-and-after",
    )

    components2 = [
        mmd2.get_rpm_component(rpm)
        for rpm in mmd2.get_rpm_component_names()
    ]
    # Store components to database in different order than for 570 to
    # reproduce the reusing issue.
    components2.sort(key=lambda x: len(x.get_name()))
    components2.sort(key=lambda x: x.get_buildorder())
    previous_buildorder = None
    batch = 1
    xmd_mbs_rpms = mmd2.get_xmd()["mbs"]["rpms"]
    for pkg in components2:
        # Increment the batch number when buildorder increases.
        if previous_buildorder != pkg.get_buildorder():
            previous_buildorder = pkg.get_buildorder()
            batch += 1

        pkgref = xmd_mbs_rpms[pkg.get_name()]["ref"]
        full_url = pkg.get_repository() + "?#" + pkgref

        module_build.component_builds.append(
            module_build_service.common.models.ComponentBuild(
                package=pkg.get_name(), format="rpms", scmurl=full_url, batch=batch, ref=pkgref)
        )

    db_session.add(module_build)
    db_session.commit()


@pytest.fixture(autouse=True)
def cleanup_build_logs(request):
    """
    Clean up any build logs remaining after each test so that it doesn't affect tests run later.
    """

    def _cleanup_build_logs():
        build_ids = list(module_build_service.common.build_logs.handlers.keys())
        for build_id in build_ids:
            mock_build = mock.Mock()
            mock_build.id = build_id
            module_build_service.common.build_logs.stop(mock_build)

    request.addfinalizer(_cleanup_build_logs)


@pytest.fixture(scope="class")
def provide_test_client(request):
    """Inject REST client into the test class -> self.client"""
    request.cls.client = module_build_service.app.test_client()


@pytest.fixture(autouse=True, scope="session")
def create_database(request):
    """Drop and recreate all tables"""
    clean_database(add_platform_module=False, add_default_arches=False)
