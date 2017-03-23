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

import vcr
import module_build_service.pdc as mbs_pdc

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
        result = mbs_pdc.get_module_build_dependencies(self.pdc, query)
        expected = [
            u'f26-modularity',
            # Should the list of deps should not include the original tag?
            # Probably not.
            u'module-base-runtime-master-20170315134803',
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
        result = mbs_pdc.get_module_build_dependencies(self.pdc, query)
        expected = [
            u'module-base-runtime-master-20170315134803',
            # Should the list of deps should not include the original tag?
            # Probably not.
            u'module-testmodule-master-20170322155247'
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
