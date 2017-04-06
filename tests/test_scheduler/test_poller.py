# Copyright (c) 2017  Red Hat, Inc.
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

import unittest
from os import path
import vcr
import modulemd
from mock import patch
import module_build_service.utils
import module_build_service.scm
from module_build_service import models, conf
from module_build_service.errors import ProgrammingError, ValidationError
from tests import test_reuse_component_init_data, init_data, db
import mock
from mock import PropertyMock
import koji
import module_build_service.scheduler.handlers.components
from module_build_service.builder import GenericBuilder, KojiModuleBuilder
from module_build_service.scheduler.producer import MBSProducer
import six.moves.queue as queue

BASE_DIR = path.abspath(path.dirname(__file__))
CASSETTES_DIR = path.join(
    path.abspath(path.dirname(__file__)), '..', 'vcr-request-data')

@patch("module_build_service.builder.GenericBuilder.default_buildroot_groups",
       return_value = {'build': [], 'srpm-build': []})
@patch("module_build_service.scheduler.consumer.get_global_consumer")
@patch("module_build_service.builder.KojiModuleBuilder.get_session")
@patch("module_build_service.builder.GenericBuilder.create_from_module")
class TestPoller(unittest.TestCase):

    def setUp(self):
        test_reuse_component_init_data()

    def tearDown(self):
        init_data()

    def test_process_paused_module_builds(self, crete_builder,
                                          koji_get_session, global_consumer,
                                          dbg):
        """
        Tests general use-case of process_paused_module_builds.
        """
        consumer = mock.MagicMock()
        consumer.incoming = queue.Queue()
        global_consumer.return_value = consumer

        koji_session = mock.MagicMock()
        koji_get_session.return_value = koji_session

        builder = mock.MagicMock()
        crete_builder.return_value = builder

        # Change the batch to 2, so the module build is in state where
        # it is not building anything, but the state is "build".
        module_build = models.ModuleBuild.query.filter_by(id=2).one()
        module_build.batch = 2
        db.session.commit()

        # Poll :)
        hub = mock.MagicMock()
        poller = MBSProducer(hub)
        poller.poll()

        # Refresh our module_build object.
        db.session.expunge(module_build)
        module_build = models.ModuleBuild.query.filter_by(id=2).one()

        # Components should be in BUILDING state now.
        components = module_build.current_batch()
        for component in components:
            self.assertEqual(component.state, koji.BUILD_STATES["BUILDING"])

    def test_trigger_new_repo_when_failed(self, crete_builder,
                                          koji_get_session, global_consumer,
                                          dbg):
        """
        Tests that we call koji_sesion.newRepo when newRepo task failed.
        """
        consumer = mock.MagicMock()
        consumer.incoming = queue.Queue()
        global_consumer.return_value = consumer

        koji_session = mock.MagicMock()
        koji_session.getTag = lambda tag_name: {'name': tag_name}
        koji_session.getTaskInfo.return_value = {'state': koji.TASK_STATES['FAILED']}
        koji_session.newRepo.return_value = 123456
        koji_get_session.return_value = koji_session

        builder = mock.MagicMock()
        builder.buildroot_ready.return_value = False
        crete_builder.return_value = builder

        # Change the batch to 2, so the module build is in state where
        # it is not building anything, but the state is "build".
        module_build = models.ModuleBuild.query.filter_by(id=2).one()
        module_build.batch = 2
        module_build.new_repo_task_id = 123456
        db.session.commit()

        hub = mock.MagicMock()
        poller = MBSProducer(hub)
        poller.poll()

        koji_session.newRepo.assert_called_once_with("module-testmodule-build")


    def test_trigger_new_repo_when_succeded(self, crete_builder,
                                          koji_get_session, global_consumer,
                                          dbg):
        """
        Tests that we do not call koji_sesion.newRepo when newRepo task
        succeeded.
        """
        consumer = mock.MagicMock()
        consumer.incoming = queue.Queue()
        global_consumer.return_value = consumer

        koji_session = mock.MagicMock()
        koji_session.getTag = lambda tag_name: {'name': tag_name}
        koji_session.getTaskInfo.return_value = {'state': koji.TASK_STATES['CLOSED']}
        koji_session.newRepo.return_value = 123456
        koji_get_session.return_value = koji_session

        builder = mock.MagicMock()
        builder.buildroot_ready.return_value = False
        crete_builder.return_value = builder

        # Change the batch to 2, so the module build is in state where
        # it is not building anything, but the state is "build".
        module_build = models.ModuleBuild.query.filter_by(id=2).one()
        module_build.batch = 2
        module_build.new_repo_task_id = 123456
        db.session.commit()

        hub = mock.MagicMock()
        poller = MBSProducer(hub)
        poller.poll()

        self.assertTrue(not koji_session.newRepo.called)

