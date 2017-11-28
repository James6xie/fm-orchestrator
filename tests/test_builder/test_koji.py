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
# Written by Jan Kaluza <jkaluza@redhat.com>

import unittest
import mock
import koji
import xmlrpclib

import module_build_service.messaging
import module_build_service.scheduler.handlers.repos
import module_build_service.models
import module_build_service.builder

from mock import patch, MagicMock

from tests import conf, init_data

from module_build_service.builder.KojiModuleBuilder import KojiModuleBuilder


class FakeKojiModuleBuilder(KojiModuleBuilder):

    @module_build_service.utils.retry(wait_on=(xmlrpclib.ProtocolError, koji.GenericError))
    def get_session(self, config, owner):
        koji_session = MagicMock()
        koji_session.getRepo.return_value = {'create_event': 'fake event'}

        def _get_tag(name):
            _id = 2 if name.endswith("build") else 1
            return {"name": name, "id": _id}
        koji_session.getTag = _get_tag

        return koji_session


class TestKojiBuilder(unittest.TestCase):

    def setUp(self):
        init_data()
        self.config = mock.Mock()
        self.config.koji_profile = conf.koji_profile
        self.config.koji_repository_url = conf.koji_repository_url
        self.module = module_build_service.models.ModuleBuild.query.filter_by(id=1).one()

    def test_tag_to_repo(self):
        """ Test that when a repo msg hits us and we have no match,
        that we do nothing gracefully.
        """
        repo = module_build_service.builder.GenericBuilder.tag_to_repo(
            "koji", self.config,
            "module-base-runtime-0.25-9",
            "x86_64")
        self.assertEquals(repo, "https://kojipkgs.stg.fedoraproject.org/repos"
                          "/module-base-runtime-0.25-9/latest/x86_64")

    def test_recover_orphaned_artifact_when_tagged(self):
        """ Test recover_orphaned_artifact when the artifact is found and tagged in both tags
        """
        builder = FakeKojiModuleBuilder(owner=self.module.owner,
                                        module=self.module,
                                        config=conf,
                                        tag_name='module-foo',
                                        components=[])

        builder.module_tag = {"name": "module-foo", "id": 1}
        builder.module_build_tag = {"name": "module-foo-build", "id": 2}

        # Set listTagged to return test data
        build_tagged = [{"nvr": "foo-1.0-1.module+e0095747", "task_id": 12345, 'build_id': 91}]
        dest_tagged = [{"nvr": "foo-1.0-1.module+e0095747", "task_id": 12345, 'build_id': 91}]
        builder.koji_session.listTagged.side_effect = [build_tagged, dest_tagged]
        module_build = module_build_service.models.ModuleBuild.query.get(30)
        component_build = module_build.component_builds[0]
        component_build.task_id = None
        component_build.state = None
        component_build.nvr = None

        actual = builder.recover_orphaned_artifact(component_build)
        self.assertEqual(len(actual), 3)
        self.assertEquals(type(actual[0]), module_build_service.messaging.KojiBuildChange)
        self.assertEquals(actual[0].build_id, 91)
        self.assertEquals(actual[0].task_id, 12345)
        self.assertEquals(actual[0].build_new_state, koji.BUILD_STATES['COMPLETE'])
        self.assertEquals(actual[0].build_name, 'rubygem-rails')
        self.assertEquals(actual[0].build_version, '1.0')
        self.assertEquals(actual[0].build_release, '1.module+e0095747')
        self.assertEquals(actual[0].module_build_id, 30)
        self.assertEquals(type(actual[1]), module_build_service.messaging.KojiTagChange)
        self.assertEquals(actual[1].tag, 'module-foo-build')
        self.assertEquals(actual[1].artifact, 'rubygem-rails')
        self.assertEquals(type(actual[2]), module_build_service.messaging.KojiTagChange)
        self.assertEquals(actual[2].tag, 'module-foo')
        self.assertEquals(actual[2].artifact, 'rubygem-rails')
        self.assertEqual(component_build.state, koji.BUILD_STATES['COMPLETE'])
        self.assertEqual(component_build.task_id, 12345)
        self.assertEqual(component_build.state_reason, 'Found existing build')
        self.assertEquals(builder.koji_session.tagBuild.call_count, 0)

    def test_recover_orphaned_artifact_when_untagged(self):
        """ Tests recover_orphaned_artifact when the build is found but untagged
        """
        builder = FakeKojiModuleBuilder(owner=self.module.owner,
                                        module=self.module,
                                        config=conf,
                                        tag_name='module-foo',
                                        components=[])

        builder.module_tag = {"name": "module-foo", "id": 1}
        builder.module_build_tag = {"name": "module-foo-build", "id": 2}
        # Set listTagged to return test data
        builder.koji_session.listTagged.side_effect = [[], [], []]
        untagged = [{
            "id": 9000,
            "name": "foo",
            "version": "1.0",
            "release": "1.module+e0095747",
        }]
        builder.koji_session.untaggedBuilds.return_value = untagged
        build_info = {
            'nvr': 'foo-1.0-1.module+e0095747',
            'task_id': 12345,
            'build_id': 91
        }
        builder.koji_session.getBuild.return_value = build_info
        module_build = module_build_service.models.ModuleBuild.query.get(30)
        component_build = module_build.component_builds[0]
        component_build.task_id = None
        component_build.nvr = None
        component_build.state = None

        actual = builder.recover_orphaned_artifact(component_build)
        self.assertEqual(len(actual), 1)
        self.assertEquals(type(actual[0]), module_build_service.messaging.KojiBuildChange)
        self.assertEquals(actual[0].build_id, 91)
        self.assertEquals(actual[0].task_id, 12345)
        self.assertEquals(actual[0].build_new_state, koji.BUILD_STATES['COMPLETE'])
        self.assertEquals(actual[0].build_name, 'rubygem-rails')
        self.assertEquals(actual[0].build_version, '1.0')
        self.assertEquals(actual[0].build_release, '1.module+e0095747')
        self.assertEquals(actual[0].module_build_id, 30)
        self.assertEqual(component_build.state, koji.BUILD_STATES['COMPLETE'])
        self.assertEqual(component_build.task_id, 12345)
        self.assertEqual(component_build.state_reason, 'Found existing build')
        builder.koji_session.tagBuild.assert_called_once_with(2, 'foo-1.0-1.module+e0095747')

    def test_recover_orphaned_artifact_when_nothing_exists(self):
        """ Test recover_orphaned_artifact when the build is not found
        """
        builder = FakeKojiModuleBuilder(owner=self.module.owner,
                                        module=self.module,
                                        config=conf,
                                        tag_name='module-foo',
                                        components=[])

        builder.module_tag = {"name": "module-foo", "id": 1}
        builder.module_build_tag = {"name": "module-foo-build", "id": 2}

        # Set listTagged to return nothing...
        tagged = []
        builder.koji_session.listTagged.return_value = tagged
        untagged = [{
            "nvr": "foo-1.0-1.nope",
            "release": "nope",
        }]
        builder.koji_session.untaggedBuilds.return_value = untagged
        module_build = module_build_service.models.ModuleBuild.query.get(30)
        component_build = module_build.component_builds[0]
        component_build.task_id = None
        component_build.nvr = None
        component_build.state = None

        actual = builder.recover_orphaned_artifact(component_build)
        self.assertEqual(actual, [])
        # Make sure nothing erroneous gets tag
        self.assertEquals(builder.koji_session.tagBuild.call_count, 0)

    @patch('koji.util')
    def test_buildroot_ready(self, mocked_kojiutil):

        attrs = {'checkForBuilds.return_value': None,
                 'checkForBuilds.side_effect': IOError}
        mocked_kojiutil.configure_mock(**attrs)
        fake_kmb = FakeKojiModuleBuilder(owner=self.module.owner,
                                         module=self.module,
                                         config=conf,
                                         tag_name='module-nginx-1.2',
                                         components=[])
        fake_kmb.module_target = {'build_tag': 'module-fake_tag'}

        with self.assertRaises(IOError):
            fake_kmb.buildroot_ready()
        self.assertEquals(mocked_kojiutil.checkForBuilds.call_count, 3)

    def test_tagging_already_tagged_artifacts(self):
        """
        Tests that buildroot_add_artifacts and tag_artifacts do not try to
        tag already tagged artifacts
        """
        builder = FakeKojiModuleBuilder(owner=self.module.owner,
                                        module=self.module,
                                        config=conf,
                                        tag_name='module-nginx-1.2',
                                        components=[])

        builder.module_tag = {"name": "module-foo", "id": 1}
        builder.module_build_tag = {"name": "module-foo-build", "id": 2}

        # Set listTagged to return test data
        tagged = [{"nvr": "foo-1.0-1.module_e0095747"},
                  {"nvr": "bar-1.0-1.module_e0095747"}]
        builder.koji_session.listTagged.return_value = tagged

        # Try to tag one artifact which is already tagged and one new ...
        to_tag = ["foo-1.0-1.module_e0095747", "new-1.0-1.module_e0095747"]
        builder.buildroot_add_artifacts(to_tag)

        # ... only new one should be added.
        builder.koji_session.tagBuild.assert_called_once_with(
            builder.module_build_tag["id"], "new-1.0-1.module_e0095747")

        # Try the same for tag_artifacts(...).
        builder.koji_session.tagBuild.reset_mock()
        builder.tag_artifacts(to_tag)
        builder.koji_session.tagBuild.assert_called_once_with(
            builder.module_tag["id"], "new-1.0-1.module_e0095747")

    @patch.object(FakeKojiModuleBuilder, 'get_session')
    @patch.object(FakeKojiModuleBuilder, '_get_tagged_nvrs')
    def test_untagged_artifacts(self, mock_get_tagged_nvrs, mock_get_session):
        """
        Tests that only tagged artifacts will be untagged
        """
        mock_session = mock.Mock()
        mock_session.getTag.side_effect = [
            {'name': 'foobar', 'id': 1}, {'name': 'foobar-build', 'id': 2}]
        mock_get_session.return_value = mock_session
        mock_get_tagged_nvrs.side_effect = [['foo', 'bar'], ['foo']]
        builder = FakeKojiModuleBuilder(
            owner=self.module.owner, module=self.module, config=conf, tag_name='module-foo',
            components=[])

        builder.untag_artifacts(['foo', 'bar'])
        self.assertEqual(mock_session.untagBuild.call_count, 3)
        expected_calls = [mock.call(1, 'foo'), mock.call(2, 'foo'), mock.call(1, 'bar')]
        self.assertEqual(mock_session.untagBuild.mock_calls, expected_calls)

    @patch('module_build_service.builder.KojiModuleBuilder.KojiModuleBuilder.get_session')
    def test_get_build_weights(self, get_session):
        session = MagicMock()
        session.getLoggedInUser.return_value = {"id": 123}
        session.multiCall.side_effect = [
            # getPackageID response
            [[1], [2]],
            # listBuilds response
            [[[{"task_id": 456}]], [[{"task_id": 789}]]],
            # getTaskDescendents response
            [[{'1': [], '2': [], '3': [{'weight': 1.0}, {'weight': 1.0}]}],
             [{'1': [], '2': [], '3': [{'weight': 1.0}, {'weight': 1.0}]}]]
        ]
        get_session.return_value = session

        weights = KojiModuleBuilder.get_build_weights(["httpd", "apr"])
        self.assertEqual(weights, {"httpd": 2, "apr": 2})

        expected_calls = [mock.call(456), mock.call(789)]
        self.assertEqual(session.getTaskDescendents.mock_calls, expected_calls)

    @patch('module_build_service.builder.KojiModuleBuilder.KojiModuleBuilder.get_session')
    def test_get_build_weights_no_task_id(self, get_session):
        session = MagicMock()
        session.getLoggedInUser.return_value = {"id": 123}
        session.multiCall.side_effect = [
            # getPackageID response
            [[1], [2]],
            # listBuilds response
            [[[{"task_id": 456}]], [[{"task_id": None}]]],
            # getTaskDescendents response
            [[{'1': [], '2': [], '3': [{'weight': 1.0}, {'weight': 1.0}]}]]
        ]
        get_session.return_value = session

        weights = KojiModuleBuilder.get_build_weights(["httpd", "apr"])
        self.assertEqual(weights, {"httpd": 2, "apr": 1.5})

        expected_calls = [mock.call(456)]
        self.assertEqual(session.getTaskDescendents.mock_calls, expected_calls)

    @patch('module_build_service.builder.KojiModuleBuilder.KojiModuleBuilder.get_session')
    def test_get_build_weights_no_build(self, get_session):
        session = MagicMock()
        session.getLoggedInUser.return_value = {"id": 123}
        session.multiCall.side_effect = [
            # getPackageID response
            [[1], [2]],
            # listBuilds response
            [[[{"task_id": 456}]], [[]]],
            # getTaskDescendents response
            [[{'1': [], '2': [], '3': [{'weight': 1.0}, {'weight': 1.0}]}]]
        ]
        get_session.return_value = session

        weights = KojiModuleBuilder.get_build_weights(["httpd", "apr"])
        self.assertEqual(weights, {"httpd": 2, "apr": 1.5})

        expected_calls = [mock.call(456)]
        self.assertEqual(session.getTaskDescendents.mock_calls, expected_calls)

    @patch('module_build_service.builder.KojiModuleBuilder.KojiModuleBuilder.get_session')
    def test_get_build_weights_listBuilds_failed(self, get_session):
        session = MagicMock()
        session.getLoggedInUser.return_value = {"id": 123}
        session.multiCall.side_effect = [[[1], [2]], []]
        get_session.return_value = session

        weights = KojiModuleBuilder.get_build_weights(["httpd", "apr"])
        self.assertEqual(weights, {"httpd": 1.5, "apr": 1.5})

        expected_calls = [mock.call(packageID=1, userID=123, state=1,
                                    queryOpts={'limit': 1, 'order': '-build_id'}),
                          mock.call(packageID=2, userID=123, state=1,
                                    queryOpts={'limit': 1, 'order': '-build_id'})]
        self.assertEqual(session.listBuilds.mock_calls, expected_calls)

    @patch('module_build_service.builder.KojiModuleBuilder.KojiModuleBuilder.get_session')
    def test_get_build_weights_getPackageID_failed(self, get_session):
        session = MagicMock()
        session.getLoggedInUser.return_value = {"id": 123}
        session.multiCall.side_effect = [[], []]
        get_session.return_value = session

        weights = KojiModuleBuilder.get_build_weights(["httpd", "apr"])
        self.assertEqual(weights, {"httpd": 1.5, "apr": 1.5})

        expected_calls = [mock.call("httpd"), mock.call("apr")]
        self.assertEqual(session.getPackageID.mock_calls, expected_calls)

    @patch('module_build_service.builder.KojiModuleBuilder.KojiModuleBuilder.get_session')
    def test_get_build_weights_getLoggedInUser_failed(self, get_session):
        weights = KojiModuleBuilder.get_build_weights(["httpd", "apr"])
        self.assertEqual(weights, {"httpd": 1.5, "apr": 1.5})


class TestGetKojiClientSession(unittest.TestCase):

    def setUp(self):
        init_data()
        self.config = mock.Mock()
        self.config.koji_profile = conf.koji_profile
        self.config.koji_config = conf.koji_config
        self.module = module_build_service.models.ModuleBuild.query.filter_by(id=1).one()
        self.tag_name = 'module-fool-1.2'

    @patch.object(koji.ClientSession, 'krb_login')
    def test_proxyuser(self, mocked_krb_login):
        KojiModuleBuilder(owner=self.module.owner,
                          module=self.module,
                          config=self.config,
                          tag_name=self.tag_name,
                          components=[])
        args, kwargs = mocked_krb_login.call_args
        self.assertTrue(set([('proxyuser', self.module.owner)]).issubset(set(kwargs.items())))
