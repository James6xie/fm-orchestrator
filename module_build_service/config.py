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
#            Filip Valder <fvalder@redhat.com>

import imp
import os

from os import sys

from module_build_service import logger

try:
    conf_module = 'mbs_runtime_config'
    mbs_runtime_config = imp.load_source(conf_module,
                                         '/etc/module-build-service/config.py')
except:
    conf_module = 'conf.config'


def init_config(app):
    _init_app_config(app)
    return Config(app)


def _init_app_config(app):
    """ Configure app
    """
    app.config.from_envvar("MBS_SETTINGS", silent=True)
    here = sys.path[0]
    if any(['nosetests' in arg or 'noserunner.py' in arg for arg in sys.argv]):
        app.config.from_object('%s.TestConfiguration' % conf_module)
    elif 'MODULE_BUILD_SERVICE_DEVELOPER_ENV' in os.environ and \
         os.environ['MODULE_BUILD_SERVICE_DEVELOPER_ENV'].lower() in (
            '1', 'on', 'true', 'y', 'yes'):
        app.config.from_object('%s.DevConfiguration' % conf_module)
    elif here not in ('/usr/bin', '/bin', '/usr/local/bin'):
        app.config.from_object('%s.DevConfiguration' % conf_module)
    else:
        app.config.from_object('%s.ProdConfiguration' % conf_module)


class Config(object):
    """Class representing the orchestrator configuration."""
    _defaults = {
        'debug': {
            'type': bool,
            'default': False,
            'desc': 'Debug mode'},
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
        'koji_build_macros_target': {
            'type': str,
            'default': '',
            'desc': 'Target to build "module-build-macros" RPM in.'
            },
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
        'messaging_topic_prefix': {
            'type': list,
            'default': 'org.fedoraproject.prod',
            'desc': 'The messaging system topic prefixes which we are interested in.'},
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
        'net_timeout': {
            'type': int,
            'default': 120,
            'desc': 'Global network timeout for read/write operations, in seconds.'},
        'net_retry_interval': {
            'type': int,
            'default': 30,
            'desc': 'Global network retry interval for read/write operations, in seconds.'},
    }

    def __init__(self, app=None):
        """
        Initialize the Config object with defaults.

        If Flask app is given, override/enrich the configuration defaults
        with Flask config values/items.
        """

        # set defaults
        for name, values in self._defaults.items():
            self.set_item(name, values['default'])

        # we don't check whether app is Flask instance, we simply assume it
        # so there's no need of import flask
        if app is not None:
            # override defaults
            for key, value in app.config.items():
                # lower keys
                key = key.lower()
                self.set_item(key, value)

    def set_item(self, key, value):
        """Set value for configuration item as self.key = value"""
        if key == 'set_item' or key.startswith('_'):
            raise Exception("Configuration item's name is not allowed: %s" % key)

        # customized check & set if there's a corresponding handler
        setifok_func = '_setifok_{}'.format(key)
        if hasattr(self, setifok_func):
            getattr(self, setifok_func)(value)
            return

        # managed/registered configuration items
        if key in self._defaults:
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
            setattr(self, key, value)

        return

    #
    # Register your _setifok_* handlers here
    #

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
        if s not in ("fedmsg", "amq", "in_memory"):
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
