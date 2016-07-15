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

from flask import Flask, request
from werkzeug.serving import WSGIRequestHandler
import requests
import json

class ClientCertRequestHandler(WSGIRequestHandler):
    """
    WSGIRequestHandler subclass adding SSL_CLIENT_CERT_* variables
    to `request.environ` dict when the client certificate is set and
    is signed by CA configured in `conf.ssl_ca_certificate_file`.
    """

    def make_environ(self):
        environ = WSGIRequestHandler.make_environ(self)

        try:
            cert = self.request.getpeercert(False)
        except AttributeError:
            cert = None

        if cert and "subject" in cert:
            for keyval in cert["subject"]:
                key, val = keyval[0]
                environ["SSL_CLIENT_CERT_" + key] = val
        return environ

def is_packager(pkgdb_api_url):
    """
    Returns the username of user associated with current request by checking
    client cert's commonName and pkgdb database API.

    When user is not a packager (is not in pkgdb), returns None.
    """
    if not "SSL_CLIENT_CERT_commonName" in request.environ:
        return None

    username = request.environ["SSL_CLIENT_CERT_commonName"]

    acl_url = pkgdb_api_url + "/packager/package/" + username

    resp = requests.get(acl_url)
    try:
        resp.raise_for_status()
    except:
        return None

    try:
        r = json.loads(resp.content.decode('utf-8'))
    except:
        return None

    if r["output"] == "ok":
        return username

    return None
