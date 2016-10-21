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
# Written by Ralph Bean <rbean@redhat.com>

from nose.tools import raises, eq_


import unittest
import mock

import module_build_service.auth
import module_build_service.errors


class TestAuthModule(unittest.TestCase):
    @raises(module_build_service.errors.Unauthorized)
    def test_get_username_failure(self):
        module_build_service.auth.get_username({})

    def test_get_username_good(self):
        # https://www.youtube.com/watch?v=G-LtddOgUCE
        name = "Joey Jo Jo Junior Shabadoo"
        environ = {'SSL_CLIENT_CERT_commonName': name}
        result = module_build_service.auth.get_username(environ)
        eq_(result, name)

    @mock.patch('fedora.client.AccountSystem')
    def test_assert_is_packager(self, AccountSystem):
        FAS = mock.MagicMock()
        FAS.person_by_username.return_value = {
            'group_roles': {
                'packager': {
                    'role_status': 'approved',
                },
            },
        }
        AccountSystem.return_value = FAS
        # This should not raise an exception
        module_build_service.auth.assert_is_packager('ralph', dict())

    @raises(module_build_service.errors.Unauthorized)
    @mock.patch('fedora.client.AccountSystem')
    def test_assert_is_packager_failure(self, AccountSystem):
        FAS = mock.MagicMock()
        FAS.person_by_username.return_value = {
            'group_roles': {
                'packager': {
                    'role_status': 'FAILLLL',
                },
            },
        }
        AccountSystem.return_value = FAS
        # This should not raise an exception
        module_build_service.auth.assert_is_packager('ralph', dict())
