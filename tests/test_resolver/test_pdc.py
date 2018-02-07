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
#
# Written by Ralph Bean <rbean@redhat.com>

import os
import copy

from mock import patch, PropertyMock
import pytest

import module_build_service.resolver as mbs_resolver
import module_build_service.utils
import module_build_service.models
from module_build_service import app, db

import tests
import modulemd


base_dir = os.path.join(os.path.dirname(__file__), "..")


class TestPDCModule:

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

        resolver = mbs_resolver.GenericResolver.create(tests.conf, backend='pdc')
        variant_dict = resolver._get_variant_dict(dep)
        assert variant_dict == expected

    def test_get_module_simple_as_dict(self, pdc_module_active):
        query = {'name': 'testmodule', 'version': 'master'}
        resolver = mbs_resolver.GenericResolver.create(tests.conf, backend='pdc')
        result = resolver._get_module(query)
        assert result['variant_name'] == 'testmodule'
        assert result['variant_version'] == 'master'
        assert 'build_deps' in result

    @pytest.mark.parametrize('empty_buildrequires', [False, True])
    def test_get_module_build_dependencies(self, pdc_module_active, empty_buildrequires):
        """
        Tests that we return just direct build-time dependencies of testmodule.
        """
        expected = set(['module-f28-build'])
        if empty_buildrequires:
            expected = set()
            pdc_item = pdc_module_active.endpoints['unreleasedvariants']['GET'][-1]
            mmd = modulemd.ModuleMetadata()
            mmd.loads(pdc_item['modulemd'])
            mmd.buildrequires = {}
            mmd.xmd['mbs']['buildrequires'] = {}
            pdc_item.update({
                'modulemd': mmd.dumps(),
                'build_deps': []
            })
        query = {
            'name': 'testmodule',
            'version': 'master',
            'release': '20180205135154',
        }
        resolver = mbs_resolver.GenericResolver.create(tests.conf, backend='pdc')
        result = resolver.get_module_build_dependencies(query).keys()
        assert set(result) == expected

    def test_get_module_build_dependencies_recursive(self, pdc_module_active):
        """
        Tests that we return just direct build-time dependencies of testmodule.
        """
        # Add testmodule2 that requires testmodule
        pdc_module_active.endpoints['unreleasedvariants']['GET'].append(
            copy.deepcopy(pdc_module_active.endpoints['unreleasedvariants']['GET'][-1]))
        pdc_item = pdc_module_active.endpoints['unreleasedvariants']['GET'][-1]
        mmd = modulemd.ModuleMetadata()
        mmd.loads(pdc_item['modulemd'])
        mmd.name = 'testmodule2'
        mmd.version = 20180123171545
        mmd.requires['testmodule'] = 'master'
        mmd.xmd['mbs']['requires']['testmodule'] = {
            'filtered_rpms': [],
            'ref': '620ec77321b2ea7b0d67d82992dda3e1d67055b4',
            'stream': 'master',
            'version': '20180205135154'
        }
        pdc_item.update({
            'variant_id': 'testmodule2',
            'variant_name': 'testmodule2',
            'variant_release': str(mmd.version),
            'koji_tag': 'module-ae2adf69caf0e1b6',
            'modulemd': mmd.dumps()
        })

        query = {
            'name': 'testmodule2',
            'version': 'master',
            'release': '20180123171545',
        }
        resolver = mbs_resolver.GenericResolver.create(tests.conf, backend='pdc')
        result = resolver.get_module_build_dependencies(query).keys()
        assert set(result) == set(['module-f28-build'])

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
                ["platform", "parent", "child", "testmodule"])

            build = module_build_service.models.ModuleBuild.local_modules(
                db.session, "child", "master")
            resolver = mbs_resolver.GenericResolver.create(tests.conf, backend='pdc')
            result = resolver.get_module_build_dependencies(build[0].mmd()).keys()

            local_path = os.path.join(base_dir, 'staged_data', "local_builds")

            expected = [
                os.path.join(
                    local_path,
                    'module-platform-f28-3/results'),
                os.path.join(
                    local_path,
                    'module-parent-master-20170816080815/results'),
            ]
            assert set(result) == set(expected)

    def test_resolve_profiles(self, pdc_module_active):
        yaml_path = os.path.join(
            base_dir, 'staged_data', 'formatted_testmodule.yaml')
        mmd = modulemd.ModuleMetadata()
        mmd.load(yaml_path)
        resolver = mbs_resolver.GenericResolver.create(tests.conf, backend='pdc')
        result = resolver.resolve_profiles(mmd, ('buildroot', 'srpm-buildroot'))
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
        assert result == expected

    @patch("module_build_service.config.Config.system",
           new_callable=PropertyMock, return_value="test")
    @patch("module_build_service.config.Config.mock_resultsdir",
           new_callable=PropertyMock,
           return_value=os.path.join(base_dir, 'staged_data', "local_builds"))
    def test_resolve_profiles_local_module(self, local_builds, conf_system):
        with app.app_context():
            module_build_service.utils.load_local_builds(['platform'])

            yaml_path = os.path.join(
                base_dir, 'staged_data', 'formatted_testmodule.yaml')
            mmd = modulemd.ModuleMetadata()
            mmd.load(yaml_path)
            resolver = mbs_resolver.GenericResolver.create(tests.conf, backend='pdc')
            result = resolver.resolve_profiles(mmd, ('buildroot', 'srpm-buildroot'))
            expected = {
                'buildroot':
                    set(['foo']),
                'srpm-buildroot':
                    set(['bar'])
            }
            assert result == expected
