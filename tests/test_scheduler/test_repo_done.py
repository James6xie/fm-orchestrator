# Copyright (c) 2016  Red Hat, Inc.
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
# Written by Ralph Bean <rbean@redhat.com>

from os.path import dirname
import unittest
import mock
import vcr

import module_build_service.messaging
import module_build_service.scheduler.handlers.repos
import module_build_service.models
from tests import scheduler_init_data
from tests import conf, db, app

base_dir = dirname(dirname(__file__))
cassette_dir = base_dir + '/vcr-request-data/'


class TestRepoDone(unittest.TestCase):

    def setUp(self):
        scheduler_init_data()

        filename = cassette_dir + self.id()
        self.vcr = vcr.use_cassette(filename)
        self.vcr.__enter__()

    def tearDown(self):
        self.vcr.__exit__()

    @mock.patch('module_build_service.models.ModuleBuild.from_repo_done_event')
    def test_no_match(self, from_repo_done_event):
        """ Test that when a repo msg hits us and we have no match,
        that we do nothing gracefully.
        """
        from_repo_done_event.return_value = None
        msg = module_build_service.messaging.KojiRepoChange(
            'no matches for this...', '2016-some-nonexistent-build')
        module_build_service.scheduler.handlers.repos.done(
            config=conf, session=db.session, msg=msg)

    @mock.patch('module_build_service.builder.KojiModuleBuilder.'
                'KojiModuleBuilder.get_average_build_time',
                return_value=0.0)
    @mock.patch('module_build_service.builder.KojiModuleBuilder.'
                'KojiModuleBuilder.list_tasks_for_components',
                return_value=[])
    @mock.patch('module_build_service.builder.KojiModuleBuilder.'
                'KojiModuleBuilder.buildroot_ready', return_value=True)
    @mock.patch('module_build_service.builder.KojiModuleBuilder.'
                'KojiModuleBuilder.get_session')
    @mock.patch('module_build_service.builder.KojiModuleBuilder.'
                'KojiModuleBuilder.build')
    @mock.patch('module_build_service.builder.KojiModuleBuilder.'
                'KojiModuleBuilder.buildroot_connect')
    def test_a_single_match(self, connect, build_fn, get_session, ready, list_tasks_fn, mock_gabt):
        """ Test that when a repo msg hits us and we have a single match.
        """
        get_session.return_value = mock.Mock(), 'development'
        build_fn.return_value = 1234, 1, '', None

        msg = module_build_service.messaging.KojiRepoChange(
            'some_msg_id', 'module-starcommand-1.3-build')
        module_build_service.scheduler.handlers.repos.done(
            config=conf, session=db.session, msg=msg)
        build_fn.assert_called_once_with(
            artifact_name='communicator',
            source=('git://pkgs.domain.local/rpms/communicator'
                    '?#da95886c8a443b36a9ce31abda1f9bed22f2f9c2'))

    @mock.patch('module_build_service.builder.KojiModuleBuilder.'
                'KojiModuleBuilder.get_average_build_time',
                return_value=0.0)
    @mock.patch('module_build_service.builder.KojiModuleBuilder.'
                'KojiModuleBuilder.list_tasks_for_components',
                return_value=[])
    @mock.patch('module_build_service.builder.KojiModuleBuilder.'
                'KojiModuleBuilder.buildroot_ready', return_value=True)
    @mock.patch('module_build_service.builder.KojiModuleBuilder.'
                'KojiModuleBuilder.get_session')
    @mock.patch('module_build_service.builder.KojiModuleBuilder.'
                'KojiModuleBuilder.build')
    @mock.patch('module_build_service.builder.KojiModuleBuilder.'
                'KojiModuleBuilder.buildroot_connect')
    def test_a_single_match_build_fail(self, connect, build_fn, config, ready, list_tasks_fn,
                                       mock_gabt):
        """ Test that when a KojiModuleBuilder.build fails, the build is
        marked as failed with proper state_reason.
        """
        config.return_value = mock.Mock(), 'development'
        build_fn.return_value = None, 4, 'Failed to submit artifact communicator to Koji', None

        msg = module_build_service.messaging.KojiRepoChange(
            'some_msg_id', 'module-starcommand-1.3-build')
        module_build_service.scheduler.handlers.repos.done(
            config=conf, session=db.session, msg=msg)
        build_fn.assert_called_once_with(
            artifact_name='communicator',
            source=('git://pkgs.domain.local/rpms/communicator'
                    '?#da95886c8a443b36a9ce31abda1f9bed22f2f9c2'))
        component_build = module_build_service.models.ComponentBuild.query\
            .filter_by(package='communicator').one()
        self.assertEquals(component_build.state_reason,
                          'Failed to submit artifact communicator to Koji')

    @mock.patch('module_build_service.scheduler.handlers.repos.log.info')
    def test_erroneous_regen_repo_received(self, mock_log_info):
        """ Test that when an unexpected KojiRepoRegen message is received, the module doesn't
        complete or go to the next build batch.
        """
        scheduler_init_data(1)
        msg = module_build_service.messaging.KojiRepoChange(
            'some_msg_id', 'module-starcommand-1.3-build')
        component_build = module_build_service.models.ComponentBuild.query\
            .filter_by(package='communicator').one()
        component_build.tagged = False
        db.session.add(component_build)
        db.session.commit()
        module_build_service.scheduler.handlers.repos.done(
            config=conf, session=db.session, msg=msg)
        mock_log_info.assert_called_once_with(
            'Ignoring repo regen, because not all components are tagged.')
        module_build = module_build_service.models.ModuleBuild.query.get(1)
        # Make sure the module build didn't transition since all the components weren't tagged
        self.assertEqual(module_build.state, module_build_service.models.BUILD_STATES['build'])

    @mock.patch('module_build_service.builder.KojiModuleBuilder.'
                'KojiModuleBuilder.list_tasks_for_components',
                return_value=[])
    @mock.patch('module_build_service.builder.KojiModuleBuilder.'
                'KojiModuleBuilder.buildroot_ready', return_value=True)
    @mock.patch('module_build_service.builder.KojiModuleBuilder.'
                'KojiModuleBuilder.get_session')
    @mock.patch('module_build_service.builder.KojiModuleBuilder.'
                'KojiModuleBuilder.build')
    @mock.patch('module_build_service.builder.KojiModuleBuilder.'
                'KojiModuleBuilder.buildroot_connect')
    @mock.patch("module_build_service.builder.GenericBuilder.default_buildroot_groups",
                return_value={'build': [], 'srpm-build': []})
    def test_failed_component_build(self, dbg, connect, build_fn, config, ready, list_tasks_fn):
        """ Test that when a KojiModuleBuilder.build fails, the build is
        marked as failed with proper state_reason.
        """
        with app.app_context():
            scheduler_init_data(3)
            config.return_value = mock.Mock(), 'development'
            build_fn.return_value = None, 4, 'Failed to submit artifact communicator to Koji', None

            msg = module_build_service.messaging.KojiRepoChange(
                'some_msg_id', 'module-starcommand-1.3-build')
            module_build_service.scheduler.handlers.repos.done(
                config=conf, session=db.session, msg=msg)
            module_build = module_build_service.models.ModuleBuild.query\
                .filter_by(name='starcommand').one()

            self.assertEquals(module_build.state,
                              module_build_service.models.BUILD_STATES["failed"])
