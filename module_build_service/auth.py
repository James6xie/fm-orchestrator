# -*- coding: utf-8 -*-
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
# Written by Jan Kaluza <jkaluza@redhat.com>

"""Auth system based on the client certificate and FAS account"""

from werkzeug.serving import WSGIRequestHandler

from module_build_service.errors import Unauthorized
from module_build_service import app, log

import fedora.client
import httplib2
import json
from six.moves.urllib.parse import urlencode

def _json_loads(content):
    if not isinstance(content, str):
        content = content.decode('utf-8')
    return json.loads(content)

client_secrets = None

def _load_secrets():
    global client_secrets
    if client_secrets:
        return

    if not "OIDC_CLIENT_SECRETS" in app.config:
        log.warn("To support authorization, OIDC_CLIENT_SECRETS has to be set.")
        return

    secrets = _json_loads(open(app.config['OIDC_CLIENT_SECRETS'],
                                'r').read())
    client_secrets = list(secrets.values())[0]

def get_token_info(token):
    """
    Asks the token_introspection_uri for the validity of a token.
    """
    if not client_secrets:
        return None

    request = {'token': token,
                'token_type_hint': 'Bearer',
                'client_id': client_secrets['client_id'],
                'client_secret': client_secrets['client_secret']}
    headers = {'Content-type': 'application/x-www-form-urlencoded'}

    resp, content = httplib2.Http().request(
        client_secrets['token_introspection_uri'], 'POST',
        urlencode(request), headers=headers)

    return _json_loads(content)

def get_username(request):
    """
    Returns the client's username based on the OIDC token provided.
    """

    _load_secrets()

    if not "oidc_token" in request.cookies:
        raise Unauthorized("Cannot verify OIDC token: No 'oidc_token' "
            "cookie found.")

    token = request.cookies["oidc_token"]
    try:
        data = get_token_info(token)
    except Exception as e:
        raise Unauthorized("Cannot verify OIDC token: %s" % str(e))

    if not "active" in data or not data["active"]:
        raise Unauthorized("OIDC token invalid or expired.")

    #TODO: Once we will get our own scope registered in Fedora infra,
    # we can start checking it here.
    return data["username"]

def assert_is_packager(username, fas_kwargs):
    """ Assert that a user is a packager by consulting FAS.

    When user is not a packager (is not in the packager FAS group), an
    exception is raised.

    Note that `fas_kwargs` must contain values for `base_url`, `username`, and
    `password`.  These are required arguments for authenticating with FAS.
    (Rida needs its own service account/password to talk to FAS).
    """

    FAS = fedora.client.AccountSystem(**fas_kwargs)
    person = FAS.person_by_username(username)

    # Check that they have even applied in the first place...
    if not 'packager' in person['group_roles']:
        raise Unauthorized("%s is not in the packager group" % username)

    # Check more closely to make sure they're approved.
    if person['group_roles']['packager']['role_status'] != 'approved':
        raise Unauthorized("%s is not approved in the packager group" % username)
