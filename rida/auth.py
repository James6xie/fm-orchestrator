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

from rida.errors import Unauthorized

import fedora.client


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


def get_username(environ):
    """ Extract the user's username from the WSGI environment. """

    if not "SSL_CLIENT_CERT_commonName" in environ:
        raise Unauthorized("No SSL client cert CN could be found to work with")

    return environ["SSL_CLIENT_CERT_commonName"]


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
