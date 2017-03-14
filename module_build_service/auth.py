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

from module_build_service.errors import Unauthorized, Forbidden
from module_build_service import app, log

import requests
import json


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
        raise Forbidden("OIDC_CLIENT_SECRETS must be set in server config.")

    secrets = _json_loads(open(app.config['OIDC_CLIENT_SECRETS'],
                                'r').read())
    client_secrets = list(secrets.values())[0]

def _get_token_info(token):
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

    resp = requests.post(client_secrets['token_introspection_uri'], data=request, headers=headers)
    return resp.json()


def _get_user_info(token):
    """
    Asks the userinfo_uri for more information on a user.
    """
    if not client_secrets:
        return None

    headers = {'authorization': 'Bearer ' + token}
    resp = requests.get(client_secrets['userinfo_uri'], headers=headers)
    return resp.json()


def get_user(request):
    """
    Returns the client's username and groups based on the OIDC token provided.
    """

    if app.config['NO_AUTH']:
        log.debug("Authorization is disabled.")
        return

    _load_secrets()

    if not "authorization" in request.headers:
        raise Unauthorized("No 'authorization' header found.")

    header = request.headers['authorization'].strip()
    prefix = 'Bearer '
    if not header.startswith(prefix):
        raise Unauthorized("Authorization headers must start with %r" % prefix)

    token = header[len(prefix):].strip()
    try:
        data = _get_token_info(token)
    except Exception as e:
        error = "Cannot verify OIDC token: %s" % str(e)
        log.exception(error)
        raise Exception(error)

    if not data or not "active" in data or not data["active"]:
        raise Unauthorized("OIDC token invalid or expired.")

    if not "OIDC_REQUIRED_SCOPE" in app.config:
        raise Forbidden("OIDC_REQUIRED_SCOPE must be set in server config.")

    presented_scopes = data['scope'].split(' ')
    required_scopes = [
        'openid',
        'https://id.fedoraproject.org/scope/groups',
        app.config["OIDC_REQUIRED_SCOPE"],
    ]
    for scope in required_scopes:
        if scope not in presented_scopes:
            raise Unauthorized("Required OIDC scope %r not present: %r" % (
                scope, presented_scopes))

    try:
        extended_data = _get_user_info(token)
    except Exception as e:
        error = "Cannot verify determine user groups:  %s" % str(e)
        log.exception(error)
        raise Exception(error)

    try:
        groups = set(extended_data['groups'])
    except Exception as e:
        error = "Could not find groups in UserInfo from OIDC %s" % str(e)
        log.exception(extended_data)
        raise Exception(error)

    return data["username"], groups
