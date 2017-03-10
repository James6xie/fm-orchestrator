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


def init_config(app):
    """ Configure MBS and the Flask app
    """
    config_module = None
    config_file = '/etc/module-build-service/config.py'
    config_section = 'DevConfiguration'

    # automagically detect production environment:
    #   - existing and readable config_file presets ProdConfiguration
    try:
        with open(config_file):
            config_section = 'ProdConfiguration'
    except:
        pass
    #   - Flask app within mod_wsgi presets ProdConfiguration
    flask_app_env = hasattr(app, 'request') and hasattr(app.request, 'environ')
    if flask_app_env and any([var.startswith('mod_wsgi.')
                              for var in app.request.environ]):
        config_section = 'ProdConfiguration'
    # try getting config_file from os.environ
    if 'MBS_CONFIG_FILE' in os.environ:
        config_file = os.environ['MBS_CONFIG_FILE']
    # try getting config_section from os.environ
    if 'MBS_CONFIG_SECTION' in os.environ:
        config_section = os.environ['MBS_CONFIG_SECTION']
    # preferably get these values from Flask app
    if flask_app_env:
        # try getting config_file from Flask app
        if 'MBS_CONFIG_FILE' in app.request.environ:
            config_file = app.request.environ['MBS_CONFIG_FILE']
        # try getting config_section from Flask app
        if 'MBS_CONFIG_SECTION' in app.request.environ:
            config_section = app.request.environ['MBS_CONFIG_SECTION']
    # TestConfiguration shall only be used for running tests, otherwise...
    if any(['nosetests' in arg or 'noserunner.py' in arg for arg in sys.argv]):
        config_section = 'TestConfiguration'
        from conf import config
        config_module = config
    # ...MODULE_BUILD_SERVICE_DEVELOPER_ENV has always the last word
    # and overrides anything previously set before!
    # Again, check Flask app (preferably) or fallback to os.environ.
    # In any of the following cases, use configuration directly from MBS package
    # -> /conf/config.py.
    elif (flask_app_env and
          'MODULE_BUILD_SERVICE_DEVELOPER_ENV' in app.request.environ):
        if app.request.environ['MODULE_BUILD_SERVICE_DEVELOPER_ENV'].lower() in (
                '1', 'on', 'true', 'y', 'yes'):
            config_section = 'DevConfiguration'
            from conf import config
            config_module = config
    elif ('MODULE_BUILD_SERVICE_DEVELOPER_ENV' in os.environ and
          os.environ['MODULE_BUILD_SERVICE_DEVELOPER_ENV'].lower() in (
            '1', 'on', 'true', 'y', 'yes')):
        config_section = 'DevConfiguration'
        from conf import config
        config_module = config
    # try loading configuration from file
    if not config_module:
        try:
            config_module = imp.load_source('mbs_runtime_config',
                                            config_file)
        except:
            raise SystemError("Configuration file {} was not found."
                              .format(config_file))

    # finally configure MBS and the Flask app
    config_section_obj = getattr(config_module, config_section)
    conf = Config(config_section_obj)
    app.config.from_object(config_section_obj)
    return conf


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
        'default_dist_tag_prefix': {
            'type': str,
            'default': 'module_',
            'desc': 'Default dist-tag prefix for built modules.'},
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
            'desc': 'Target to build "module-build-macros" RPM in.'},
        'koji_tag_prefixes': {
            'type': list,
            'default': ['module'],
            'desc': 'List of allowed koji tag prefixes.'},
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
        'modules_default_repository': {
            'type': str,
            'default': 'git://pkgs.fedoraproject.org/modules/',
            'desc': 'Included modules default repository URL.'},
        'modules_allow_repository': {
            'type': bool,
            'default': False,
            'desc': 'Allow custom included modules repositories.'},
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
        'allowed_groups': {
            'type': set,
            'default': set(['packager']),
            'desc': 'The set of groups allowed to submit builds.'},
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
            'default': ['org.fedoraproject.prod'],
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
            'desc': 'Allowed SCM URLs for submitted module.'},
        'yaml_submit_allowed': {
            'type': bool,
            'default': False,
            'desc': 'Is it allowed to directly submit modulemd yaml file?'},
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
        'no_auth': {
            'type': bool,
            'default': False,
            'desc': 'Disable client authentication.'},
    }

    def __init__(self, conf_section_obj):
        """
        Initialize the Config object with defaults and then override them
        with runtime values.
        """

        # set defaults
        for name, values in self._defaults.items():
            self.set_item(name, values['default'])

        # override defaults
        for key in dir(conf_section_obj):
            # skip keys starting with underscore
            if key.startswith('_'):
                continue
            # set item (lower key)
            self.set_item(key.lower(), getattr(conf_section_obj, key))

    def set_item(self, key, value):
        """
        Set value for configuration item. Creates the self._key = value
        attribute and self.key property to set/get/del the attribute.
        """
        if key == 'set_item' or key.startswith('_'):
            raise Exception("Configuration item's name is not allowed: %s" % key)

        # Create the empty self._key attribute, so we can assign to it.
        setattr(self, "_" + key, None)

        # Create self.key property to access the self._key attribute.
        # Use the setifok_func if available for the attribute.
        setifok_func = '_setifok_{}'.format(key)
        if hasattr(self, setifok_func):
            setx = lambda self, val: getattr(self, setifok_func)(val)
        else:
            setx = lambda self, val: setattr(self, "_" + key, val)
        getx = lambda self: getattr(self, "_" + key)
        delx = lambda self: delattr(self, "_" + key)
        setattr(Config, key, property(getx, setx, delx))

        # managed/registered configuration items
        if key in self._defaults:
            # type conversion for configuration item
            convert = self._defaults[key]['type']
            if convert in [bool, int, list, str, set]:
                try:
                    # Do no try to convert None...
                    if value is not None:
                        value = convert(value)
                except:
                    raise TypeError("Configuration value conversion failed for name: %s" % key)
            # unknown type/unsupported conversion
            elif convert is not None:
                raise TypeError("Unsupported type %s for configuration item name: %s" % (convert, key))

        # Set the attribute to the correct value
        setattr(self, key, value)

    #
    # Register your _setifok_* handlers here
    #

    def _setifok_system(self, s):
        s = str(s)
        if s not in ("koji", "copr", "mock"):
            raise ValueError("Unsupported buildsystem: %s." % s)
        self._system = s

    def _setifok_polling_interval(self, i):
        if not isinstance(i, int):
            raise TypeError("polling_interval needs to be an int")
        if i < 0:
            raise ValueError("polling_interval must be >= 0")
        self._polling_interval = i

    def _setifok_rpms_default_repository(self, s):
        rpm_repo = str(s)
        if rpm_repo[-1] != '/':
            rpm_repo = rpm_repo + '/'
        self._rpms_default_repository = rpm_repo

    def _setifok_rpms_default_cache(self, s):
        rpm_cache = str(s)
        if rpm_cache[-1] != '/':
            rpm_cache = rpm_cache + '/'
        self._rpms_default_cache = rpm_cache

    def _setifok_log_backend(self, s):
        if s is None:
            self._log_backend = "console"
        elif s not in logger.supported_log_backends():
            raise ValueError("Unsupported log backend")
        self._log_backend = str(s)

    def _setifok_log_file(self, s):
        if s is None:
            self._log_file = ""
        else:
            self._log_file = str(s)

    def _setifok_log_level(self, s):
        level = str(s).lower()
        self._log_level = logger.str_to_log_level(level)

    def _setifok_messaging(self, s):
        s = str(s)
        if s not in ("fedmsg", "amq", "in_memory"):
            raise ValueError("Unsupported messaging system.")
        self._messaging = s

    def _setifok_amq_recv_addresses(self, l):
        assert isinstance(l, list) or isinstance(l, tuple)
        self._amq_recv_addresses = list(l)

    def _setifok_scmurls(self, l):
        if not isinstance(l, list):
            raise TypeError("scmurls needs to be a list.")
        self._scmurls = [str(x) for x in l]

    def _setifok_num_consecutive_builds(self, i):
        if not isinstance(i, int):
            raise TypeError('NUM_CONSECUTIVE_BUILDS needs to be an int')
        if i < 0:
            raise ValueError('NUM_CONSECUTIVE_BUILDS must be >= 0')
        self._num_consecutive_builds = i
