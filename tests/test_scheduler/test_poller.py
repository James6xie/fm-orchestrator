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
from mock import patch
from module_build_service import models, conf
from tests import test_reuse_component_init_data, init_data, db
import mock
import koji
from module_build_service.scheduler.producer import MBSProducer
import six.moves.queue as queue
from datetime import datetime, timedelta

BASE_DIR = path.abspath(path.dirname(__file__))
CASSETTES_DIR = path.join(
    path.abspath(path.dirname(__file__)), '..', 'vcr-request-data')


@patch("module_build_service.builder.GenericBuilder.default_buildroot_groups",
       return_value={'build': [], 'srpm-build': []})
@patch("module_build_service.scheduler.consumer.get_global_consumer")
@patch("module_build_service.builder.KojiModuleBuilder.KojiModuleBuilder.get_session")
@patch("module_build_service.builder.GenericBuilder.create_from_module")
class TestPoller(unittest.TestCase):

    def setUp(self):
        test_reuse_component_init_data()

    def tearDown(self):
        init_data()

    @patch('module_build_service.utils.start_build_component')
    def test_process_paused_module_builds(self, start_build_component, create_builder,
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
        create_builder.return_value = builder

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
        module_build = models.ModuleBuild.query.filter_by(id=2).one()
        db.session.refresh(module_build)

        # Components should be in BUILDING state now.
        components = module_build.current_batch()
        for component in components:
            self.assertEqual(component.state, koji.BUILD_STATES["BUILDING"])
        self.assertEqual(len(start_build_component.mock_calls), 2)

    def test_trigger_new_repo_when_failed(self, create_builder,
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
        create_builder.return_value = builder

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

    def test_trigger_new_repo_when_succeded(self, create_builder,
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
        create_builder.return_value = builder

        # Change the batch to 2, so the module build is in state where
        # it is not building anything, but the state is "build".
        module_build = models.ModuleBuild.query.filter_by(id=2).one()
        module_build.batch = 2
        module_build.new_repo_task_id = 123456
        db.session.commit()

        hub = mock.MagicMock()
        poller = MBSProducer(hub)
        poller.poll()

        # Refresh our module_build object.
        module_build = models.ModuleBuild.query.filter_by(id=2).one()
        db.session.refresh(module_build)

        self.assertTrue(not koji_session.newRepo.called)
        self.assertEqual(module_build.new_repo_task_id, 0)

    def test_process_paused_module_builds_waiting_for_repo(
            self, create_builder, koji_get_session, global_consumer, dbg):
        """
        Tests that process_paused_module_builds does not start new batch
        when we are waiting for repo.
        """
        consumer = mock.MagicMock()
        consumer.incoming = queue.Queue()
        global_consumer.return_value = consumer

        koji_session = mock.MagicMock()
        koji_get_session.return_value = koji_session

        builder = mock.MagicMock()
        create_builder.return_value = builder

        # Change the batch to 2, so the module build is in state where
        # it is not building anything, but the state is "build".
        module_build = models.ModuleBuild.query.filter_by(id=2).one()
        module_build.batch = 2
        module_build.new_repo_task_id = 123456
        db.session.commit()

        # Poll :)
        hub = mock.MagicMock()
        poller = MBSProducer(hub)
        poller.poll()

        # Refresh our module_build object.
        module_build = models.ModuleBuild.query.filter_by(id=2).one()
        db.session.refresh(module_build)

        # Components should not be in building state
        components = module_build.current_batch()
        for component in components:
            self.assertEqual(component.state, None)

    def test_delete_old_koji_targets(
            self, create_builder, koji_get_session, global_consumer, dbg):
        """
        Tests that we delete koji target when time_completed is older than
        koji_target_delete_time value.
        """
        consumer = mock.MagicMock()
        consumer.incoming = queue.Queue()
        global_consumer.return_value = consumer

        for state_name, state in models.BUILD_STATES.items():
            koji_session = mock.MagicMock()
            koji_session.getBuildTargets.return_value = [
                {'dest_tag_name': 'module-tag', 'id': 852, 'name': 'module-tag'},
                {'dest_tag_name': 'f26', 'id': 853, 'name': 'f26'},
                {'dest_tag_name': 'module-tag2', 'id': 853, 'name': 'f26'}]
            koji_get_session.return_value = koji_session

            builder = mock.MagicMock()
            create_builder.return_value = builder

            # Change the batch to 2, so the module build is in state where
            # it is not building anything, but the state is "build".
            module_build = models.ModuleBuild.query.filter_by(id=2).one()
            module_build.state = state
            module_build.koji_tag = "module-tag"
            module_build.time_completed = datetime.utcnow()
            module_build.new_repo_task_id = 123456
            db.session.commit()

            # Poll :)
            hub = mock.MagicMock()
            poller = MBSProducer(hub)
            poller.delete_old_koji_targets(conf, db.session)

            module_build = models.ModuleBuild.query.filter_by(id=2).one()
            db.session.refresh(module_build)
            module_build.time_completed = datetime.utcnow() - timedelta(hours=23)
            db.session.commit()
            poller.delete_old_koji_targets(conf, db.session)

            # deleteBuildTarget should not be called, because time_completed is
            # set to "now".
            self.assertTrue(not koji_session.deleteBuildTarget.called)

            # Try removing non-modular target - should not happen
            db.session.refresh(module_build)
            module_build.koji_tag = "module-tag2"
            module_build.time_completed = datetime.utcnow() - timedelta(hours=25)
            db.session.commit()
            poller.delete_old_koji_targets(conf, db.session)
            self.assertTrue(not koji_session.deleteBuildTarget.called)

            # Refresh our module_build object and set time_completed 25 hours ago
            db.session.refresh(module_build)
            module_build.time_completed = datetime.utcnow() - timedelta(hours=25)
            module_build.koji_tag = "module-tag"
            db.session.commit()

            poller.delete_old_koji_targets(conf, db.session)

            if state_name in ["done", "ready", "failed"]:
                koji_session.deleteBuildTarget.assert_called_once_with(852)

    def test_process_waiting_module_build(self, create_builder, koji_get_session,
                                          global_consumer, dbg):
        """ Test that processing old waiting module builds works. """

        consumer = mock.MagicMock()
        consumer.incoming = queue.Queue()
        global_consumer.return_value = consumer

        hub = mock.MagicMock()
        poller = MBSProducer(hub)

        # Change the batch to 2, so the module build is in state where
        # it is not building anything, but the state is "build".
        module_build = models.ModuleBuild.query.filter_by(id=2).one()
        module_build.state = 1
        original = datetime.utcnow() - timedelta(minutes=11)
        module_build.time_modified = original
        db.session.commit()
        db.session.refresh(module_build)

        # Ensure the queue is empty before we start.
        self.assertEquals(consumer.incoming.qsize(), 0)

        # Poll :)
        poller.process_waiting_module_builds(db.session)

        self.assertEquals(consumer.incoming.qsize(), 1)
        module_build = models.ModuleBuild.query.filter_by(id=2).one()
        # ensure the time_modified was changed.
        self.assertGreater(module_build.time_modified, original)

    def test_process_waiting_module_build_not_old_enough(self, create_builder, koji_get_session,
                                                         global_consumer, dbg):
        """ Test that we do not process young waiting builds. """

        consumer = mock.MagicMock()
        consumer.incoming = queue.Queue()
        global_consumer.return_value = consumer

        hub = mock.MagicMock()
        poller = MBSProducer(hub)

        # Change the batch to 2, so the module build is in state where
        # it is not building anything, but the state is "build".
        module_build = models.ModuleBuild.query.filter_by(id=2).one()
        module_build.state = 1
        original = datetime.utcnow() - timedelta(minutes=9)
        module_build.time_modified = original
        db.session.commit()
        db.session.refresh(module_build)

        # Ensure the queue is empty before we start.
        self.assertEquals(consumer.incoming.qsize(), 0)

        # Poll :)
        poller.process_waiting_module_builds(db.session)

        # Ensure we did *not* process the 9 minute-old build.
        self.assertEquals(consumer.incoming.qsize(), 0)

    def test_process_waiting_module_build_none_found(self, create_builder, koji_get_session,
                                                     global_consumer, dbg):
        """ Test nothing happens when no module builds are waiting. """

        consumer = mock.MagicMock()
        consumer.incoming = queue.Queue()
        global_consumer.return_value = consumer

        hub = mock.MagicMock()
        poller = MBSProducer(hub)

        # Ensure the queue is empty before we start.
        self.assertEquals(consumer.incoming.qsize(), 0)

        # Poll :)
        poller.process_waiting_module_builds(db.session)

        # Ensure we did *not* process any of the non-waiting builds.
        self.assertEquals(consumer.incoming.qsize(), 0)
