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
from mock import patch

import module_build_service.auth
import module_build_service.errors
from os import path


class TestAuthModule(unittest.TestCase):
    def test_get_user_no_token(self):
        base_dir = path.abspath(path.dirname(__file__))
        client_secrets = path.join(base_dir, "client_secrets.json")
        with patch.dict('module_build_service.app.config', {'OIDC_CLIENT_SECRETS': client_secrets,
                                                            'OIDC_REQUIRED_SCOPE': 'mbs-scope'}):
            request = mock.MagicMock()
            request.cookies.return_value = {}

            with self.assertRaises(module_build_service.errors.Unauthorized) as cm:
                result = module_build_service.auth.get_user(request)

            self.assertEquals(str(cm.exception),
                "No 'authorization' header found.")

    @patch('module_build_service.auth._get_token_info')
    @patch('module_build_service.auth._get_user_info')
    def test_get_user_failure(self, get_user_info, get_token_info):
        base_dir = path.abspath(path.dirname(__file__))
        client_secrets = path.join(base_dir, "client_secrets.json")
        with patch.dict('module_build_service.app.config', {'OIDC_CLIENT_SECRETS': client_secrets,
                                                            'OIDC_REQUIRED_SCOPE': 'mbs-scope'}):
            # https://www.youtube.com/watch?v=G-LtddOgUCE
            name = "Joey Jo Jo Junior Shabadoo"
            mocked_get_token_info = {"active": False, "username": name,
                        "scope": "openid https://id.fedoraproject.org/scope/groups mbs-scope"}
            get_token_info.return_value = mocked_get_token_info

            get_user_info.return_value = {"groups":["group"]}

            headers = {"authorization": "Bearer foobar"}
            request = mock.MagicMock()
            request.headers.return_value = mock.MagicMock(spec_set=dict)
            request.headers.__getitem__.side_effect = headers.__getitem__
            request.headers.__setitem__.side_effect = headers.__setitem__
            request.headers.__contains__.side_effect = headers.__contains__

            with self.assertRaises(module_build_service.errors.Unauthorized) as cm:
                result = module_build_service.auth.get_user(request)

            self.assertEquals(str(cm.exception),
                "OIDC token invalid or expired.")

    @patch('module_build_service.auth._get_token_info')
    @patch('module_build_service.auth._get_user_info')
    def test_get_user_good(self, get_user_info, get_token_info):
        base_dir = path.abspath(path.dirname(__file__))
        client_secrets = path.join(base_dir, "client_secrets.json")
        with patch.dict('module_build_service.app.config', {'OIDC_CLIENT_SECRETS': client_secrets,
                                                            'OIDC_REQUIRED_SCOPE': 'mbs-scope'}):
            # https://www.youtube.com/watch?v=G-LtddOgUCE
            name = "Joey Jo Jo Junior Shabadoo"
            mocked_get_token_info = {"active": True, "username": name,
                        "scope": "openid https://id.fedoraproject.org/scope/groups mbs-scope"}
            get_token_info.return_value = mocked_get_token_info

            get_user_info.return_value = {"groups":["group"]}

            headers = {"authorization": "Bearer foobar"}
            request = mock.MagicMock()
            request.headers.return_value = mock.MagicMock(spec_set=dict)
            request.headers.__getitem__.side_effect = headers.__getitem__
            request.headers.__setitem__.side_effect = headers.__setitem__
            request.headers.__contains__.side_effect = headers.__contains__

            username, groups = module_build_service.auth.get_user(request)
            eq_(username, name)
            eq_(groups, set(get_user_info.return_value["groups"]))

    def test_disable_authentication(self):
        with patch.dict('module_build_service.app.config', {'NO_AUTH': True}, clear=True):
            request = mock.MagicMock()
            eq_(module_build_service.auth.get_user(request), None)

    @patch('module_build_service.auth.client_secrets', None)
    def test_misconfiguring_oidc_client_secrets_should_be_failed(self):
        request = mock.MagicMock()
        with self.assertRaises(module_build_service.errors.Forbidden) as cm:
            module_build_service.auth.get_user(request)

        self.assertEquals(str(cm.exception),
            "OIDC_CLIENT_SECRETS must be set in server config.")

    @patch('module_build_service.auth._get_token_info')
    @patch('module_build_service.auth._get_user_info')
    def test_get_required_scope_not_present(self, get_user_info, get_token_info):
        base_dir = path.abspath(path.dirname(__file__))
        client_secrets = path.join(base_dir, "client_secrets.json")
        with patch.dict('module_build_service.app.config', {'OIDC_CLIENT_SECRETS': client_secrets,
                                                            'OIDC_REQUIRED_SCOPE': 'mbs-scope'}):
            # https://www.youtube.com/watch?v=G-LtddOgUCE
            name = "Joey Jo Jo Junior Shabadoo"
            mocked_get_token_info = {"active": True, "username": name,
                        "scope": "openid https://id.fedoraproject.org/scope/groups"}
            get_token_info.return_value = mocked_get_token_info

            get_user_info.return_value = {"groups":["group"]}

            headers = {"authorization": "Bearer foobar"}
            request = mock.MagicMock()
            request.headers.return_value = mock.MagicMock(spec_set=dict)
            request.headers.__getitem__.side_effect = headers.__getitem__
            request.headers.__setitem__.side_effect = headers.__setitem__
            request.headers.__contains__.side_effect = headers.__contains__

            with self.assertRaises(module_build_service.errors.Unauthorized) as cm:
                result = module_build_service.auth.get_user(request)

            self.assertEquals(str(cm.exception),
                "Required OIDC scope 'mbs-scope' not present: "
                "['openid', 'https://id.fedoraproject.org/scope/groups']")

    @patch('module_build_service.auth._get_token_info')
    @patch('module_build_service.auth._get_user_info')
    def test_get_required_scope_not_set_in_cfg(self, get_user_info, get_token_info):
        base_dir = path.abspath(path.dirname(__file__))
        client_secrets = path.join(base_dir, "client_secrets.json")
        with patch.dict('module_build_service.app.config', {'OIDC_CLIENT_SECRETS': client_secrets}):
            # https://www.youtube.com/watch?v=G-LtddOgUCE
            name = "Joey Jo Jo Junior Shabadoo"
            mocked_get_token_info = {"active": True, "username": name,
                        "scope": "openid https://id.fedoraproject.org/scope/groups"}
            get_token_info.return_value = mocked_get_token_info

            get_user_info.return_value = {"groups":["group"]}

            headers = {"authorization": "Bearer foobar"}
            request = mock.MagicMock()
            request.headers.return_value = mock.MagicMock(spec_set=dict)
            request.headers.__getitem__.side_effect = headers.__getitem__
            request.headers.__setitem__.side_effect = headers.__setitem__
            request.headers.__contains__.side_effect = headers.__contains__

            with self.assertRaises(module_build_service.errors.Forbidden) as cm:
                result = module_build_service.auth.get_user(request)

            self.assertEquals(str(cm.exception),
                "OIDC_REQUIRED_SCOPE must be set in server config.")
