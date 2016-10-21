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

import unittest
import mock

import rida.messaging
import rida.scheduler.handlers.repos
import rida.models


class TestRepoDone(unittest.TestCase):

    def setUp(self):
        self.config = mock.Mock()
        self.config.rpms_default_repository = 'dist_git_url'
        self.config.koji_profile = 'staging'  # TODO - point at a fake test config


        self.session = mock.Mock()
        self.fn = rida.scheduler.handlers.repos.done

    @mock.patch('rida.models.ModuleBuild.from_repo_done_event')
    def test_no_match(self, from_repo_done_event):
        """ Test that when a repo msg hits us and we have no match,
        that we do nothing gracefully.
        """
        from_repo_done_event.return_value = None
        msg = rida.messaging.KojiRepoChange(
            'no matches for this...', '2016-some-guid')
        self.fn(config=self.config, session=self.session, msg=msg)

    @mock.patch('rida.builder.KojiModuleBuilder.buildroot_ready')
    @mock.patch('rida.builder.KojiModuleBuilder.get_session')
    @mock.patch('rida.builder.KojiModuleBuilder.build')
    @mock.patch('rida.builder.KojiModuleBuilder.buildroot_connect')
    @mock.patch('rida.models.ModuleBuild.from_repo_done_event')
    def test_a_single_match(self, from_repo_done_event, connect, build_fn, config, ready):
        """ Test that when a repo msg hits us and we have a single match.
        """
        config.return_value = mock.Mock(), "development"
        unbuilt_component_build = mock.Mock()
        unbuilt_component_build.package = 'foo'
        unbuilt_component_build.scmurl = 'full_scm_url'
        unbuilt_component_build.state = None
        built_component_build = mock.Mock()
        built_component_build.package = 'foo2'
        built_component_build.scmurl = 'full_scm_url'
        built_component_build.state = 1
        module_build = mock.Mock()
        module_build.batch = 1
        module_build.component_builds = [unbuilt_component_build, built_component_build]
        module_build.current_batch.return_value = [built_component_build]

        from_repo_done_event.return_value = module_build

        ready.return_value = True

        msg = rida.messaging.KojiRepoChange(
            'no matches for this...', '2016-some-guid')
        self.fn(config=self.config, session=self.session, msg=msg)
        build_fn.assert_called_once_with(artifact_name='foo', source='full_scm_url')


    @mock.patch('rida.builder.KojiModuleBuilder.buildroot_ready')
    @mock.patch('rida.builder.KojiModuleBuilder.get_session')
    @mock.patch('rida.builder.KojiModuleBuilder.build')
    @mock.patch('rida.builder.KojiModuleBuilder.buildroot_connect')
    @mock.patch('rida.models.ModuleBuild.from_repo_done_event')
    def test_a_single_match_build_fail(self, from_repo_done_event, connect, build_fn, config, ready):
        """ Test that when a KojiModuleBuilder.build fails, the build is
        marked as failed with proper state_reason.
        """
        config.return_value = mock.Mock(), "development"
        unbuilt_component_build = mock.Mock()
        unbuilt_component_build.package = 'foo'
        unbuilt_component_build.scmurl = 'full_scm_url'
        unbuilt_component_build.state = None
        built_component_build = mock.Mock()
        built_component_build.package = 'foo2'
        built_component_build.scmurl = 'full_scm_url'
        built_component_build.state = 1
        module_build = mock.Mock()
        module_build.batch = 1
        module_build.component_builds = [unbuilt_component_build, built_component_build]
        module_build.current_batch.return_value = [built_component_build]
        build_fn.return_value = None

        from_repo_done_event.return_value = module_build

        ready.return_value = True

        msg = rida.messaging.KojiRepoChange(
            'no matches for this...', '2016-some-guid')
        self.fn(config=self.config, session=self.session, msg=msg)
        build_fn.assert_called_once_with(artifact_name='foo', source='full_scm_url')
        module_build.transition.assert_called_once_with(self.config,
                                                        rida.models.BUILD_STATES["failed"],
                                                        'Failed to submit artifact foo to Koji')
        self.assertEquals(unbuilt_component_build.state_reason, "Failed to submit to Koji")
