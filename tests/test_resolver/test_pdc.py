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

from mock import patch, PropertyMock
import pytest

import module_build_service.resolver as mbs_resolver
import module_build_service.utils
import module_build_service.models
from module_build_service import app
from module_build_service import glib, Modulemd
import tests


base_dir = os.path.join(os.path.dirname(__file__), "..")


class TestPDCModule:

    def test_get_module_modulemds_nsvc(self, pdc_module_active_two_contexts):
        resolver = mbs_resolver.GenericResolver.create(tests.conf, backend='pdc')
        ret = resolver.get_module_modulemds('testmodule', 'master', '20180205135154', '9c690d0e')
        nsvcs = set(m.dup_nsvc() for m in ret)
        expected = set(["testmodule:master:125a91f56532:9c690d0e"])
        assert nsvcs == expected

    @pytest.mark.parametrize('kwargs', [{'version': '20180205135154'}, {}])
    def test_get_module_modulemds_partial(self, pdc_module_active_two_contexts, kwargs):
        resolver = mbs_resolver.GenericResolver.create(tests.conf, backend='pdc')
        ret = resolver.get_module_modulemds('testmodule', 'master', **kwargs)
        nsvcs = set(m.dup_nsvc() for m in ret)
        expected = set(["testmodule:master:125a91f56532:9c690d0e",
                        "testmodule:master:125a91f56532:c2c572ed"])
        assert nsvcs == expected

    @pytest.mark.parametrize('empty_buildrequires', [False, True])
    def test_get_module_build_dependencies(self, pdc_module_active, empty_buildrequires):
        """
        Tests that we return just direct build-time dependencies of testmodule.
        """
        expected = set(['module-f28-build'])
        if empty_buildrequires:
            expected = set()
            pdc_item = pdc_module_active.endpoints['unreleasedvariants']['GET'][-1]
            mmd = Modulemd.Module().new_from_string(pdc_item['modulemd'])
            # Wipe out the dependencies
            mmd.set_dependencies()
            xmd = glib.from_variant_dict(mmd.get_xmd())
            xmd['mbs']['buildrequires'] = {}
            mmd.set_xmd(glib.dict_values(xmd))
            pdc_item.update({
                'modulemd': mmd.dumps(),
                'build_deps': []
            })
        resolver = mbs_resolver.GenericResolver.create(tests.conf, backend='pdc')
        result = resolver.get_module_build_dependencies(
            'testmodule', 'master', '20180205135154', '9c690d0e').keys()
        assert set(result) == expected

    def test_resolve_profiles(self, pdc_module_active):
        yaml_path = os.path.join(
            base_dir, 'staged_data', 'formatted_testmodule.yaml')
        mmd = Modulemd.Module().new_from_file(yaml_path)
        mmd.upgrade()
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
        tests.clean_database()
        with app.app_context():
            module_build_service.utils.load_local_builds(['platform'])

            yaml_path = os.path.join(
                base_dir, 'staged_data', 'formatted_testmodule.yaml')
            mmd = Modulemd.Module().new_from_file(yaml_path)
            mmd.upgrade()
            resolver = mbs_resolver.GenericResolver.create(tests.conf, backend='pdc')
            result = resolver.resolve_profiles(mmd, ('buildroot', 'srpm-buildroot'))
            expected = {
                'buildroot':
                    set(['foo']),
                'srpm-buildroot':
                    set(['bar'])
            }
            assert result == expected
