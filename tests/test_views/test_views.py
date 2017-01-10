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
# Written by Matt Prahl <mprahl@redhat.com

import unittest
import json
import time
from mock import patch
from shutil import copyfile
from os import path, mkdir

import modulemd as _modulemd

from tests import app, init_data
from module_build_service.models import ComponentBuild
import module_build_service.scm

class MockedSCM(object):
    def __init__(self, mocked_scm, name, mmd_filenames):
        """
        Adds default testing checkout, get_latest and name methods
        to mocked_scm SCM class.

        :param mmd_filenames: List of ModuleMetadata yaml files which
        will be checkouted by the SCM class in the same order as they
        are stored in the list.
        """
        self.mocked_scm = mocked_scm
        self.name = name
        if not isinstance(mmd_filenames, list):
            mmd_filenames = [mmd_filenames]
        self.mmd_filenames = mmd_filenames
        self.checkout_id = 0

        self.mocked_scm.return_value.checkout = self.checkout
        self.mocked_scm.return_value.name = self.name
        self.mocked_scm.return_value.get_latest = self.get_latest
        self.mocked_scm.return_value.repository_root = "git://pkgs.stg.fedoraproject.org/modules/"

    def checkout(self, temp_dir):
        try:
            mmd_filename = self.mmd_filenames[self.checkout_id]
        except:
            mmd_filename = self.mmd_filenames[0]

        scm_dir = path.join(temp_dir, self.name)
        mkdir(scm_dir)
        base_dir = path.abspath(path.dirname(__file__))
        copyfile(path.join(base_dir, mmd_filename),
                    path.join(scm_dir, self.name + ".yaml"))

        self.checkout_id += 1

        return scm_dir

    def get_latest(self, branch = 'master'):
        return branch


class TestViews(unittest.TestCase):

    def setUp(self):
        self.client = app.test_client()
        init_data()

    def test_query_build(self):
        rv = self.client.get('/module-build-service/1/module-builds/1')
        data = json.loads(rv.data)
        self.assertEquals(data['id'], 1)
        self.assertEquals(data['name'], 'nginx')
        self.assertEquals(data['owner'], 'Moe Szyslak')
        self.assertEquals(data['state'], 3)
        self.assertEquals(data['state_reason'], None)
        self.assertEquals(data['tasks'], {
                'rpms/module-build-macros': '12312321/1',
                'rpms/nginx': '12312345/1'
            }
        )
        self.assertEquals(data['time_completed'], '2016-09-03T11:25:32Z')
        self.assertEquals(data['time_modified'], '2016-09-03T11:25:32Z')
        self.assertEquals(data['time_submitted'], '2016-09-03T11:23:20Z')

    def test_pagination_metadata(self):
        rv = self.client.get('/module-build-service/1/module-builds/?per_page=8&page=2')
        meta_data = json.loads(rv.data)['meta']
        self.assertTrue(
            'module-build-service/1/module-builds/?per_page=8&page=1' in meta_data['prev'])
        self.assertTrue(
            'module-build-service/1/module-builds/?per_page=8&page=3' in meta_data['next'])
        self.assertTrue(
            'module-build-service/1/module-builds/?per_page=8&page=4' in meta_data['last'])
        self.assertTrue(
            'module-build-service/1/module-builds/?per_page=8&page=1' in meta_data['first'])
        self.assertEquals(meta_data['total'], 30)
        self.assertEquals(meta_data['per_page'], 8)
        self.assertEquals(meta_data['pages'], 4)
        self.assertEquals(meta_data['page'], 2)

    def test_query_builds(self):
        rv = self.client.get('/module-build-service/1/module-builds/?per_page=2')
        items = json.loads(rv.data)['items']
        self.assertEquals(items,
                          [{u'state': 3, u'id': 1}, {u'state': 3, u'id': 2}])

    def test_query_builds_verbose(self):
        rv = self.client.get('/module-build-service/1/module-builds/?per_page=2&verbose=True')
        item = json.loads(rv.data)['items'][0]
        self.assertEquals(item['id'], 1)
        self.assertEquals(item['name'], 'nginx')
        self.assertEquals(item['owner'], 'Moe Szyslak')
        self.assertEquals(item['state'], 3)
        self.assertEquals(item['tasks'], {
                'rpms/module-build-macros': '12312321/1',
                'rpms/nginx': '12312345/1'
            }
        )
        self.assertEquals(item['time_completed'], '2016-09-03T11:25:32Z')
        self.assertEquals(item['time_modified'], '2016-09-03T11:25:32Z')
        self.assertEquals(item['time_submitted'], '2016-09-03T11:23:20Z')

    def test_query_builds_filter_name(self):
        rv = self.client.get('/module-build-service/1/module-builds/?name=nginx')
        data = json.loads(rv.data)
        self.assertEquals(data['meta']['total'], 10)

    def test_query_builds_filter_completed_before(self):
        rv = self.client.get(
            '/module-build-service/1/module-builds/?completed_before=2016-09-03T11:30:00Z')
        data = json.loads(rv.data)
        self.assertEquals(data['meta']['total'], 2)

    def test_query_builds_filter_completed_after(self):
        rv = self.client.get(
            '/module-build-service/1/module-builds/?completed_after=2016-09-03T12:25:00Z')
        data = json.loads(rv.data)
        self.assertEquals(data['meta']['total'], 8)

    def test_query_builds_filter_submitted_before(self):
        rv = self.client.get(
            '/module-build-service/1/module-builds/?submitted_before=2016-09-03T12:25:00Z')
        data = json.loads(rv.data)
        self.assertEquals(data['meta']['total'], 7)

    def test_query_builds_filter_submitted_after(self):
        rv = self.client.get(
            '/module-build-service/1/module-builds/?submitted_after=2016-09-03T12:25:00Z')
        data = json.loads(rv.data)
        self.assertEquals(data['meta']['total'], 23)

    def test_query_builds_filter_modified_before(self):
        rv = self.client.get(
            '/module-build-service/1/module-builds/?modified_before=2016-09-03T12:25:00Z')
        data = json.loads(rv.data)
        self.assertEquals(data['meta']['total'], 6)

    def test_query_builds_filter_modified_after(self):
        rv = self.client.get(
            '/module-build-service/1/module-builds/?modified_after=2016-09-03T12:25:00Z')
        data = json.loads(rv.data)
        self.assertEquals(data['meta']['total'], 24)

    def test_query_builds_filter_owner(self):
        rv = self.client.get(
            '/module-build-service/1/module-builds/?owner=Moe%20Szyslak')
        data = json.loads(rv.data)
        self.assertEquals(data['meta']['total'], 10)

    def test_query_builds_filter_state(self):
        rv = self.client.get(
            '/module-build-service/1/module-builds/?state=3')
        data = json.loads(rv.data)
        self.assertEquals(data['meta']['total'], 20)

    def test_query_builds_two_filters(self):
        rv = self.client.get('/module-build-service/1/module-builds/?owner=Moe%20Szyslak'
                             '&modified_after=2016-09-03T12:25:00Z')
        data = json.loads(rv.data)
        self.assertEquals(data['meta']['total'], 4)

    def test_query_builds_filter_invalid_date(self):
        rv = self.client.get(
            '/module-build-service/1/module-builds/?modified_after=2016-09-03T12:25:00-05:00')
        data = json.loads(rv.data)
        self.assertEquals(data['error'], 'Bad Request')
        self.assertEquals(data['message'], 'An invalid Zulu ISO 8601 timestamp'
                          ' was provided for the \"modified_after\" parameter')
        self.assertEquals(data['status'], 400)

    @patch('module_build_service.auth.get_username', return_value='Homer J. Simpson')
    @patch('module_build_service.auth.assert_is_packager')
    @patch('module_build_service.scm.SCM')
    def test_submit_build(self, mocked_scm, mocked_assert_is_packager,
                          mocked_get_username):
        mocked_scm_obj = MockedSCM(mocked_scm, "fakemodule", "fakemodule.yaml")

        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#68931c90de214d9d13feefbd35246a81b6cb8d49'}))
        data = json.loads(rv.data)

        self.assertEquals(data['component_builds'], [61])
        self.assertEquals(data['name'], 'fakemodule')
        self.assertEquals(data['scmurl'],
                          ('git://pkgs.stg.fedoraproject.org/modules/testmodule'
                          '.git?#68931c90de214d9d13feefbd35246a81b6cb8d49'))
        self.assertEquals(data['version'], '5')
        self.assertTrue(data['time_submitted'] is not None)
        self.assertTrue(data['time_modified'] is not None)
        self.assertEquals(data['version'], '5')
        self.assertEquals(data['time_completed'], None)
        self.assertEquals(data['stream'], '4.3.44')
        self.assertEquals(data['owner'], 'Homer J. Simpson')
        self.assertEquals(data['id'], 31)
        self.assertEquals(data['state_name'], 'wait')
        self.assertEquals(data['state_url'], '/module-build-service/1/module-builds/31')
        mmd = _modulemd.ModuleMetadata()
        mmd.loads(data["modulemd"])

    @patch('module_build_service.auth.get_username', return_value='Homer J. Simpson')
    @patch('module_build_service.auth.assert_is_packager')
    @patch('module_build_service.scm.SCM')
    def test_submit_componentless_build(self, mocked_scm, mocked_assert_is_packager,
                          mocked_get_username):
        mocked_scm_obj = MockedSCM(mocked_scm, "fakemodule2", "fakemodule2.yaml")

        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#68931c90de214d9d13feefbd35246a81b6cb8d49'}))
        data = json.loads(rv.data)

        self.assertEquals(data['component_builds'], [])
        self.assertEquals(data['name'], 'fakemodule2')
        self.assertEquals(data['scmurl'],
                          ('git://pkgs.stg.fedoraproject.org/modules/testmodule'
                          '.git?#68931c90de214d9d13feefbd35246a81b6cb8d49'))
        self.assertEquals(data['version'], '5')
        self.assertTrue(data['time_submitted'] is not None)
        self.assertTrue(data['time_modified'] is not None)
        self.assertEquals(data['version'], '5')
        self.assertEquals(data['time_completed'], None)
        self.assertEquals(data['stream'], '4.3.44')
        self.assertEquals(data['owner'], 'Homer J. Simpson')
        self.assertEquals(data['id'], 31)
        self.assertEquals(data['state_name'], 'wait')

    def test_submit_build_auth_error(self):
        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#48931b90de214d9d13feefbd35246a81b6cb8d49'}))
        data = json.loads(rv.data)
        self.assertEquals(
            data['message'],
            "Cannot verify OIDC token: No 'oidc_token' cookie found."
        )
        self.assertEquals(data['status'], 401)
        self.assertEquals(data['error'], 'Unauthorized')

    @patch('module_build_service.auth.get_username', return_value='Homer J. Simpson')
    @patch('module_build_service.auth.assert_is_packager')
    def test_submit_build_scm_url_error(self, mocked_assert_is_packager,
                                        mocked_get_username):
        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'scmurl': 'git://badurl.com'}))
        data = json.loads(rv.data)
        self.assertEquals(data['message'], 'The submitted scmurl '
            'git://badurl.com is not allowed')
        self.assertEquals(data['status'], 401)
        self.assertEquals(data['error'], 'Unauthorized')

    @patch('module_build_service.auth.get_username', return_value='Homer J. Simpson')
    @patch('module_build_service.auth.assert_is_packager')
    def test_submit_build_scm_url_without_hash(self,
                                               mocked_assert_is_packager,
                                               mocked_get_username):
        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git'}))
        data = json.loads(rv.data)
        self.assertEquals(data['message'], 'The submitted scmurl '
            'git://pkgs.stg.fedoraproject.org/modules/testmodule.git '
            'is not valid')
        self.assertEquals(data['status'], 401)
        self.assertEquals(data['error'], 'Unauthorized')

    @patch('module_build_service.auth.get_username', return_value='Homer J. Simpson')
    @patch('module_build_service.auth.assert_is_packager')
    @patch('module_build_service.scm.SCM')
    def test_submit_build_bad_modulemd(self, mocked_scm,
                                       mocked_assert_is_packager,
                                       mocked_get_username):
        mocked_scm_obj = MockedSCM(mocked_scm, "bad", "bad.yaml")

        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#68931c90de214d9d13feefbd35246a81b6cb8d49'}))
        data = json.loads(rv.data)
        self.assertTrue(data['message'].startswith('Invalid modulemd:'))
        self.assertEquals(data['status'], 422)
        self.assertEquals(data['error'], 'Unprocessable Entity')

    @patch('module_build_service.auth.get_username', return_value='Homer J. Simpson')
    @patch('module_build_service.auth.assert_is_packager')
    @patch('module_build_service.scm.SCM')
    def test_submit_build_scm_parallalization(self, mocked_scm,
                          mocked_assert_is_packager, mocked_get_username):
        def mocked_scm_is_available():
            time.sleep(1)
            return True

        mocked_scm.return_value.is_available = mocked_scm_is_available
        mocked_scm_obj = MockedSCM(mocked_scm, "base-runtime", "base-runtime.yaml")

        start = time.time()
        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#68931c90de214d9d13feefbd35246a81b6cb8d49'}))
        data = json.loads(rv.data)

        self.assertEquals(len(data['component_builds']), 5)
        self.assertEquals(data['name'], 'base-runtime')
        self.assertEquals(data['scmurl'],
                          ('git://pkgs.stg.fedoraproject.org/modules/testmodule'
                          '.git?#68931c90de214d9d13feefbd35246a81b6cb8d49'))
        self.assertTrue(data['time_submitted'] is not None)
        self.assertTrue(data['time_modified'] is not None)
        self.assertEquals(data['time_completed'], None)
        self.assertEquals(data['owner'], 'Homer J. Simpson')
        self.assertEquals(data['id'], 31)
        self.assertEquals(data['state_name'], 'wait')

        # SCM availability check is parallelized, so 5 components should not
        # take longer than 3 second, because each takes 1 second, but they
        # are execute in 10 threads. They should take around 1 or 2 seconds
        # max to complete.
        self.assertTrue(time.time() - start < 3)

    @patch('module_build_service.auth.get_username', return_value='Homer J. Simpson')
    @patch('module_build_service.auth.assert_is_packager')
    @patch('module_build_service.scm.SCM')
    def test_submit_build_scm_non_available(self, mocked_scm,
                          mocked_assert_is_packager, mocked_get_username):
        def mocked_scm_is_available():
            return False

        mocked_scm.return_value.is_available = mocked_scm_is_available
        mocked_scm_obj = MockedSCM(mocked_scm, "base-runtime", "base-runtime.yaml")

        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#68931c90de214d9d13feefbd35246a81b6cb8d49'}))
        data = json.loads(rv.data)

        self.assertEquals(data['status'], 422)
        self.assertEquals(data['message'][:15], "Cannot checkout")
        self.assertEquals(data['error'], "Unprocessable Entity")

    @patch('module_build_service.auth.get_username', return_value='Homer J. Simpson')
    @patch('module_build_service.auth.assert_is_packager')
    @patch('module_build_service.scm.SCM')
    def test_submit_build_includedmodule(self, mocked_scm, mocked_assert_is_packager,
                          mocked_get_username):
        mocked_scm_obj = MockedSCM(mocked_scm, "includedmodules",
                                   ["includedmodules.yaml", "fakemodule.yaml"])

        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#68931c90de214d9d13feefbd35246a81b6cb8d49'}))
        data = json.loads(rv.data)

        self.assertEquals(data['component_builds'], [61, 62])
        self.assertEquals(data['name'], 'fakemodule')
        self.assertEquals(data['scmurl'],
                          ('git://pkgs.stg.fedoraproject.org/modules/testmodule'
                          '.git?#68931c90de214d9d13feefbd35246a81b6cb8d49'))
        self.assertEquals(data['version'], '5')
        self.assertTrue(data['time_submitted'] is not None)
        self.assertTrue(data['time_modified'] is not None)
        self.assertEquals(data['version'], '5')
        self.assertEquals(data['time_completed'], None)
        self.assertEquals(data['stream'], '4.3.44')
        self.assertEquals(data['owner'], 'Homer J. Simpson')
        self.assertEquals(data['id'], 31)
        self.assertEquals(data['state_name'], 'wait')
        self.assertEquals(data['state_url'], '/module-build-service/1/module-builds/31')

        batches = {}
        for build in ComponentBuild.query.filter_by(module_id=31).all():
            batches[build.package] = build.batch

        self.assertEquals(batches["bash"], 2)
        self.assertEquals(batches["file"], 3)

    @patch('module_build_service.auth.get_username', return_value='some_other_user')
    @patch('module_build_service.auth.assert_is_packager')
    def test_cancel_build(self, mocked_assert_is_packager,
                          mocked_get_username):
        rv = self.client.patch('/module-build-service/1/module-builds/30',
                               data=json.dumps({'state': 'failed'}))
        data = json.loads(rv.data)

        self.assertEquals(data['state'], 4)
        self.assertEquals(data['state_reason'], 'Canceled by some_other_user.')


    @patch('module_build_service.auth.get_username', return_value='Someone else')
    @patch('module_build_service.auth.assert_is_packager')
    def test_cancel_build_unauthorized(self, mocked_assert_is_packager,
                          mocked_get_username):
        rv = self.client.patch('/module-build-service/1/module-builds/30',
                               data=json.dumps({'state': 'failed'}))
        data = json.loads(rv.data)

        self.assertEquals(data['status'], 401)
        self.assertEquals(data['error'], 'Unauthorized')

    @patch('module_build_service.auth.get_username', return_value='some_other_user')
    @patch('module_build_service.auth.assert_is_packager')
    def test_cancel_build_wrong_param(self, mocked_assert_is_packager,
                                      mocked_get_username):
        rv = self.client.patch('/module-build-service/1/module-builds/30',
                               data=json.dumps({'some_param': 'value'}))
        data = json.loads(rv.data)

        self.assertEquals(data['status'], 400)
        self.assertEquals(data['error'], 'Bad Request')
        self.assertEquals(
            data['message'], 'Invalid JSON submitted')

    @patch('module_build_service.auth.get_username', return_value='some_other_user')
    @patch('module_build_service.auth.assert_is_packager')
    def test_cancel_build_wrong_state(self, mocked_assert_is_packager,
                          mocked_get_username):
        rv = self.client.patch('/module-build-service/1/module-builds/30',
                               data=json.dumps({'state': 'some_state'}))
        data = json.loads(rv.data)

        self.assertEquals(data['status'], 400)
        self.assertEquals(data['error'], 'Bad Request')
        self.assertEquals(
            data['message'], 'The provided state change is not supported')

    @patch('module_build_service.auth.get_username', return_value='Homer J. Simpson')
    @patch('module_build_service.auth.assert_is_packager')
    def test_submit_build_unsupported_scm_scheme(self, mocked_assert_is_packager,
                          mocked_get_username):
        scmurl = 'unsupported://example.com/modules/'
        'testmodule.git?#0000000000000000000000000000000000000000'
        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'scmurl': scmurl}))
        data = json.loads(rv.data)
        self.assertIn(
            data['message'], (
                "The submitted scmurl {} is not allowed".format(scmurl),
                "The submitted scmurl {} is not valid".format(scmurl),
            )
        )
        self.assertEquals(data['status'], 401)
        self.assertEquals(data['error'], 'Unauthorized')
