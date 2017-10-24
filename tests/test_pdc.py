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
#
# Written by Ralph Bean <rbean@redhat.com>

import os

import unittest
from mock import patch, PropertyMock

import vcr
import module_build_service.pdc as mbs_pdc
import module_build_service.utils
import module_build_service.models
from module_build_service import app, db

import tests
import modulemd


base_dir = os.path.dirname(__file__)
cassette_dir = base_dir + '/vcr-request-data/'


class TestPDCModule(unittest.TestCase):

    def setUp(self):
        filename = cassette_dir + self.id()
        self.vcr = vcr.use_cassette(filename)
        self.vcr.__enter__()

        self.pdc = mbs_pdc.get_pdc_client_session(tests.conf)

    def tearDown(self):
        self.vcr.__exit__()

    def test_get_variant_dict_module_dict_active(self):
        """
        Tests that "active" is honored by get_variant_dict(...).
        """
        dep = {
            'name': "platform",
            'version': "master",
            'active': True,
        }
        expected = {
            'active': True,
            'variant_id': 'platform',
            'variant_version': 'master'
        }

        variant_dict = mbs_pdc.get_variant_dict(dep)
        self.assertEqual(variant_dict, expected)

    def test_get_module_simple_as_dict(self):
        query = {'name': 'testmodule', 'version': 'master'}
        result = mbs_pdc.get_module(self.pdc, query)
        assert result['variant_name'] == 'testmodule'
        assert result['variant_version'] == 'master'
        assert 'build_deps' in result

    def test_get_module_build_dependencies(self):
        """
        Tests that we return proper koji_tags with base-runtime
        build-time dependencies.
        """
        query = {
            'name': 'base-runtime',
            'version': 'master',
            'release': '20170315134803',
        }
        result = mbs_pdc.get_module_build_dependencies(self.pdc, query).keys()
        expected = [
            u'module-bootstrap-rawhide',
        ]
        self.assertEqual(set(result), set(expected))

    def test_get_module_build_dependencies_single_level(self):
        """
        Tests that we return just direct build-time dependencies of testmodule.
        It means just testmodule itself and base-runtime, but no f26-modularity
        (koji tag of bootstrap module which is build-require of base-runtime).
        """
        query = {
            'name': 'testmodule',
            'version': 'master',
            'release': '20170322155247'
        }
        result = mbs_pdc.get_module_build_dependencies(self.pdc, query).keys()
        expected = [
            u'module-base-runtime-master-20170315134803',
        ]
        self.assertEqual(set(result), set(expected))

    @patch("module_build_service.config.Config.system",
           new_callable=PropertyMock, return_value="test")
    @patch("module_build_service.config.Config.mock_resultsdir",
           new_callable=PropertyMock,
           return_value=os.path.join(base_dir, 'staged_data', "local_builds"))
    def test_get_module_build_dependencies_recursive_requires(
            self, resultdir, conf_system):
        """
        Tests that we return Requires of Buildrequires of a module
        recursively.
        """
        with app.app_context():
            module_build_service.utils.load_local_builds(
                ["base-runtime", "parent", "child", "testmodule"])

            build = module_build_service.models.ModuleBuild.local_modules(
                db.session, "child", "master")
            result = mbs_pdc.get_module_build_dependencies(self.pdc, build[0].mmd()).keys()

            local_path = os.path.join(base_dir, 'staged_data', "local_builds")

            expected = [
                os.path.join(
                    local_path,
                    'module-base-runtime-master-20170816080815/results'),
                os.path.join(
                    local_path,
                    'module-parent-master-20170816080815/results'),
            ]
            self.assertEqual(set(result), set(expected))

    def test_resolve_profiles(self):
        current_dir = os.path.dirname(__file__)
        yaml_path = os.path.join(
            current_dir, 'staged_data', 'formatted_testmodule.yaml')
        mmd = modulemd.ModuleMetadata()
        mmd.load(yaml_path)
        result = mbs_pdc.resolve_profiles(self.pdc, mmd,
                                          ('buildroot', 'srpm-buildroot'))
        expected = {
            'buildroot':
                set(['unzip', 'tar', 'cpio', 'gawk', 'gcc', 'xz', 'sed',
                     'findutils', 'util-linux', 'bash', 'info', 'bzip2',
                     'grep', 'redhat-rpm-config', 'fedora-modular-release',
                     'diffutils', 'make', 'patch', 'shadow-utils', 'coreutils',
                     'which', 'rpm-build', 'gzip', 'gcc-c++']),
            'srpm-buildroot':
                set(['shadow-utils', 'redhat-rpm-config', 'rpm-build',
                     'fedora-modular-release', 'fedpkg-minimal', 'gnupg2',
                     'bash'])
        }
        self.assertEqual(result, expected)

    @patch("module_build_service.config.Config.system",
           new_callable=PropertyMock, return_value="test")
    @patch("module_build_service.config.Config.mock_resultsdir",
           new_callable=PropertyMock,
           return_value=os.path.join(base_dir, 'staged_data', "local_builds"))
    def test_resolve_profiles_local_module(self, local_builds, conf_system):
        with app.app_context():
            module_build_service.utils.load_local_builds(["base-runtime"])

            current_dir = os.path.dirname(__file__)
            yaml_path = os.path.join(
                current_dir, 'staged_data', 'formatted_testmodule.yaml')
            mmd = modulemd.ModuleMetadata()
            mmd.load(yaml_path)
            result = mbs_pdc.resolve_profiles(self.pdc, mmd, ('buildroot', 'srpm-buildroot'))
            expected = {
                'buildroot':
                    set(['foo']),
                'srpm-buildroot':
                    set(['bar'])
            }
            self.assertEqual(result, expected)
