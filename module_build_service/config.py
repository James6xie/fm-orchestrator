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

from module_build_service import app
from module_build_service import logger



def from_app_config():
    """ Create the configuration instance from the values in app.config
    """
    conf = Config()
    for key, value in app.config.items():
        # lower keys
        key = key.lower()
        conf.set_item(key, value)
    return conf


class Config(object):
    """Class representing the orchestrator configuration."""
    _defaults = {
        'system': {
            'type': str,
            'default': 'koji',
            'desc': 'The buildsystem to use.'},
        'db': {
            'type': str,
            'default': '',
            'desc': 'RDB URL.'},
        'polling_interval': {
            'type': int,
            'default': 0,
            'desc': 'Polling interval, in seconds.'},
        'pdc_url': {
            'type': str,
            'default': '',
            'desc': 'PDC URL.'},
        'pdc_insecure': {
            'type': bool,
            'default': False,
            'desc': 'Allow insecure connection to PDC.'},
        'pdc_develop': {
            'type': bool,
            'default': False,
            'desc': 'PDC Development mode, basically noauth.'},
        'koji_config': {
            'type': str,
            'default': None,
            'desc': 'Koji config file.'},
        'koji_profile': {
            'type': str,
            'default': None,
            'desc': 'Koji config profile.'},
        'koji_arches': {
            'type': list,
            'default': [],
            'desc': 'Koji architectures.'},
        'koji_proxyuser': {
            'type': bool,
            'default': None,
            'desc': 'Koji proxyuser flag.'},
        'koji_build_priority': {
            'type': int,
            'default': 10,
            'desc': ''},
        'koji_repository_url': {
            'type': str,
            'default': None,
            'desc': 'Koji repository URL.'},
        'rpms_default_repository': {
            'type': str,
            'default': 'git://pkgs.fedoraproject.org/rpms/',
            'desc': 'RPMs default repository URL.'},
        'rpms_allow_repository': {
            'type': bool,
            'default': False,
            'desc': 'Allow custom RPMs repositories.'},
        'rpms_default_cache': {
            'type': str,
            'default': 'http://pkgs.fedoraproject.org/repo/pkgs/',
            'desc': 'RPMs default cache URL.'},
        'rpms_allow_cache': {
            'type': bool,
            'default': False,
            'desc': 'Allow custom RPMs cache.'},
        'ssl_certificate_file': {
            'type': str,
            'default': '',
            'desc': ''},
        'ssl_certificate_key_file': {
            'type': str,
            'default': '',
            'desc': ''},
        'ssl_ca_certificate_file': {
            'type': str,
            'default': '',
            'desc': ''},
        'pkgdb_api_url': {
            'type': str,
            'default': '',
            'desc': ''},
        'fas_url': {
            'type': str,
            'default': '',
            'desc': 'FAS URL'},
        'fas_username': {
            'type': str,
            'default': '',
            'desc': 'FAS username'},
        'fas_password': {
            'type': str,
            'default': '',
            'desc': 'FAS password'},
        'require_packager': {
            'type': bool,
            'default': True,
            'desc': 'Turn on authorization against FAS'},
        'log_backend': {
            'type': str,
            'default': None,
            'desc': 'Log backend'},
        'log_file': {
            'type': str,
            'default': '',
            'desc': 'Path to log file'},
        'log_level': {
            'type': str,
            'default': 0,
            'desc': 'Log level'},
        'krb_keytab': {
            'type': None,
            'default': None,
            'desc': ''},
        'krb_principal': {
            'type': None,
            'default': None,
            'desc': ''},
        'krb_ccache': {
            'type': None,
            'default': '/tmp/krb5cc_module_build_service',
            'desc': ''},
        'messaging': {
            'type': str,
            'default': 'fedmsg',
            'desc': 'The messaging system to use.'},
        'amq_recv_addresses': {
            'type': list,
            'default': [],
            'desc': 'Apache MQ broker url to receive messages.'},
        'amq_dest_address': {
            'type': str,
            'default': '',
            'desc': 'Apache MQ broker address to send messages'},
        'amq_cert_file': {
            'type': str,
            'default': '',
            'desc': 'Certificate for Apache MQ broker auth.'},
        'amq_private_key_file': {
            'type': str,
            'default': '',
            'desc': 'Private key for Apache MQ broker auth.'},
        'amq_trusted_cert_file': {
            'type': str,
            'default': '',
            'desc': 'Trusted certificate for ssl connection.'},
        'mock_config': {
            'type': str,
            'default': 'fedora-25-x86_64',
            'desc': ''},
        'mock_build_srpm_cmd': {
            'type': str,
            'default': 'fedpkg --dist f25 srpm',
            'desc': ''},
        'mock_resultsdir': {
            'type': str,
            'default': '/tmp',
            'desc': 'Directory for Mock build results.'},
        'scmurls': {
            'type': list,
            'default': [],
            'desc': 'Allowed SCM URLs.'},
        'num_consecutive_builds': {
            'type': int,
            'default': 0,
            'desc': 'Number of consecutive component builds.'},
    }

    def __init__(self):
        """Initialize the Config object with defaults."""

        for name, values in self._defaults.items():
            self.set_item(name, values['default'])

    def set_item(self, key, value):
        if key == 'set_item' or key.startswith('_'):
            raise Exception("Configuration item's name is not allowed: %s" % key)

        # managed/registered configuration items
        if key in self._defaults:
            # customized check & set if there's a corresponding handler
            setifok_func = '_setifok_{}'.format(key)
            if hasattr(self, setifok_func):
                getattr(self, setifok_func)(value)
                return

            # type conversion for configuration item
            convert = self._defaults[key]['type']
            if convert in [bool, int, list, str]:
                try:
                    setattr(self, key, convert(value))
                except:
                    raise TypeError("Configuration value conversion failed for name: %s" % key)
            # if type is None, do not perform any conversion
            elif convert is None:
                setattr(self, key, value)
            # unknown type/unsupported conversion
            else:
                raise TypeError("Unsupported type %s for configuration item name: %s" % (convert, key))
        # passthrough for unmanaged configuration items
        else:
            # customized check & set if there's a corresponding handler
            setifok_func = '_setifok_{}'.format(key)
            if hasattr(self, setifok_func):
                getattr(self, setifok_func)(value)
            # otherwise just transparently set value for a key
            else:
                setattr(self, key, value)

        return

    def _setifok_system(self, s):
        s = str(s)
        if s not in ("koji", "copr", "mock"):
            raise ValueError("Unsupported buildsystem: %s." % s)
        self.system = s

    def _setifok_polling_interval(self, i):
        if not isinstance(i, int):
            raise TypeError("polling_interval needs to be an int")
        if i < 0:
            raise ValueError("polling_interval must be >= 0")
        self.polling_interval = i

    def _setifok_rpms_default_repository(self, s):
        rpm_repo = str(s)
        if rpm_repo[-1] != '/':
            rpm_repo = rpm_repo + '/'
        self.rpms_default_repository = rpm_repo

    def _setifok_rpms_default_cache(self, s):
        rpm_cache = str(s)
        if rpm_cache[-1] != '/':
            rpm_cache = rpm_cache + '/'
        self.rpms_default_cache = rpm_cache

    def _setifok_log_backend(self, s):
        if s is None:
            self.log_backend = "console"
        elif s not in logger.supported_log_backends():
            raise ValueError("Unsupported log backend")
        self.log_backend = str(s)

    def _setifok_log_file(self, s):
        if s is None:
            self.log_file = ""
        else:
            self.log_file = str(s)

    def _setifok_log_level(self, s):
        level = str(s).lower()
        self.log_level = logger.str_to_log_level(level)

    def _setifok_messaging(self, s):
        s = str(s)
        if s not in ("fedmsg", "amq"):
            raise ValueError("Unsupported messaging system.")
        self.messaging = s

    def _setifok_amq_recv_addresses(self, l):
        assert isinstance(l, list) or isinstance(l, tuple)
        self.amq_recv_addresses = list(l)

    def _setifok_scmurls(self, l):
        if not isinstance(l, list):
            raise TypeError("scmurls needs to be a list.")
        self.scmurls = [str(x) for x in l]

    def _setifok_num_consecutive_builds(self, i):
        if not isinstance(i, int):
            raise TypeError('NUM_CONSECUTIVE_BUILDS needs to be an int')
        if i < 0:
            raise ValueError('NUM_CONSECUTIVE_BUILDS must be >= 0')
        self.num_consecutive_builds = i
