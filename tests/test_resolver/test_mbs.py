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

import os

from mock import patch, PropertyMock, Mock, call

import module_build_service.resolver as mbs_resolver
import module_build_service.utils
import module_build_service.models
from module_build_service import glib, Modulemd, app
import tests


base_dir = os.path.join(os.path.dirname(__file__), "..")


class TestMBSModule:

    @patch("requests.Session")
    def test_get_module_modulemds_nsvc(self, mock_session, testmodule_mmd_9c690d0e):
        """ Tests for querying a module from mbs """
        mock_res = Mock()
        mock_res.ok.return_value = True
        mock_res.json.return_value = {
            "items": [
                {
                    "name": "testmodule",
                    "stream": "master",
                    "version": "20180205135154",
                    "context": "9c690d0e",
                    "modulemd": testmodule_mmd_9c690d0e
                }
            ],
            "meta": {"next": None}
        }

        mock_session().get.return_value = mock_res

        resolver = mbs_resolver.GenericResolver.create(tests.conf, backend='mbs')
        module_mmds = resolver.get_module_modulemds('testmodule', 'master', '20180205135154',
                                                    '9c690d0e')
        nsvcs = set(
            '{}:{}:{}:{}'.format(m.peek_name(), m.peek_stream(),
                                 m.peek_version(), m.peek_context())
            for m in module_mmds
        )
        expected = set(["testmodule:master:20180205135154:9c690d0e"])
        mbs_url = tests.conf.mbs_url
        expected_query = {
            "name": "testmodule",
            "stream": "master",
            "version": "20180205135154",
            "context": "9c690d0e",
            "verbose": True,
            "order_desc_by": "version",
            "page": 1,
            "per_page": 10,
            "state": "ready"
        }
        mock_session().get.assert_called_once_with(mbs_url, params=expected_query)
        assert nsvcs == expected

    @patch("requests.Session")
    def test_get_module_modulemds_partial(self, mock_session, testmodule_mmd_9c690d0e,
                                          testmodule_mmd_c2c572ed):
        """ Test for querying MBS without the context of a module """

        version = "20180205135154"

        mock_res = Mock()
        mock_res.ok.return_value = True
        mock_res.json.return_value = {
            "items": [
                {
                    "name": "testmodule",
                    "stream": "master",
                    "version": version,
                    "context": "9c690d0e",
                    "modulemd": testmodule_mmd_9c690d0e
                },
                {
                    "name": "testmodule",
                    "stream": "master",
                    "version": version,
                    "context": "c2c572ed",
                    "modulemd": testmodule_mmd_c2c572ed
                }
            ],
            "meta": {"next": None}
        }

        mock_session().get.return_value = mock_res
        resolver = mbs_resolver.GenericResolver.create(tests.conf, backend='mbs')
        ret = resolver.get_module_modulemds('testmodule', 'master', version)
        nsvcs = set(
            '{}:{}:{}:{}'.format(m.peek_name(), m.peek_stream(),
                                 m.peek_version(), m.peek_context())
            for m in ret
        )
        expected = set(["testmodule:master:20180205135154:9c690d0e",
                        "testmodule:master:20180205135154:c2c572ed"])
        mbs_url = tests.conf.mbs_url
        expected_query = {
            "name": "testmodule",
            "stream": "master",
            "version": version,
            "verbose": True,
            "order_desc_by": "version",
            "page": 1,
            "per_page": 10,
            "state": "ready"
        }
        mock_session().get.assert_called_once_with(mbs_url, params=expected_query)
        assert nsvcs == expected

    @patch("requests.Session")
    def test_get_module_build_dependencies(self, mock_session, platform_mmd,
                                           testmodule_mmd_9c690d0e):
        """
        Tests that we return just direct build-time dependencies of testmodule.
        """
        mock_res = Mock()
        mock_res.ok.return_value = True
        mock_res.json.side_effect = [
            {
                "items": [
                    {
                        "name": "testmodule",
                        "stream": "master",
                        "version": "20180205135154",
                        "context": "9c690d0e",
                        "modulemd": testmodule_mmd_9c690d0e
                    }
                ],
                "meta": {"next": None}
            }, {
                "items": [
                    {
                        "name": "platform",
                        "stream": "f28",
                        "version": "3",
                        "context": "00000000",
                        "modulemd": platform_mmd,
                        "koji_tag": "module-f28-build"
                    }
                ],
                "meta": {"next": None}
            }
        ]

        mock_session().get.return_value = mock_res
        expected = set(['module-f28-build'])
        resolver = mbs_resolver.GenericResolver.create(tests.conf, backend='mbs')
        result = resolver.get_module_build_dependencies(
            'testmodule', 'master', '20180205135154', '9c690d0e').keys()

        expected_queries = [{
            "name": "testmodule",
            "stream": "master",
            "version": "20180205135154",
            "context": "9c690d0e",
            "verbose": True,
            "order_desc_by": "version",
            "page": 1,
            "per_page": 10,
            "state": "ready"
        }, {
            "name": "platform",
            "stream": "f28",
            "version": "3",
            "context": "00000000",
            "verbose": True,
            "order_desc_by": "version",
            "page": 1,
            "per_page": 10,
            "state": "ready"
        }]

        mbs_url = tests.conf.mbs_url
        expected_calls = [call(mbs_url, params=expected_queries[0]),
                          call(mbs_url, params=expected_queries[1])]
        mock_session().get.mock_calls = expected_calls
        assert mock_session().get.call_count == 2
        assert set(result) == expected

    @patch("requests.Session")
    def test_get_module_build_dependencies_empty_buildrequires(self, mock_session,
                                                               testmodule_mmd_9c690d0e):

        mmd = Modulemd.Module().new_from_string(testmodule_mmd_9c690d0e)
        # Wipe out the dependencies
        mmd.set_dependencies()
        xmd = glib.from_variant_dict(mmd.get_xmd())
        xmd['mbs']['buildrequires'] = {}
        mmd.set_xmd(glib.dict_values(xmd))

        mock_res = Mock()
        mock_res.ok.return_value = True
        mock_res.json.side_effect = [
            {
                "items": [
                    {
                        "name": "testmodule",
                        "stream": "master",
                        "version": "20180205135154",
                        "context": "9c690d0e",
                        "modulemd": mmd.dumps(),
                        "build_deps": []
                    }
                ],
                "meta": {"next": None}
            }
        ]

        mock_session().get.return_value = mock_res

        expected = set()

        resolver = mbs_resolver.GenericResolver.create(tests.conf, backend='mbs')
        result = resolver.get_module_build_dependencies(
            'testmodule', 'master', '20180205135154', '9c690d0e').keys()
        mbs_url = tests.conf.mbs_url
        expected_query = {
            "name": "testmodule",
            "stream": "master",
            "version": "20180205135154",
            "context": "9c690d0e",
            "verbose": True,
            "order_desc_by": "version",
            "page": 1,
            "per_page": 10,
            "state": "ready"
        }
        mock_session().get.assert_called_once_with(mbs_url, params=expected_query)
        assert set(result) == expected

    @patch("requests.Session")
    def test_resolve_profiles(self, mock_session, formatted_testmodule_mmd, platform_mmd):

        mock_res = Mock()
        mock_res.ok.return_value = True
        mock_res.json.return_value = {
            "items": [
                {
                    "name": "platform",
                    "stream": "f28",
                    "version": "3",
                    "context": "00000000",
                    "modulemd": platform_mmd
                }
            ],
            "meta": {"next": None}
        }

        mock_session().get.return_value = mock_res
        resolver = mbs_resolver.GenericResolver.create(tests.conf, backend='mbs')
        result = resolver.resolve_profiles(formatted_testmodule_mmd,
                                           ('buildroot', 'srpm-buildroot'))
        expected = {
            'buildroot':
                set(['unzip', 'tar', 'cpio', 'gawk', 'gcc', 'xz', 'sed',
                     'findutils', 'util-linux', 'bash', 'info', 'bzip2',
                     'grep', 'redhat-rpm-config', 'fedora-release',
                     'diffutils', 'make', 'patch', 'shadow-utils', 'coreutils',
                     'which', 'rpm-build', 'gzip', 'gcc-c++']),
            'srpm-buildroot':
                set(['shadow-utils', 'redhat-rpm-config', 'rpm-build',
                     'fedora-release', 'fedpkg-minimal', 'gnupg2',
                     'bash'])
        }

        mbs_url = tests.conf.mbs_url
        expected_query = {
            "name": "platform",
            "stream": "f28",
            "version": "3",
            "context": "00000000",
            "verbose": True,
            "order_desc_by": "version",
            "page": 1,
            "per_page": 10,
            "state": "ready"
        }

        mock_session().get.assert_called_once_with(mbs_url, params=expected_query)
        assert result == expected

    @patch("module_build_service.config.Config.system",
           new_callable=PropertyMock, return_value="test")
    @patch("module_build_service.config.Config.mock_resultsdir",
           new_callable=PropertyMock,
           return_value=os.path.join(base_dir, 'staged_data', "local_builds"))
    def test_resolve_profiles_local_module(self, local_builds, conf_system,
                                           formatted_testmodule_mmd):
        tests.clean_database()
        with app.app_context():
            module_build_service.utils.load_local_builds(['platform'])

            resolver = mbs_resolver.GenericResolver.create(tests.conf, backend='mbs')
            result = resolver.resolve_profiles(formatted_testmodule_mmd,
                                               ('buildroot', 'srpm-buildroot'))
            expected = {
                'buildroot':
                    set(['foo']),
                'srpm-buildroot':
                    set(['bar'])
            }
            assert result == expected
