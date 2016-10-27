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
# Written by Petr Šabata <contyk@redhat.com>

"""Configuration handler functions."""

import six

from module_build_service import app
from module_build_service import logger


def from_app_config():
    """ Create the configuration instance from the values in app.config
    """
    conf = Config()
    for key, value in app.config.items():
        setattr(conf, key.lower(), value)
    return conf


class Config(object):
    """Class representing the orchestrator configuration."""

    def __init__(self):
        """Initialize the Config object."""
        self._system = ""
        self._db = ""
        self._polling_interval = 0
        self._pdc_url = ""
        self._pdc_insecure = False
        self._pdc_develop = False
        self._koji_config = None
        self._koji_profile = None
        self._koji_arches = None
        self._koji_build_priority = 10
        self._koji_repository_url = None
        self._rpms_default_repository = ""
        self._rpms_allow_repository = False
        self._rpms_default_cache = ""
        self._rpms_allow_cache = False
        self._ssl_certificate_file = ""
        self._ssl_certificate_key_file = ""
        self._ssl_ca_certificate_file = ""
        self._pkgdb_api_url = ""
        self._fas_url = ""
        self._fas_username = ""
        self._fas_password = ""
        self._require_packager = True
        self._log_backend = ""
        self._log_file = ""
        self._log_level = 0
        self._krb_keytab = None
        self._krb_principal = None
        self._krb_ccache = "/tmp/krb5cc_module_build_service"
        self._messaging = ""
        self._amq_recv_addresses = []
        self._amq_dest_address = ""
        self._amq_cert_file = ""
        self._amq_private_key_file = ""
        self._amq_trusted_cert_file = ""

    @property
    def system(self):
        """The buildsystem to use."""
        return self._system

    @system.setter
    def system(self, s):
        s = str(s)
        if s not in ("koji", "copr"):
            raise ValueError("Unsupported buildsystem.")
        self._system = s

    @property
    def messaging(self):
        """The messaging system to use."""
        return self._messaging

    @messaging.setter
    def messaging(self, s):
        s = str(s)
        if s not in ("fedmsg" , "amq"):
            raise ValueError("Unsupported messaging system.")
        self._messaging = s

    @property
    def amq_recv_addresses(self):
        """Apache MQ broker url to receive messages."""
        return self._amq_recv_addresses

    @amq_recv_addresses.setter
    def amq_recv_addresses(self, l):
        assert isinstance(l, list) or isinstance(l, tuple)
        self._amq_recv_addresses = list(l)

    @property
    def amq_dest_address(self):
        """Apache MQ broker address to send messages"""
        return self._amq_dest_address

    @amq_dest_address.setter
    def amq_dest_address(self, s):
        self._amq_dest_address = str(s)

    @property
    def amq_cert_file(self):
        """Certificate for Apache MQ broker auth."""
        return self._amq_cert_file

    @amq_cert_file.setter
    def amq_cert_file(self, s):
        self._amq_cert_file = str(s)

    @property
    def amq_private_key_file(self):
        """Private key for Apache MQ broker auth."""
        return self._amq_private_key_file

    @amq_private_key_file.setter
    def amq_private_key_file(self, s):
        self._amq_private_key_file = str(s)

    @property
    def amq_trusted_cert_file(self):
        """Trusted certificate for ssl connection."""
        return self._amq_trusted_cert_file

    @amq_trusted_cert_file.setter
    def amq_trusted_cert_file(self, s):
        s = str(s)
        self._amq_trusted_cert_file = s


    @property
    def db(self):
        """RDB URL."""
        return self._db

    @db.setter
    def db(self, s):
        self._db = str(s)

    @property
    def pdc_url(self):
        """PDC URL."""
        return self._pdc_url

    @pdc_url.setter
    def pdc_url(self, s):
        self._pdc_url = str(s)

    @property
    def pdc_insecure(self):
        """Allow insecure connection to PDC."""
        return self._pdc_insecure

    @pdc_insecure.setter
    def pdc_insecure(self, b):
        self._pdc_insecure = bool(b)

    @property
    def pdc_develop(self):
        """PDC Development mode, basically noauth."""
        return self._pdc_develop

    @pdc_develop.setter
    def pdc_develop(self, b):
        self._pdc_develop = bool(b)

    @property
    def polling_interval(self):
        """Polling interval, in seconds."""
        return self._polling_interval

    @polling_interval.setter
    def polling_interval(self, i):
        if not isinstance(i, int):
            raise TypeError("polling_interval needs to be an int")
        if i < 0:
            raise ValueError("polling_interval must be >= 0")
        self._polling_interval = i

    @property
    def koji_config(self):
        """Koji URL."""
        return self._koji_config

    @koji_config.setter
    def koji_config(self, s):
        self._koji_config = str(s)

    @property
    def koji_profile(self):
        """Koji URL."""
        return self._koji_profile

    @koji_profile.setter
    def koji_profile(self, s):
        self._koji_profile = str(s)

    @property
    def koji_arches(self):
        """Koji architectures."""
        return self._koji_arches

    @koji_arches.setter
    def koji_arches(self, s):
        self._koji_arches = list(s)

    @property
    def koji_repository_url(self):
        return self._koji_repository_url

    @koji_repository_url.setter
    def koji_repository_url(self, s):
        self._koji_repository_url = str(s)

    @property
    def koji_build_priority(self):
        return self._koji_build_priority

    @koji_build_priority.setter
    def koji_build_priority(self, i):
        if not isinstance(i, int):
            raise TypeError("koji_build_priority needs to be an int")
        self._koji_build_priority = i

    @property
    def scmurls(self):
        """Allowed SCM URLs."""
        return self._scmurls

    @scmurls.setter
    def scmurls(self, l):
        if not isinstance(l, list):
            raise TypeError("scmurls needs to be a list.")
        self._scmurls = [str(x) for x in l]

    @property
    def rpms_default_repository(self):
        return self._rpms_default_repository

    @rpms_default_repository.setter
    def rpms_default_repository(self, s):
        rpm_repo = str(s)
        if rpm_repo[-1] != '/':
            rpm_repo = rpm_repo + '/'
        self._rpms_default_repository = rpm_repo

    @property
    def rpms_allow_repository(self):
        return self._rpms_allow_repository

    @rpms_allow_repository.setter
    def rpms_allow_repository(self, b):
        if not isinstance(b, bool):
            raise TypeError("rpms_allow_repository must be a bool.")
        self._rpms_allow_repository = b

    @property
    def rpms_default_cache(self):
        return self._rpms_default_cache

    @rpms_default_cache.setter
    def rpms_default_cache(self, s):
        rpm_cache = str(s)
        if rpm_cache[-1] != '/':
            rpm_cache = rpm_cache + '/'
        self._rpms_default_cache = rpm_cache

    @property
    def rpms_allow_cache(self):
        return self._rpms_allow_cache

    @rpms_allow_cache.setter
    def rpms_allow_cache(self, b):
        if not isinstance(b, bool):
            raise TypeError("rpms_allow_cache must be a bool.")
        self._rpms_allow_cache = b

    @property
    def ssl_certificate_file(self):
        return self._ssl_certificate_file

    @ssl_certificate_file.setter
    def ssl_certificate_file(self, s):
        self._ssl_certificate_file = str(s)

    @property
    def ssl_ca_certificate_file(self):
        return self._ssl_ca_certificate_file

    @ssl_ca_certificate_file.setter
    def ssl_ca_certificate_file(self, s):
        self._ssl_ca_certificate_file = str(s)

    @property
    def ssl_certificate_key_file(self):
        return self._ssl_certificate_key_file

    @ssl_certificate_key_file.setter
    def ssl_certificate_key_file(self, s):
        self._ssl_certificate_key_file = str(s)

    @property
    def pkgdb_api_url(self):
        return self._pkgdb_api_url

    @pkgdb_api_url.setter
    def pkgdb_api_url(self, s):
        self._pkgdb_api_url = str(s)

    @property
    def fas_url(self):
        return self._fas_url

    @fas_url.setter
    def fas_url(self, s):
        self._fas_url = str(s)

    @property
    def fas_username(self):
        return self._fas_username

    @fas_username.setter
    def fas_username(self, s):
        self._fas_username = str(s)

    @property
    def fas_password(self):
        return self._fas_password

    @fas_password.setter
    def fas_password(self, s):
        self._fas_password = str(s)

    @property
    def require_packager(self):
        return self._require_packager

    @require_packager.setter
    def require_packager(self, s):
        self._require_packager = bool(s)

    @property
    def log_backend(self):
        return self._log_backend

    @log_backend.setter
    def log_backend(self, s):
        if s == None:
            self._log_backend = "console"
        elif not s in logger.supported_log_backends():
            raise ValueError("Unsupported log backend")

        self._log_backend = str(s)

    @property
    def log_file(self):
        return self._log_file

    @log_file.setter
    def log_file(self, s):
        if s == None:
            self._log_file = ""
        else:
            self._log_file = str(s)

    @property
    def log_level(self):
        return self._log_level

    @log_level.setter
    def log_level(self, s):
        level = str(s).lower()
        self._log_level = logger.str_to_log_level(level)

    @property
    def krb_keytab(self):
        return self._krb_keytab

    @krb_keytab.setter
    def krb_keytab(self, s):
        self._krb_keytab = s

    @property
    def krb_principal(self):
        return self._krb_principal

    @krb_principal.setter
    def krb_principal(self, s):
        self._krb_principal = s

    @property
    def krb_ccache(self):
        return self._krb_ccache

    @krb_ccache.setter
    def krb_ccache(self, s):
        self._krb_ccache = s
