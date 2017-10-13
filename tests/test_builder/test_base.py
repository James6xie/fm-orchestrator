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

import unittest
import koji

import module_build_service.models
import module_build_service.builder

from tests import conf, init_data, db

from module_build_service.builder import GenericBuilder
from mock import patch


class TestGenericBuilder(unittest.TestCase):

    def setUp(self):
        init_data()
        self.module = module_build_service.models.ModuleBuild.query.filter_by(id=1).one()

    @patch('module_build_service.pdc.resolve_profiles')
    def test_default_buildroot_groups_cache(self, resolve_profiles):
        pdc_groups = {
            "buildroot": [],
            "srpm-buildroot": []
        }
        resolve_profiles.return_value = pdc_groups

        expected_groups = {
            "build": [],
            "srpm-build": []
        }

        # Call default_buildroot_groups, the result should be cached.
        ret = GenericBuilder.default_buildroot_groups(db.session, self.module)
        self.assertEqual(ret, expected_groups)
        resolve_profiles.assert_called_once()
        resolve_profiles.reset_mock()

        # Now try calling it again to verify resolve_profiles is not called,
        # because it is cached.
        ret = GenericBuilder.default_buildroot_groups(db.session, self.module)
        self.assertEqual(ret, expected_groups)
        resolve_profiles.assert_not_called()
        resolve_profiles.reset_mock()

        # And now try clearing the cache and call it again.
        GenericBuilder.clear_cache(self.module)
        ret = GenericBuilder.default_buildroot_groups(db.session, self.module)
        self.assertEqual(ret, expected_groups)
        resolve_profiles.assert_called_once()
