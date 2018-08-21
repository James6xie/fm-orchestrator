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
# Written by Matt Prahl <mprahl@redhat.com>

import os

from mock import patch, PropertyMock
import pytest

import module_build_service.resolver as mbs_resolver
from module_build_service import app, db, models, glib, utils, Modulemd
import tests


base_dir = os.path.join(os.path.dirname(__file__), "..")


class TestDBModule:

    def setup_method(self):
        tests.reuse_component_init_data()

    @pytest.mark.parametrize('empty_buildrequires', [False, True])
    def test_get_module_build_dependencies(self, empty_buildrequires):
        """
        Tests that the buildrequires of testmodule are returned
        """
        expected = set(['module-f28-build'])
        module = models.ModuleBuild.query.get(2)
        if empty_buildrequires:
            expected = set()
            module = models.ModuleBuild.query.get(2)
            mmd = module.mmd()
            # Wipe out the dependencies
            mmd.set_dependencies()
            xmd = glib.from_variant_dict(mmd.get_xmd())
            xmd['mbs']['buildrequires'] = {}
            mmd.set_xmd(glib.dict_values(xmd))
            module.modulemd = mmd.dumps()
            db.session.add(module)
            db.session.commit()
        resolver = mbs_resolver.GenericResolver.create(tests.conf, backend='db')
        result = resolver.get_module_build_dependencies(
            'testmodule', 'master', '20170109091357', '78e4a6fd').keys()
        assert set(result) == expected

    def test_get_module_build_dependencies_recursive(self):
        """
        Tests that the buildrequires are returned when it is two layers deep
        """
        # Add testmodule2 that requires testmodule
        module = models.ModuleBuild.query.get(3)
        mmd = module.mmd()
        mmd.set_name('testmodule2')
        mmd.set_version(20180123171545)
        requires = mmd.get_dependencies()[0].get_requires()
        requires['testmodule'] = Modulemd.SimpleSet()
        requires['testmodule'].add('master')
        mmd.get_dependencies()[0].set_requires(requires)
        xmd = glib.from_variant_dict(mmd.get_xmd())
        xmd['mbs']['requires']['testmodule'] = {
            'filtered_rpms': [],
            'ref': '620ec77321b2ea7b0d67d82992dda3e1d67055b4',
            'stream': 'master',
            'version': '20180205135154'
        }
        mmd.set_xmd(glib.dict_values(xmd))
        module.modulemd = mmd.dumps()
        module.name = 'testmodule2'
        module.version = str(mmd.get_version())
        module.koji_tag = 'module-ae2adf69caf0e1b6'

        resolver = mbs_resolver.GenericResolver.create(tests.conf, backend='db')
        result = resolver.get_module_build_dependencies(
            'testmodule2', 'master', '20180123171545', 'c40c156c').keys()
        assert set(result) == set(['module-f28-build'])

    @patch("module_build_service.config.Config.system",
           new_callable=PropertyMock, return_value="test")
    @patch("module_build_service.config.Config.mock_resultsdir",
           new_callable=PropertyMock,
           return_value=os.path.join(base_dir, 'staged_data', "local_builds"))
    def test_get_module_build_dependencies_recursive_requires(
            self, resultdir, conf_system):
        """
        Tests that it returns the requires of the buildrequires recursively
        """
        with app.app_context():
            utils.load_local_builds(["platform", "parent", "child", "testmodule"])

            build = models.ModuleBuild.local_modules(
                db.session, "child", "master")
            resolver = mbs_resolver.GenericResolver.create(tests.conf, backend='db')
            result = resolver.get_module_build_dependencies(mmd=build[0].mmd()).keys()

            local_path = os.path.join(base_dir, 'staged_data', "local_builds")

            expected = [
                os.path.join(
                    local_path,
                    'module-parent-master-20170816080815/results'),
            ]
            assert set(result) == set(expected)

    def test_resolve_requires(self):
        build = models.ModuleBuild.query.get(2)
        resolver = mbs_resolver.GenericResolver.create(tests.conf, backend='db')
        result = resolver.resolve_requires([":".join([
            build.name, build.stream, build.version, build.context])])

        assert result == {
            'testmodule': {
                'stream': 'master', 'version': '20170109091357', 'context': u'78e4a6fd',
                'ref': 'ff1ea79fc952143efeed1851aa0aa006559239ba'}}

    def test_resolve_profiles(self):
        """
        Tests that the profiles get resolved recursively
        """
        mmd = models.ModuleBuild.query.get(2).mmd()
        resolver = mbs_resolver.GenericResolver.create(tests.conf, backend='db')
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
        """
        Test that profiles get resolved recursively on local builds
        """
        with app.app_context():
            utils.load_local_builds(['platform'])
            mmd = models.ModuleBuild.query.get(2).mmd()
            resolver = mbs_resolver.GenericResolver.create(tests.conf, backend='mbs')
            result = resolver.resolve_profiles(mmd, ('buildroot', 'srpm-buildroot'))
            expected = {
                'buildroot':
                    set(['foo']),
                'srpm-buildroot':
                    set(['bar'])
            }
            assert result == expected
