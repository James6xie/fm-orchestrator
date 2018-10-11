import os
import mock
import koji
import tempfile
import shutil
from textwrap import dedent

import kobo.rpmlib

from module_build_service import conf
from module_build_service.models import ModuleBuild, ComponentBuild, make_session
from module_build_service.builder.MockModuleBuilder import MockModuleBuilder
from module_build_service import glib, Modulemd
from tests import clean_database


class TestMockModuleBuilder:

    def setup_method(self, test_method):
        clean_database()
        self.resultdir = tempfile.mkdtemp()

    def teardown_method(self, test_method):
        clean_database()
        shutil.rmtree(self.resultdir)

    def _create_module_with_filters(self, session, batch, state):
        comp_builds = [
            {
                "module_id": 2,
                "package": "ed",
                "format": "rpms",
                "scmurl": ("git://pkgs.fedoraproject.org/rpms/ed"
                           "?#01bf8330812fea798671925cc537f2f29b0bd216"),
                "batch": 2,
                "ref": "01bf8330812fea798671925cc537f2f29b0bd216"
            },
            {
                "module_id": 2,
                "package": "mksh",
                "format": "rpms",
                "scmurl": ("git://pkgs.fedoraproject.org/rpms/mksh"
                           "?#f70fd11ddf96bce0e2c64309706c29156b39141d"),
                "batch": 3,
                "ref": "f70fd11ddf96bce0e2c64309706c29156b39141d"
            },
        ]

        base_dir = os.path.abspath(os.path.dirname(__file__))
        mmd = Modulemd.Module().new_from_file(os.path.join(
            base_dir, '..', 'staged_data', 'testmodule-with-filters.yaml'))
        mmd.upgrade()
        mmd.set_xmd(glib.dict_values({
            'mbs': {
                'rpms': {
                    'ed': {'ref': '01bf8330812fea798671925cc537f2f29b0bd216'},
                    'mksh': {'ref': 'f70fd11ddf96bce0e2c64309706c29156b39141d'}
                },
                'buildrequires':
                {
                    'host': {
                        'version': '20171024133034',
                        'filtered_rpms': [],
                        'stream': 'master',
                        'ref': '6df253bb3c53e84706c01b8ab2d5cac24f0b6d45',
                        'context': '00000000'
                    },
                    'platform': {
                        'version': '20171028112959',
                        'filtered_rpms': [],
                        'stream': 'master',
                        'ref': '4f7787370a931d57421f9f9555fc41c3e31ff1fa',
                        'context': '00000000'
                    }
                },
                'scmurl': 'file:///testdir',
                'commit': '5566bc792ec7a03bb0e28edd1b104a96ba342bd8',
                'requires': {
                    'platform': {
                        'version': '20171028112959',
                        'filtered_rpms': [],
                        'stream': 'master',
                        'ref': '4f7787370a931d57421f9f9555fc41c3e31ff1fa',
                        'context': '00000000'
                    }
                }
            }
        }))
        module = ModuleBuild.create(
            session,
            conf,
            name="mbs-testmodule",
            stream="test",
            version="20171027111452",
            modulemd=mmd.dumps(),
            scmurl="file:///testdir",
            username="test",
        )
        module.koji_tag = "module-mbs-testmodule-test-20171027111452"
        module.batch = batch
        session.add(module)

        for build in comp_builds:
            cb = ComponentBuild(**dict(build, format="rpms", state=state))
            session.add(cb)
            session.commit()
        session.commit()

        return module

    @mock.patch("module_build_service.conf.system", new="mock")
    def test_createrepo_filter_last_batch(self, *args):
        with make_session(conf) as session:
            module = self._create_module_with_filters(session, 3, koji.BUILD_STATES['COMPLETE'])

            builder = MockModuleBuilder("mcurlej", module, conf, module.koji_tag,
                                        module.component_builds)
            builder.resultsdir = self.resultdir
            rpms = [
                "ed-1.14.1-4.module+24957a32.x86_64.rpm",
                "mksh-56b-1.module+24957a32.x86_64.rpm",
                "module-build-macros-0.1-1.module+24957a32.noarch.rpm"
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
                rpm_names = [kobo.rpmlib.parse_nvr(rpm)["name"] for rpm in pkglist.split('\n')]
                assert "ed" not in rpm_names

    @mock.patch("module_build_service.conf.system", new="mock")
    def test_createrepo_not_last_batch(self):
        with make_session(conf) as session:
            module = self._create_module_with_filters(session, 2, koji.BUILD_STATES['COMPLETE'])

            builder = MockModuleBuilder("mcurlej", module, conf, module.koji_tag,
                                        module.component_builds)
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
                rpm_names = [kobo.rpmlib.parse_nvr(rpm)["name"] for rpm in pkglist.split('\n')]
                assert "ed" in rpm_names
