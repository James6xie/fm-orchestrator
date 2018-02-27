# Copyright (c) 2017 Red Hat, Inc.
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

import os

from mock import patch, PropertyMock
from gi.repository import GLib

from tests import conf, clean_database
from tests.test_views.test_views import FakeSCM
import module_build_service.messaging
import module_build_service.scheduler.handlers.modules
from module_build_service import build_logs
from module_build_service.models import make_session, ModuleBuild, ComponentBuild


class TestModuleInit:

    def setup_method(self, test_method):
        self.fn = module_build_service.scheduler.handlers.modules.init
        self.staged_data_dir = os.path.join(
            os.path.dirname(__file__), '../', 'staged_data')
        testmodule_yml_path = os.path.join(
            self.staged_data_dir, 'testmodule.yaml')
        with open(testmodule_yml_path, 'r') as f:
            yaml = f.read()
        scmurl = 'git://pkgs.domain.local/modules/testmodule?#620ec77'
        clean_database()
        with make_session(conf) as session:
            ModuleBuild.create(
                session, conf, 'testmodule', '1', 3, yaml, scmurl, 'mprahl')

    def teardown_method(self, test_method):
        try:
            path = build_logs.path(1)
            os.remove(path)
        except Exception:
            pass

    @patch('module_build_service.scm.SCM')
    def test_init_basic(self, mocked_scm, pdc):
        FakeSCM(mocked_scm, 'testmodule', 'testmodule.yaml',
                '620ec77321b2ea7b0d67d82992dda3e1d67055b4')
        msg = module_build_service.messaging.MBSModule(
            msg_id=None, module_build_id=1, module_build_state='init')
        with make_session(conf) as session:
            self.fn(config=conf, session=session, msg=msg)
        build = ModuleBuild.query.filter_by(id=1).one()
        # Make sure the module entered the wait state
        assert build.state == 1, build.state
        # Make sure format_mmd was run properly
        assert type(build.mmd().get_xmd()['mbs']) is GLib.Variant

    @patch('module_build_service.scm.SCM')
    def test_init_scm_not_available(self, mocked_scm, pdc):
        def mocked_scm_get_latest():
            raise RuntimeError("Failed in mocked_scm_get_latest")

        FakeSCM(mocked_scm, 'testmodule', 'testmodule.yaml',
                '620ec77321b2ea7b0d67d82992dda3e1d67055b4')
        mocked_scm.return_value.get_latest = mocked_scm_get_latest
        msg = module_build_service.messaging.MBSModule(
            msg_id=None, module_build_id=1, module_build_state='init')
        with make_session(conf) as session:
            self.fn(config=conf, session=session, msg=msg)
        build = ModuleBuild.query.filter_by(id=1).one()
        # Make sure the module entered the failed state
        # since the git server is not available
        assert build.state == 4, build.state

    @patch("module_build_service.config.Config.modules_allow_repository",
           new_callable=PropertyMock, return_value=True)
    @patch('module_build_service.scm.SCM')
    def test_init_includedmodule(self, mocked_scm, mocked_mod_allow_repo, pdc):
        FakeSCM(mocked_scm, "includedmodules", ['testmodule.yaml'])
        includedmodules_yml_path = os.path.join(
            self.staged_data_dir, 'includedmodules.yaml')
        with open(includedmodules_yml_path, 'r') as f:
            yaml = f.read()
        scmurl = 'git://pkgs.domain.local/modules/includedmodule?#da95886'
        with make_session(conf) as session:
            ModuleBuild.create(
                session, conf, 'includemodule', '1', 3, yaml, scmurl, 'mprahl')
            msg = module_build_service.messaging.MBSModule(
                msg_id=None, module_build_id=2, module_build_state='init')
            self.fn(config=conf, session=session, msg=msg)
        build = ModuleBuild.query.filter_by(id=2).one()
        assert build.state == 1
        assert build.name == 'includemodule'
        batches = {}
        for comp_build in ComponentBuild.query.filter_by(module_id=2).all():
            batches[comp_build.package] = comp_build.batch
        assert batches['perl-List-Compare'] == 2
        assert batches['perl-Tangerine'] == 2
        assert batches['foo'] == 2
        assert batches['tangerine'] == 3
        assert batches['file'] == 4
        # Test that the RPMs are properly merged in xmd
        xmd_rpms = {
            'perl-List-Compare': {'ref': '4f26aeafdb'},
            'perl-Tangerine': {'ref': '4f26aeafdb'},
            'tangerine': {'ref': '4f26aeafdb'},
            'foo': {'ref': '93dea37599'},
            'file': {'ref': 'a2740663f8'},
        }
        assert build.mmd().get_xmd()['mbs']['rpms'] == xmd_rpms

    @patch('module_build_service.models.ModuleBuild.from_module_event')
    @patch('module_build_service.scm.SCM')
    def test_init_when_get_latest_raises(self, mocked_scm, mocked_from_module_event, pdc):
        FakeSCM(mocked_scm, 'testmodule', 'testmodule.yaml',
                '7035bd33614972ac66559ac1fdd019ff6027ad22',
                get_latest_raise=True)
        msg = module_build_service.messaging.MBSModule(
            msg_id=None, module_build_id=1, module_build_state='init')
        with make_session(conf) as session:
            build = session.query(ModuleBuild).filter_by(id=1).one()
            mocked_from_module_event.return_value = build
            self.fn(config=conf, session=session, msg=msg)
            # Query the database again to make sure the build object is updated
            session.refresh(build)
            # Make sure the module entered the failed state
            assert build.state == 4, build.state
            assert 'Failed to get the latest commit for' in build.state_reason
