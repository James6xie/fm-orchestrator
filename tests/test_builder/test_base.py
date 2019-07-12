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
# Written by Jan Kaluza <jkaluza@redhat.com>

import mock

import module_build_service.models
import module_build_service.builder
import module_build_service.resolver

from tests import init_data

from module_build_service.builder import GenericBuilder
from mock import patch


class TestGenericBuilder:
    def setup_method(self, test_method):
        init_data(1)

    @patch("module_build_service.resolver.DBResolver")
    @patch("module_build_service.builder.base.GenericResolver")
    def test_default_buildroot_groups_cache(self, generic_resolver, resolver, db_session):
        mbs_groups = {"buildroot": [], "srpm-buildroot": []}

        resolver = mock.MagicMock()
        resolver.backend = "mbs"
        resolver.resolve_profiles.return_value = mbs_groups

        expected_groups = {"build": [], "srpm-build": []}

        module = module_build_service.models.ModuleBuild.get_by_id(db_session, 1)

        generic_resolver.create.return_value = resolver
        # Call default_buildroot_groups, the result should be cached.
        ret = GenericBuilder.default_buildroot_groups(db_session, module)
        assert ret == expected_groups
        resolver.resolve_profiles.assert_called_once()
        resolver.resolve_profiles.reset_mock()

        # Now try calling it again to verify resolve_profiles is not called,
        # because it is cached.
        generic_resolver.create.return_value = resolver
        ret = GenericBuilder.default_buildroot_groups(db_session, module)
        assert ret == expected_groups
        resolver.resolve_profiles.assert_not_called()
        resolver.resolve_profiles.reset_mock()

        # And now try clearing the cache and call it again.
        generic_resolver.create.return_value = resolver
        GenericBuilder.clear_cache(module)
        ret = GenericBuilder.default_buildroot_groups(db_session, module)
        assert ret == expected_groups
        resolver.resolve_profiles.assert_called_once()

    def test_get_build_weights(self):
        weights = GenericBuilder.get_build_weights(["httpd", "apr"])
        assert weights == {"httpd": 1.5, "apr": 1.5}
