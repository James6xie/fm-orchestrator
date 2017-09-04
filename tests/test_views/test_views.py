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
import vcr

import modulemd as _modulemd
import module_build_service.scm

from mock import patch, PropertyMock, MagicMock
from shutil import copyfile
from os import path, mkdir
from os.path import dirname
from parameterized import parameterized
import hashlib

from tests import app, init_data
from module_build_service.errors import UnprocessableEntity
from module_build_service.models import ComponentBuild, ModuleBuild
from module_build_service import conf, db
import module_build_service.scheduler.handlers.modules


user = ('Homer J. Simpson', set(['packager']))
other_user = ('some_other_user', set(['packager']))
anonymous_user = ('anonymous', set(['packager']))
base_dir = dirname(dirname(__file__))
cassette_dir = base_dir + '/vcr-request-data/'


class MockedSCM(object):
    def __init__(self, mocked_scm, name, mmd_filenames, commit=None, checkout_raise=False,
                 get_latest_raise=False):
        """
        Adds default testing checkout, get_latest and name methods
        to mocked_scm SCM class.

        :param mmd_filenames: List of ModuleMetadata yaml files which
        will be checkouted by the SCM class in the same order as they
        are stored in the list.
        """
        self.mocked_scm = mocked_scm
        self.name = name
        self.commit = commit
        if not isinstance(mmd_filenames, list):
            mmd_filenames = [mmd_filenames]
        self.mmd_filenames = mmd_filenames
        self.checkout_id = 0
        self.sourcedir = None

        if checkout_raise:
            self.mocked_scm.return_value.checkout.side_effect = \
                UnprocessableEntity(
                    "checkout: The requested commit hash was not found within "
                    "the repository. Perhaps you forgot to push. The original "
                    "message was: ")
        else:
            self.mocked_scm.return_value.checkout = self.checkout

        self.mocked_scm.return_value.name = self.name
        self.mocked_scm.return_value.commit = self.commit
        if get_latest_raise:
            self.mocked_scm.return_value.get_latest.side_effect = \
                RuntimeError("Failed to get_latest commit")
        else:
            self.mocked_scm.return_value.get_latest = self.get_latest
        self.mocked_scm.return_value.repository_root = "git://pkgs.stg.fedoraproject.org/modules/"
        self.mocked_scm.return_value.branch = 'master'
        self.mocked_scm.return_value.sourcedir = self.sourcedir
        self.mocked_scm.return_value.get_module_yaml = self.get_module_yaml

    def checkout(self, temp_dir):
        try:
            mmd_filename = self.mmd_filenames[self.checkout_id]
        except:
            mmd_filename = self.mmd_filenames[0]

        self.sourcedir = path.join(temp_dir, self.name)
        mkdir(self.sourcedir)
        base_dir = path.abspath(path.dirname(__file__))
        copyfile(path.join(base_dir, '..', 'staged_data', mmd_filename),
                 self.get_module_yaml())

        self.checkout_id += 1

        return self.sourcedir

    def get_latest(self, branch='master'):
        return hashlib.sha1(branch).hexdigest()[:10]

    def get_module_yaml(self):
        return path.join(self.sourcedir, self.name + ".yaml")


class TestViews(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.client = app.test_client()
        init_data()

        filename = cassette_dir + self.id()
        self.vcr = vcr.use_cassette(filename)
        self.vcr.__enter__()

    def tearDown(self):
        self.vcr.__exit__()

    def test_query_build(self):
        rv = self.client.get('/module-build-service/1/module-builds/1')
        data = json.loads(rv.data)
        self.assertEquals(data['id'], 1)
        self.assertEquals(data['name'], 'nginx')
        self.assertEquals(data['owner'], 'Moe Szyslak')
        self.assertEquals(data['state'], 3)
        self.assertEquals(data['state_reason'], None)
        self.assertDictEqual(data['tasks'], {
            'rpms': {
                'module-build-macros': {
                    'task_id': 12312321,
                    'state': 1,
                    'state_reason': None,
                    'nvr': 'module-build-macros-01-1.module_nginx_1_2',
                },
                'nginx': {
                    'task_id': 12312345,
                    'state': 1,
                    'state_reason': None,
                    'nvr': 'nginx-1.10.1-2.module_nginx_1_2',
                },
            },
        })
        self.assertEquals(data['time_completed'], '2016-09-03T11:25:32Z')
        self.assertEquals(data['time_modified'], '2016-09-03T11:25:32Z')
        self.assertEquals(data['time_submitted'], '2016-09-03T11:23:20Z')

    def test_query_build_with_verbose_mode(self):
        rv = self.client.get('/module-build-service/1/module-builds/1?verbose=1')
        data = json.loads(rv.data)
        self.assertEquals(data['component_builds'], [1, 2])
        self.assertEquals(data['id'], 1)
        with open(path.join(base_dir, "staged_data", "nginx_mmd.yaml")) as mmd:
            self.assertEquals(data['modulemd'], mmd.read())
        self.assertEquals(data['name'], 'nginx')
        self.assertEquals(data['owner'], 'Moe Szyslak')
        self.assertEquals(data['scmurl'],
                          ('git://pkgs.domain.local/modules/nginx'
                           '?#ba95886c7a443b36a9ce31abda1f9bef22f2f8c9'))
        self.assertEquals(data['state'], 3)
        self.assertEquals(data['state_name'], 'done')
        self.assertEquals(data['state_reason'], None)
        self.assertEquals(data['state_trace'][0]['reason'], None)
        self.assertTrue(data['state_trace'][0]['time'] is not None)
        self.assertEquals(data['state_trace'][0]['state'], 3)
        self.assertEquals(data['state_trace'][0]['state_name'], 'done')
        self.assertEquals(data['state_url'], '/module-build-service/1/module-builds/1')
        self.assertEquals(data['stream'], '1')
        self.assertDictEqual(data['tasks'], {
            'rpms': {
                'module-build-macros': {
                    'task_id': 12312321,
                    'state': 1,
                    'state_reason': None,
                    'nvr': 'module-build-macros-01-1.module_nginx_1_2',
                },
                'nginx': {
                    'task_id': 12312345,
                    'state': 1,
                    'state_reason': None,
                    'nvr': 'nginx-1.10.1-2.module_nginx_1_2',
                },
            },
        })
        self.assertEquals(data['time_completed'], u'2016-09-03T11:25:32Z')
        self.assertEquals(data['time_modified'], u'2016-09-03T11:25:32Z')
        self.assertEquals(data['time_submitted'], u'2016-09-03T11:23:20Z')
        self.assertEquals(data['version'], '2')

    def test_pagination_metadata(self):
        rv = self.client.get('/module-build-service/1/module-builds/?per_page=8&page=2')
        meta_data = json.loads(rv.data)['meta']
        self.assertIn(
            meta_data['prev'].split('?', 1)[1], ['per_page=8&page=1', 'page=1&per_page=8'])
        self.assertIn(
            meta_data['next'].split('?', 1)[1], ['per_page=8&page=3', 'page=3&per_page=8'])
        self.assertIn(
            meta_data['last'].split('?', 1)[1], ['per_page=8&page=4', 'page=4&per_page=8'])
        self.assertIn(
            meta_data['first'].split('?', 1)[1], ['per_page=8&page=1', 'page=1&per_page=8'])
        self.assertEquals(meta_data['total'], 30)
        self.assertEquals(meta_data['per_page'], 8)
        self.assertEquals(meta_data['pages'], 4)
        self.assertEquals(meta_data['page'], 2)

    def test_pagination_metadata_with_args(self):
        rv = self.client.get('/module-build-service/1/module-builds/?per_page=8&page=2&order_by=id')
        meta_data = json.loads(rv.data)['meta']
        for link in [meta_data['prev'], meta_data['next'], meta_data['last'], meta_data['first']]:
            self.assertIn('order_by=id', link)
            self.assertIn('per_page=8', link)
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
        self.assertDictEqual(item['tasks'], {
            'rpms': {
                'module-build-macros': {
                    'task_id': 12312321,
                    'state': 1,
                    'state_reason': None,
                    'nvr': 'module-build-macros-01-1.module_nginx_1_2',
                },
                'nginx': {
                    'task_id': 12312345,
                    'state': 1,
                    'state_reason': None,
                    'nvr': 'nginx-1.10.1-2.module_nginx_1_2',
                },
            },
        })
        self.assertEquals(item['time_completed'], '2016-09-03T11:25:32Z')
        self.assertEquals(item['time_modified'], '2016-09-03T11:25:32Z')
        self.assertEquals(item['time_submitted'], '2016-09-03T11:23:20Z')

    def test_query_component_build(self):
        rv = self.client.get('/module-build-service/1/component-builds/1')
        data = json.loads(rv.data)
        self.assertEquals(data['id'], 1)
        self.assertEquals(data['format'], 'rpms')
        self.assertEquals(data['module_build'], 1)
        self.assertEquals(data['package'], 'nginx')
        self.assertEquals(data['state'], 1)
        self.assertEquals(data['state_name'], 'COMPLETE')
        self.assertEquals(data['state_reason'], None)
        self.assertEquals(data['task_id'], 12312345)

    def test_query_component_build_verbose(self):
        rv = self.client.get('/module-build-service/1/component-builds/3?verbose=1')
        data = json.loads(rv.data)
        self.assertEquals(data['id'], 3)
        self.assertEquals(data['format'], 'rpms')
        self.assertEquals(data['module_build'], 2)
        self.assertEquals(data['package'], 'postgresql')
        self.assertEquals(data['state'], 1)
        self.assertEquals(data['state_name'], 'COMPLETE')
        self.assertEquals(data['state_reason'], None)
        self.assertEquals(data['task_id'], 2433433)
        self.assertEquals(data['state_trace'][0]['reason'], None)
        self.assertTrue(data['state_trace'][0]['time'] is not None)
        self.assertEquals(data['state_trace'][0]['state'], 1)
        self.assertEquals(data['state_trace'][0]['state_name'], 'wait')

    component_builds_filters = ['tagged', 'ref', 'format']

    @parameterized.expand([
        ('format', 'rpms', 60),
        ('ref', 'this-filter-query-should-return-zero-items', 0),
        ('tagged', 'this-filter-query-should-return-zero-items', 0),
    ])
    def test_query_component_builds_filters(self, f, s, c):
        rv = self.client.get('/module-build-service/1/component-builds/?{}={}'.format(f, s))
        data = json.loads(rv.data)
        self.assertEquals(data['meta']['total'], c)

    def test_query_component_builds_filter_nvr(self):
        rv = self.client.get('/module-build-service/1/component-builds/?nvr=nginx-1.10.1-2.module_nginx_1_2')
        data = json.loads(rv.data)
        self.assertEquals(data['meta']['total'], 10)

    def test_query_component_builds_filter_task_id(self):
        rv = self.client.get('/module-build-service/1/component-builds/?task_id=12312346')
        data = json.loads(rv.data)
        self.assertEquals(data['meta']['total'], 1)

    def test_query_builds_filter_name(self):
        rv = self.client.get('/module-build-service/1/module-builds/?name=nginx')
        data = json.loads(rv.data)
        self.assertEquals(data['meta']['total'], 10)

    def test_query_builds_filter_koji_tag(self):
        rv = self.client.get('/module-build-service/1/module-builds/?koji_tag=module-nginx-1.2')
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

    def test_query_builds_order_by(self):
        rv = self.client.get('/module-build-service/1/module-builds/?'
                             'per_page=10&order_by=id')
        items = json.loads(rv.data)['items']
        # Check that the id is 1, 2, 3, ..., 10
        for idx, item in enumerate(items):
            self.assertEquals(item["id"], idx + 1)

    def test_query_builds_order_desc_by(self):
        rv = self.client.get('/module-build-service/1/module-builds/?'
                             'per_page=10&order_desc_by=id')
        items = json.loads(rv.data)['items']
        # Check that the id is items[0]["id"], items[0]["id"] - 1, ...
        for idx, item in enumerate(items):
            self.assertEquals(item["id"], items[0]["id"] - idx)

    def test_query_builds_order_by_order_desc_by(self):
        """
        Test that when both order_by and order_desc_by is set,
        we prefer order_desc_by.
        """
        rv = self.client.get('/module-build-service/1/module-builds/?'
                             'per_page=10&order_desc_by=id&order_by=name')
        items = json.loads(rv.data)['items']
        # Check that the id is items[0]["id"], items[0]["id"] - 1, ...
        for idx, item in enumerate(items):
            self.assertEquals(item["id"], items[0]["id"] - idx)

    def test_query_builds_order_by_wrong_key(self):
        rv = self.client.get('/module-build-service/1/module-builds/?'
                             'per_page=10&order_by=unknown')
        data = json.loads(rv.data)
        self.assertEquals(data['status'], 400)
        self.assertEquals(data['error'], 'Bad Request')
        self.assertEquals(
            data['message'], 'An invalid order_by or order_desc_by key '
            'was supplied')

    @patch('module_build_service.auth.get_user', return_value=user)
    @patch('module_build_service.scm.SCM')
    def test_submit_build(self, mocked_scm, mocked_get_user):
        MockedSCM(mocked_scm, 'testmodule', 'testmodule.yaml',
                  '620ec77321b2ea7b0d67d82992dda3e1d67055b4')

        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'branch': 'master', 'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#68931c90de214d9d13feefbd35246a81b6cb8d49'}))
        data = json.loads(rv.data)

        assert 'component_builds' in data, data
        self.assertEquals(data['component_builds'], [61, 62, 63])
        self.assertEquals(data['name'], 'testmodule')
        self.assertEquals(data['scmurl'],
                          ('git://pkgs.stg.fedoraproject.org/modules/testmodule'
                          '.git?#68931c90de214d9d13feefbd35246a81b6cb8d49'))
        self.assertEquals(data['version'], '1')
        self.assertTrue(data['time_submitted'] is not None)
        self.assertTrue(data['time_modified'] is not None)
        self.assertEquals(data['time_completed'], None)
        self.assertEquals(data['stream'], 'master')
        self.assertEquals(data['owner'], 'Homer J. Simpson')
        self.assertEquals(data['id'], 31)
        self.assertEquals(data['state_name'], 'wait')
        self.assertEquals(data['state_url'], '/module-build-service/1/module-builds/31')
        self.assertEquals(data['state_trace'][0]['reason'], None)
        self.assertTrue(data['state_trace'][0]['time'] is not None)
        self.assertEquals(data['state_trace'][0]['state'], 1)
        self.assertEquals(data['state_trace'][0]['state_name'], 'wait')
        self.assertDictEqual(data['tasks'], {
            'rpms': {
                'perl-List-Compare': {
                    'task_id': None,
                    'state': None,
                    'state_reason': None,
                    'nvr': None,
                },
                'perl-Tangerine': {
                    'task_id': None,
                    'state': None,
                    'state_reason': None,
                    'nvr': None,
                },
                'tangerine': {
                    'task_id': None,
                    'state': None,
                    'state_reason': None,
                    'nvr': None,
                },
            },
        })
        mmd = _modulemd.ModuleMetadata()
        mmd.loads(data["modulemd"])

    @patch('module_build_service.auth.get_user', return_value=user)
    @patch('module_build_service.scm.SCM')
    def test_submit_componentless_build(self, mocked_scm, mocked_get_user):
        MockedSCM(mocked_scm, 'fakemodule', 'fakemodule.yaml',
                  '3da541559918a808c2402bba5012f6c60b27661c')

        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'branch': 'master', 'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#68931c90de214d9d13feefbd35246a81b6cb8d49'}))
        data = json.loads(rv.data)

        self.assertEquals(data['component_builds'], [])
        self.assertEquals(data['name'], 'fakemodule')
        self.assertEquals(data['scmurl'],
                          ('git://pkgs.stg.fedoraproject.org/modules/testmodule'
                          '.git?#68931c90de214d9d13feefbd35246a81b6cb8d49'))
        self.assertEquals(data['version'], '1')
        self.assertTrue(data['time_submitted'] is not None)
        self.assertTrue(data['time_modified'] is not None)
        self.assertEquals(data['time_completed'], None)
        self.assertEquals(data['stream'], 'master')
        self.assertEquals(data['owner'], 'Homer J. Simpson')
        self.assertEquals(data['id'], 31)
        self.assertEquals(data['state_name'], 'wait')

    def test_submit_build_auth_error(self):
        base_dir = path.abspath(path.dirname(__file__))
        client_secrets = path.join(base_dir, "client_secrets.json")
        with patch.dict('module_build_service.app.config', {'OIDC_CLIENT_SECRETS': client_secrets}):
            rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
                {'branch': 'master', 'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                    'testmodule.git?#48931b90de214d9d13feefbd35246a81b6cb8d49'}))
            data = json.loads(rv.data)
            self.assertEquals(
                data['message'],
                "No 'authorization' header found."
            )
            self.assertEquals(data['status'], 401)
            self.assertEquals(data['error'], 'Unauthorized')

    @patch('module_build_service.auth.get_user', return_value=user)
    def test_submit_build_scm_url_error(self, mocked_get_user):
        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'branch': 'master', 'scmurl': 'git://badurl.com'}))
        data = json.loads(rv.data)
        self.assertEquals(data['message'], 'The submitted scmurl '
                          'git://badurl.com is not allowed')
        self.assertEquals(data['status'], 403)
        self.assertEquals(data['error'], 'Forbidden')

    @patch('module_build_service.auth.get_user', return_value=user)
    def test_submit_build_scm_url_without_hash(self, mocked_get_user):
        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'branch': 'master', 'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git'}))
        data = json.loads(rv.data)
        self.assertEquals(data['message'], 'The submitted scmurl '
                          'git://pkgs.stg.fedoraproject.org/modules/testmodule.git '
                          'is not valid')
        self.assertEquals(data['status'], 403)
        self.assertEquals(data['error'], 'Forbidden')

    @patch('module_build_service.auth.get_user', return_value=user)
    @patch('module_build_service.scm.SCM')
    def test_submit_build_bad_modulemd(self, mocked_scm, mocked_get_user):
        MockedSCM(mocked_scm, "bad", "bad.yaml")

        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'branch': 'master', 'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#68931c90de214d9d13feefbd35246a81b6cb8d49'}))
        data = json.loads(rv.data)
        self.assertTrue(data['message'].startswith('Invalid modulemd:'))
        self.assertEquals(data['status'], 422)
        self.assertEquals(data['error'], 'Unprocessable Entity')

    @patch('module_build_service.auth.get_user', return_value=user)
    @patch('module_build_service.scm.SCM')
    def test_submit_build_scm_parallalization(self, mocked_scm,
                                              mocked_get_user):
        def mocked_scm_get_latest(branch="master"):
            time.sleep(1)
            return branch

        MockedSCM(mocked_scm, 'testmodule', 'testmodule.yaml',
                  '620ec77321b2ea7b0d67d82992dda3e1d67055b4')
        mocked_scm.return_value.is_available = mocked_scm_get_latest

        start = time.time()
        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'branch': 'master', 'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#68931c90de214d9d13feefbd35246a81b6cb8d49'}))
        data = json.loads(rv.data)

        self.assertEquals(len(data['component_builds']), 3)
        self.assertEquals(data['name'], 'testmodule')
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

    @patch('module_build_service.auth.get_user', return_value=user)
    @patch('module_build_service.scm.SCM')
    def test_submit_build_scm_non_available(self, mocked_scm, mocked_get_user):

        def mocked_scm_get_latest():
            raise RuntimeError("Failed in mocked_scm_get_latest")

        MockedSCM(mocked_scm, 'testmodule', 'testmodule.yaml',
                  '620ec77321b2ea7b0d67d82992dda3e1d67055b4')
        mocked_scm.return_value.get_latest = mocked_scm_get_latest

        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'branch': 'master', 'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#68931c90de214d9d13feefbd35246a81b6cb8d49'}))
        data = json.loads(rv.data)

        self.assertEquals(data['status'], 422)
        self.assertEquals(data['message'][:31], "Failed to get the latest commit")
        self.assertEquals(data['error'], "Unprocessable Entity")

    @patch('module_build_service.auth.get_user', return_value=user)
    @patch('module_build_service.scm.SCM')
    @patch("module_build_service.config.Config.modules_allow_repository",
           new_callable=PropertyMock, return_value=True)
    def test_submit_build_includedmodule(self, conf, mocked_scm, mocked_get_user):
        MockedSCM(mocked_scm, "includedmodules", ["includedmodules.yaml",
                                                  "testmodule.yaml"])

        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'branch': 'master', 'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#68931c90de214d9d13feefbd35246a81b6cb8d49'}))
        data = json.loads(rv.data)

        assert 'component_builds' in data, data
        self.assertEquals(data['component_builds'], [61, 62, 63, 64, 65])
        self.assertEquals(data['name'], 'includedmodules')
        self.assertEquals(data['scmurl'],
                          ('git://pkgs.stg.fedoraproject.org/modules/testmodule'
                          '.git?#68931c90de214d9d13feefbd35246a81b6cb8d49'))
        self.assertEquals(data['version'], '1')
        self.assertTrue(data['time_submitted'] is not None)
        self.assertTrue(data['time_modified'] is not None)
        self.assertEquals(data['time_completed'], None)
        self.assertEquals(data['stream'], 'master')
        self.assertEquals(data['owner'], 'Homer J. Simpson')
        self.assertEquals(data['id'], 31)
        self.assertEquals(data['state_name'], 'wait')
        self.assertEquals(data['state_url'], '/module-build-service/1/module-builds/31')

        batches = {}
        for build in ComponentBuild.query.filter_by(module_id=31).all():
            batches[build.package] = build.batch

        self.assertEquals(batches['ed'], 2)
        self.assertEquals(batches['perl-List-Compare'], 2)
        self.assertEquals(batches['perl-Tangerine'], 2)
        self.assertEquals(batches['tangerine'], 3)
        self.assertEquals(batches["file"], 4)

        build = ModuleBuild.query.filter(ModuleBuild.id == data['id']).one()
        mmd = build.mmd()

        # Test that RPMs are properly merged in case of included modules in mmd.
        xmd_rpms = {'ed': {'ref': '40bd001563'},
                    'perl-List-Compare': {'ref': '2ee8474e44'},
                    'tangerine': {'ref': 'd29d5c24b8'},
                    'file': {'ref': 'a2740663f8'},
                    'perl-Tangerine': {'ref': '27785f9f05'}}
        self.assertEqual(mmd.xmd['mbs']['rpms'], xmd_rpms)

    @patch('module_build_service.auth.get_user', return_value=user)
    @patch('module_build_service.scm.SCM')
    def test_submit_build_includedmodule_custom_repo_not_allowed(self,
                                                                 mocked_scm, mocked_get_user):
        MockedSCM(mocked_scm, "includedmodules", ["includedmodules.yaml",
                                                  "testmodule.yaml"])
        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'branch': 'master', 'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#68931c90de214d9d13feefbd35246a81b6cb8d49'}))
        data = json.loads(rv.data)

        self.assertEquals(data['status'], 403)
        self.assertEquals(data['error'], 'Forbidden')

    @patch('module_build_service.auth.get_user', return_value=other_user)
    def test_cancel_build(self, mocked_get_user):
        rv = self.client.patch('/module-build-service/1/module-builds/30',
                               data=json.dumps({'state': 'failed'}))
        data = json.loads(rv.data)

        self.assertEquals(data['state'], 4)
        self.assertEquals(data['state_reason'], 'Canceled by some_other_user.')

    @patch('module_build_service.auth.get_user', return_value=('sammy', set()))
    def test_cancel_build_unauthorized_no_groups(self, mocked_get_user):
        rv = self.client.patch('/module-build-service/1/module-builds/30',
                               data=json.dumps({'state': 'failed'}))
        data = json.loads(rv.data)

        self.assertEquals(data['status'], 403)
        self.assertEquals(data['error'], 'Forbidden')

    @patch('module_build_service.auth.get_user', return_value=('sammy', set(["packager"])))
    def test_cancel_build_unauthorized_not_owner(self, mocked_get_user):
        rv = self.client.patch('/module-build-service/1/module-builds/30',
                               data=json.dumps({'state': 'failed'}))
        data = json.loads(rv.data)

        self.assertEquals(data['status'], 403)
        self.assertEquals(data['error'], 'Forbidden')

    @patch('module_build_service.auth.get_user',
           return_value=('sammy', set(["packager", "mbs-admin"])))
    def test_cancel_build_admin(self, mocked_get_user):
        with patch("module_build_service.config.Config.admin_groups",
                   new_callable=PropertyMock, return_value=set(["mbs-admin"])):
            rv = self.client.patch('/module-build-service/1/module-builds/30',
                                   data=json.dumps({'state': 'failed'}))
            data = json.loads(rv.data)

            self.assertEquals(data['state'], 4)
            self.assertEquals(data['state_reason'], 'Canceled by sammy.')

    @patch('module_build_service.auth.get_user',
           return_value=('sammy', set(["packager"])))
    def test_cancel_build_no_admin(self, mocked_get_user):
        with patch("module_build_service.config.Config.admin_groups",
                   new_callable=PropertyMock, return_value=set(["mbs-admin"])):
            rv = self.client.patch('/module-build-service/1/module-builds/30',
                                   data=json.dumps({'state': 'failed'}))
            data = json.loads(rv.data)

            self.assertEquals(data['status'], 403)
            self.assertEquals(data['error'], 'Forbidden')

    @patch('module_build_service.auth.get_user', return_value=other_user)
    def test_cancel_build_wrong_param(self, mocked_get_user):
        rv = self.client.patch('/module-build-service/1/module-builds/30',
                               data=json.dumps({'some_param': 'value'}))
        data = json.loads(rv.data)

        self.assertEquals(data['status'], 400)
        self.assertEquals(data['error'], 'Bad Request')
        self.assertEquals(
            data['message'], 'Invalid JSON submitted')

    @patch('module_build_service.auth.get_user', return_value=other_user)
    def test_cancel_build_wrong_state(self, mocked_get_user):
        rv = self.client.patch('/module-build-service/1/module-builds/30',
                               data=json.dumps({'state': 'some_state'}))
        data = json.loads(rv.data)

        self.assertEquals(data['status'], 400)
        self.assertEquals(data['error'], 'Bad Request')
        self.assertEquals(
            data['message'], 'The provided state change is not supported')

    @patch('module_build_service.auth.get_user', return_value=user)
    def test_submit_build_unsupported_scm_scheme(self, mocked_get_user):
        scmurl = 'unsupported://example.com/modules/'
        'testmodule.git?#0000000000000000000000000000000000000000'
        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'branch': 'master', 'scmurl': scmurl}))
        data = json.loads(rv.data)
        self.assertIn(
            data['message'], (
                "The submitted scmurl {} is not allowed".format(scmurl),
                "The submitted scmurl {} is not valid".format(scmurl),
            )
        )
        self.assertEquals(data['status'], 403)
        self.assertEquals(data['error'], 'Forbidden')

    @patch('module_build_service.auth.get_user', return_value=user)
    @patch('module_build_service.scm.SCM')
    def test_submit_build_version_set_error(self, mocked_scm, mocked_get_user):
        MockedSCM(mocked_scm, 'testmodule', 'testmodule-version-set.yaml',
                  '620ec77321b2ea7b0d67d82992dda3e1d67055b4')

        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'branch': 'master', 'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#68931c90de214d9d13feefbd35246a81b6cb8d49'}))
        data = json.loads(rv.data)
        self.assertEquals(data['status'], 400)
        self.assertEquals(
            data['message'],
            'The version "123456789" is already defined in the modulemd but '
            'it shouldn\'t be since the version is generated based on the '
            'commit time')
        self.assertEquals(data['error'], 'Bad Request')

    @patch('module_build_service.auth.get_user', return_value=user)
    @patch('module_build_service.scm.SCM')
    def test_submit_build_wrong_stream(self, mocked_scm, mocked_get_user):
        MockedSCM(mocked_scm, 'testmodule', 'testmodule-wrong-stream.yaml',
                  '620ec77321b2ea7b0d67d82992dda3e1d67055b4')

        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'branch': 'master', 'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#68931c90de214d9d13feefbd35246a81b6cb8d49'}))
        data = json.loads(rv.data)
        self.assertEquals(data['status'], 400)
        self.assertEquals(
            data['message'],
            'The stream "wrong_stream" that is stored in the modulemd does not '
            'match the branch "master"')
        self.assertEquals(data['error'], 'Bad Request')

    @patch('module_build_service.auth.get_user', return_value=user)
    def test_submit_build_set_owner(self, mocked_get_user):
        data = {
            'branch': 'master',
            'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                      'testmodule.git?#68931c90de214d9d13feefbd35246a81b6cb8d49',
            'owner': 'foo',
        }
        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(data))
        result = json.loads(rv.data)
        self.assertEquals(result['status'], 400)
        self.assertIn("The request contains 'owner' parameter", result['message'])

    @patch('module_build_service.auth.get_user', return_value=anonymous_user)
    @patch('module_build_service.scm.SCM')
    @patch("module_build_service.config.Config.no_auth", new_callable=PropertyMock, return_value=True)
    def test_submit_build_no_auth_set_owner(self, mocked_conf, mocked_scm, mocked_get_user):
        MockedSCM(mocked_scm, 'testmodule', 'testmodule.yaml',
                  '620ec77321b2ea7b0d67d82992dda3e1d67055b4')

        data = {
            'branch': 'master',
            'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                      'testmodule.git?#68931c90de214d9d13feefbd35246a81b6cb8d49',
            'owner': 'foo',
        }
        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(data))
        result = json.loads(rv.data)

        build = ModuleBuild.query.filter(ModuleBuild.id == result['id']).one()
        self.assertTrue(build.owner == result['owner'] == 'foo')

    @patch('module_build_service.auth.get_user', return_value=anonymous_user)
    @patch('module_build_service.scm.SCM')
    @patch("module_build_service.config.Config.no_auth", new_callable=PropertyMock)
    def test_patch_set_different_owner(self, mocked_no_auth, mocked_scm, mocked_get_user):
        MockedSCM(mocked_scm, 'testmodule', 'testmodule.yaml',
                  '620ec77321b2ea7b0d67d82992dda3e1d67055b4')

        mocked_no_auth.return_value = True
        data = {
            'branch': 'master',
            'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                      'testmodule.git?#68931c90de214d9d13feefbd35246a81b6cb8d49',
            'owner': 'foo',
        }
        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(data))
        r1 = json.loads(rv.data)

        url = '/module-build-service/1/module-builds/' + str(r1['id'])
        r2 = self.client.patch(url, data=json.dumps({'state': 'failed'}))
        self.assertEquals(r2.status_code, 403)

        r3 = self.client.patch(url, data=json.dumps({'state': 'failed', 'owner': 'foo'}))
        self.assertEquals(r3.status_code, 200)

        mocked_no_auth.return_value = False
        r3 = self.client.patch(url, data=json.dumps({'state': 'failed', 'owner': 'foo'}))
        self.assertEquals(r3.status_code, 400)
        self.assertIn("The request contains 'owner' parameter", json.loads(r3.data)['message'])

    @patch('module_build_service.auth.get_user', return_value=user)
    @patch('module_build_service.scm.SCM')
    def test_submit_build_commit_hash_not_found(self, mocked_scm, mocked_get_user):
        MockedSCM(mocked_scm, 'testmodule', 'testmodule.yaml',
                  '7035bd33614972ac66559ac1fdd019ff6027ad22', checkout_raise=True)

        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'branch': 'master', 'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#7035bd33614972ac66559ac1fdd019ff6027ad22'}))
        data = json.loads(rv.data)
        self.assertIn("The requested commit hash was not found within the repository.",
                      data['message'])
        self.assertIn("Perhaps you forgot to push. The original message was: ",
                      data['message'])
        self.assertEquals(data['status'], 422)
        self.assertEquals(data['error'], 'Unprocessable Entity')

    @patch('module_build_service.auth.get_user', return_value=user)
    @patch('module_build_service.scm.SCM')
    @patch('module_build_service.models.ModuleBuild.from_module_event')
    def test_submit_build_get_latest_raises(
            self, from_module_event, mocked_scm, mocked_get_user):
        MockedSCM(mocked_scm, 'testmodule', 'testmodule.yaml',
                  '7035bd33614972ac66559ac1fdd019ff6027ad22', get_latest_raise=True)

        with app.app_context():
            rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
                {'branch': 'master', 'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                    'testmodule.git?#7035bd33614972ac66559ac1fdd019ff6027ad22'}))
            data = json.loads(rv.data)
            self.assertEquals(data['status'], 422)
            self.assertEquals(data['error'], 'Unprocessable Entity')

            # Get the last module and check it has the state_reason set.
            build = ModuleBuild.query.order_by(ModuleBuild.id).all()[-1]
            db.session.add(build)
            from_module_event.return_value = build
            self.assertIn("Failed to validate modulemd file", build.state_reason)

            # Check that after the failed message is handled, the state_reason
            # remains the same.
            module_build_service.scheduler.handlers.modules.failed(
                conf, db.session, MagicMock())
            db.session.expunge(build)
            build = ModuleBuild.query.order_by(ModuleBuild.id).all()[-1]
            self.assertIn("Failed to validate modulemd file", build.state_reason)

    @patch('module_build_service.auth.get_user', return_value=user)
    @patch('module_build_service.scm.SCM')
    @patch("module_build_service.config.Config.allow_custom_scmurls", new_callable=PropertyMock)
    def test_submit_custom_scmurl(self, allow_custom_scmurls, mocked_scm, mocked_get_user):
        MockedSCM(mocked_scm, 'testmodule', 'testmodule.yaml',
                  '620ec77321b2ea7b0d67d82992dda3e1d67055b4')

        def submit(scmurl):
            return self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
                                    {'branch': 'master', 'scmurl': scmurl}))

        allow_custom_scmurls.return_value = False
        res1 = submit('git://some.custom.url.org/modules/testmodule.git?#68931c9')
        data = json.loads(res1.data)
        self.assertEquals(data['status'], 403)
        self.assertTrue(data['message'].startswith('The submitted scmurl'))
        self.assertTrue(data['message'].endswith('is not allowed'))

        allow_custom_scmurls.return_value = True
        res2 = submit('git://some.custom.url.org/modules/testmodule.git?#68931c9')
        self.assertEquals(res2.status_code, 201)
