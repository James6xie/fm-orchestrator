# Copyright (c) 2018  Red Hat, Inc.
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

import koji
import os
import pytest

from datetime import datetime

import module_build_service

from module_build_service import conf
from module_build_service.models import make_db_session, BUILD_STATES
from module_build_service.utils.general import mmd_to_str, load_mmd, get_rpm_release
from tests import clean_database, read_staged_data, module_build_from_modulemd

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


@pytest.fixture()
def db_session():
    with make_db_session(conf) as db_session:
        yield db_session


@pytest.fixture()
def model_tests_init_data(db_session):
    """Initialize data for model tests

    This is refactored from tests/test_models/__init__.py, which was able to be
    called directly inside setup_method generally.

    The reason to convert it to this fixture is to use fixture ``db_session``
    rather than create a new one. That would also benefit the whole test suite
    to reduce the number of SQLAlchemy session objects.
    """
    clean_database()

    model_test_data_dir = os.path.join(os.path.dirname(__file__), "test_models", "data")

    for filename in os.listdir(model_test_data_dir):
        with open(os.path.join(model_test_data_dir, filename), "r") as f:
            yaml = f.read()
        build = module_build_from_modulemd(yaml)
        db_session.add(build)

    db_session.commit()


@pytest.fixture()
def reuse_component_init_data(db_session):
    clean_database()

    mmd = load_mmd(read_staged_data("formatted_testmodule"))

    build_one = module_build_service.models.ModuleBuild(
        name="testmodule",
        stream="master",
        version='20170109091357',
        state=BUILD_STATES["ready"],
        runtime_context="ac4de1c346dcf09ce77d38cd4e75094ec1c08eb0",
        build_context="ac4de1c346dcf09ce77d38cd4e75094ec1c08eb1",
        context="78e4a6fd",
        koji_tag="module-testmodule-master-20170109091357-78e4a6fd",
        scmurl="https://src.stg.fedoraproject.org/modules/testmodule.git?#ff1ea79",
        batch=3,
        owner="Tom Brady",
        time_submitted=datetime(2017, 2, 15, 16, 8, 18),
        time_modified=datetime(2017, 2, 15, 16, 19, 35),
        time_completed=datetime(2017, 2, 15, 16, 19, 35),
        rebuild_strategy="changed-and-after",
    )

    build_one_component_release = get_rpm_release(db_session, build_one)

    mmd.set_version(int(build_one.version))
    xmd = mmd.get_xmd()
    xmd["mbs"]["scmurl"] = build_one.scmurl
    xmd["mbs"]["commit"] = "ff1ea79fc952143efeed1851aa0aa006559239ba"
    mmd.set_xmd(xmd)
    build_one.modulemd = mmd_to_str(mmd)
    build_one.build_context = module_build_service.models.ModuleBuild.contexts_from_mmd(
        build_one.modulemd
    ).build_context

    db_session.add(build_one)
    db_session.commit()
    db_session.refresh(build_one)

    platform_br = module_build_service.models.ModuleBuild.get_by_id(db_session, 1)
    build_one.buildrequires.append(platform_br)

    arch = db_session.query(module_build_service.models.ModuleArch).get(1)
    build_one.arches.append(arch)

    db_session.add_all([
        module_build_service.models.ComponentBuild(
            module_id=build_one.id,
            package="perl-Tangerine",
            scmurl="https://src.fedoraproject.org/rpms/perl-Tangerine"
                   "?#4ceea43add2366d8b8c5a622a2fb563b625b9abf",
            format="rpms",
            task_id=90276227,
            state=koji.BUILD_STATES["COMPLETE"],
            nvr="perl-Tangerine-0.23-1.{0}".format(build_one_component_release),
            batch=2,
            ref="4ceea43add2366d8b8c5a622a2fb563b625b9abf",
            tagged=True,
            tagged_in_final=True,
        ),
        module_build_service.models.ComponentBuild(
            module_id=build_one.id,
            package="perl-List-Compare",
            scmurl="https://src.fedoraproject.org/rpms/perl-List-Compare"
                   "?#76f9d8c8e87eed0aab91034b01d3d5ff6bd5b4cb",
            format="rpms",
            task_id=90276228,
            state=koji.BUILD_STATES["COMPLETE"],
            nvr="perl-List-Compare-0.53-5.{0}".format(build_one_component_release),
            batch=2,
            ref="76f9d8c8e87eed0aab91034b01d3d5ff6bd5b4cb",
            tagged=True,
            tagged_in_final=True,
        ),
        module_build_service.models.ComponentBuild(
            module_id=build_one.id,
            package="tangerine",
            scmurl="https://src.fedoraproject.org/rpms/tangerine"
                   "?#fbed359411a1baa08d4a88e0d12d426fbf8f602c",
            format="rpms",
            task_id=90276315,
            state=koji.BUILD_STATES["COMPLETE"],
            nvr="tangerine-0.22-3.{0}".format(build_one_component_release),
            batch=3,
            ref="fbed359411a1baa08d4a88e0d12d426fbf8f602c",
            tagged=True,
            tagged_in_final=True,
        ),
        module_build_service.models.ComponentBuild(
            module_id=build_one.id,
            package="module-build-macros",
            scmurl="/tmp/module_build_service-build-macrosqr4AWH/SRPMS/module-build-"
                   "macros-0.1-1.module_testmodule_master_20170109091357.src.rpm",
            format="rpms",
            task_id=90276181,
            state=koji.BUILD_STATES["COMPLETE"],
            nvr="module-build-macros-0.1-1.{0}".format(build_one_component_release),
            batch=1,
            tagged=True,
            build_time_only=True,
        ),
    ])
    # Commit component builds added to build_one
    db_session.commit()

    build_two = module_build_service.models.ModuleBuild(
        name="testmodule",
        stream="master",
        version='20170219191323',
        state=BUILD_STATES["build"],
        runtime_context="ac4de1c346dcf09ce77d38cd4e75094ec1c08eb0",
        build_context="ac4de1c346dcf09ce77d38cd4e75094ec1c08eb1",
        context="c40c156c",
        koji_tag="module-testmodule-master-20170219191323-c40c156c",
        scmurl="https://src.stg.fedoraproject.org/modules/testmodule.git?#55f4a0a",
        batch=1,
        owner="Tom Brady",
        time_submitted=datetime(2017, 2, 19, 16, 8, 18),
        time_modified=datetime(2017, 2, 19, 16, 8, 18),
        rebuild_strategy="changed-and-after",
    )

    build_two_component_release = get_rpm_release(db_session, build_two)

    mmd.set_version(int(build_one.version))
    xmd = mmd.get_xmd()
    xmd["mbs"]["scmurl"] = build_one.scmurl
    xmd["mbs"]["commit"] = "55f4a0a2e6cc255c88712a905157ab39315b8fd8"
    mmd.set_xmd(xmd)
    build_two.modulemd = mmd_to_str(mmd)
    build_two.build_context = module_build_service.models.ModuleBuild.contexts_from_mmd(
        build_two.modulemd
    ).build_context

    db_session.add(build_two)
    db_session.commit()
    db_session.refresh(build_two)

    build_two.arches.append(arch)
    build_two.buildrequires.append(platform_br)

    db_session.add_all([
        module_build_service.models.ComponentBuild(
            module_id=build_two.id,
            package="perl-Tangerine",
            scmurl="https://src.fedoraproject.org/rpms/perl-Tangerine"
                   "?#4ceea43add2366d8b8c5a622a2fb563b625b9abf",
            format="rpms",
            batch=2,
            ref="4ceea43add2366d8b8c5a622a2fb563b625b9abf",
        ),
        module_build_service.models.ComponentBuild(
            module_id=build_two.id,
            package="perl-List-Compare",
            scmurl="https://src.fedoraproject.org/rpms/perl-List-Compare"
                   "?#76f9d8c8e87eed0aab91034b01d3d5ff6bd5b4cb",
            format="rpms",
            batch=2,
            ref="76f9d8c8e87eed0aab91034b01d3d5ff6bd5b4cb",
        ),
        module_build_service.models.ComponentBuild(
            module_id=build_two.id,
            package="tangerine",
            scmurl="https://src.fedoraproject.org/rpms/tangerine"
                   "?#fbed359411a1baa08d4a88e0d12d426fbf8f602c",
            format="rpms",
            batch=3,
            ref="fbed359411a1baa08d4a88e0d12d426fbf8f602c",
        ),
        module_build_service.models.ComponentBuild(
            module_id=build_two.id,
            package="module-build-macros",
            scmurl="/tmp/module_build_service-build-macrosqr4AWH/SRPMS/module-build-"
                   "macros-0.1-1.module_testmodule_master_20170219191323.src.rpm",
            format="rpms",
            task_id=90276186,
            state=koji.BUILD_STATES["COMPLETE"],
            nvr="module-build-macros-0.1-1.{0}".format(build_two_component_release),
            batch=1,
            tagged=True,
            build_time_only=True,
        ),
    ])
    db_session.commit()


@pytest.fixture()
def reuse_shared_userspace_init_data(db_session):
    clean_database()

    # Create shared-userspace-570, state is COMPLETE, all components
    # are properly built.
    mmd = load_mmd(read_staged_data("shared-userspace-570"))

    module_build = module_build_service.models.ModuleBuild(
        name=mmd.get_module_name(),
        stream=mmd.get_stream_name(),
        version=mmd.get_version(),
        build_context="e046b867a400a06a3571f3c71142d497895fefbe",
        runtime_context="50dd3eb5dde600d072e45d4120e1548ce66bc94a",
        state=BUILD_STATES["ready"],
        modulemd=mmd_to_str(mmd),
        koji_tag="module-shared-userspace-f26-20170601141014-75f92abb",
        scmurl="https://src.stg.fedoraproject.org/modules/testmodule.git?#7fea453",
        batch=16,
        owner="Tom Brady",
        time_submitted=datetime(2017, 2, 15, 16, 8, 18),
        time_modified=datetime(2017, 2, 15, 16, 19, 35),
        time_completed=datetime(2017, 2, 15, 16, 19, 35),
        rebuild_strategy="changed-and-after",
    )

    xmd = mmd.get_xmd()
    xmd["mbs"]["scmurl"] = module_build.scmurl
    xmd["mbs"]["commit"] = "55f4a0a2e6cc255c88712a905157ab39315b8fd8"
    mmd.set_xmd(xmd)
    module_build.modulemd = mmd_to_str(mmd)
    module_build.build_context = module_build_service.models.ModuleBuild.contexts_from_mmd(
        module_build.modulemd
    ).build_context

    components = [
        mmd.get_rpm_component(rpm)
        for rpm in mmd.get_rpm_component_names()
    ]
    components.sort(key=lambda x: x.get_buildorder())
    previous_buildorder = None
    batch = 1
    for pkg in components:
        # Increment the batch number when buildorder increases.
        if previous_buildorder != pkg.get_buildorder():
            previous_buildorder = pkg.get_buildorder()
            batch += 1

        pkgref = mmd.get_xmd()["mbs"]["rpms"][pkg.get_name()]["ref"]
        full_url = pkg.get_repository() + "?#" + pkgref

        module_build.component_builds.append(
            module_build_service.models.ComponentBuild(
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
    mmd2 = load_mmd(read_staged_data("shared-userspace-577"))

    module_build = module_build_service.models.ModuleBuild(
        name=mmd2.get_module_name(),
        stream=mmd2.get_stream_name(),
        version=mmd2.get_version(),
        build_context="e046b867a400a06a3571f3c71142d497895fefbe",
        runtime_context="50dd3eb5dde600d072e45d4120e1548ce66bc94a",
        state=BUILD_STATES["done"],
        modulemd=mmd_to_str(mmd2),
        koji_tag="module-shared-userspace-f26-20170605091544-75f92abb",
        scmurl="https://src.stg.fedoraproject.org/modules/testmodule.git?#7fea453",
        batch=0,
        owner="Tom Brady",
        time_submitted=datetime(2017, 2, 15, 16, 8, 18),
        time_modified=datetime(2017, 2, 15, 16, 19, 35),
        time_completed=datetime(2017, 2, 15, 16, 19, 35),
        rebuild_strategy="changed-and-after",
    )

    xmd = mmd2.get_xmd()
    xmd["mbs"]["scmurl"] = module_build.scmurl
    xmd["mbs"]["commit"] = "55f4a0a2e6cc255c88712a905157ab39315b8fd8"
    mmd2.set_xmd(xmd)
    module_build.modulemd = mmd_to_str(mmd2)
    module_build.build_context = module_build_service.models.ModuleBuild.contexts_from_mmd(
        module_build.modulemd
    ).build_context

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
    for pkg in components2:
        # Increment the batch number when buildorder increases.
        if previous_buildorder != pkg.get_buildorder():
            previous_buildorder = pkg.get_buildorder()
            batch += 1

        pkgref = mmd2.get_xmd()["mbs"]["rpms"][pkg.get_name()]["ref"]
        full_url = pkg.get_repository() + "?#" + pkgref

        module_build.component_builds.append(
            module_build_service.models.ComponentBuild(
                package=pkg.get_name(), format="rpms", scmurl=full_url, batch=batch, ref=pkgref)
        )

    db_session.add(module_build)
    db_session.commit()
