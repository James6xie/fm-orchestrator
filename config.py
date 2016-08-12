from os import path


class BaseConfiguration(object):
    # Make this random (used to generate session keys)
    SECRET_KEY = '74d9e9f9cd40e66fc6c4c2e9987dce48df3ce98542529fd0'
    basedir = path.abspath(path.dirname(__file__))
    SQLALCHEMY_DATABASE_URI = 'sqlite:///{0}'.format(path.join(basedir, 'rida.db'))
    SQLALCHEMY_TRACK_MODIFICATIONS = True
    # Where we should run when running "manage.py runssl" directly.
    HOST = '127.0.0.1'
    PORT = 5000

    SYSTEM = 'koji'
    MESSAGING = 'fedmsg'
    KOJI_CONFIG = '/etc/rida/koji.conf'
    KOJI_PROFILE = 'koji'
    KOJI_ARCHES = ['i686', 'armv7hl', 'x86_64']
    PDC_URL = 'http://modularity.fedorainfracloud.org:8080/rest_api/v1'
    PDC_INSECURE = True
    PDC_DEVELOP = True
    SCMURLS = ["git://pkgs.stg.fedoraproject.org/modules/"]

    # How often should we resort to polling, in seconds
    # Set to zero to disable polling
    POLLING_INTERVAL = 600

    RPMS_DEFAULT_REPOSITORY = 'git://pkgs.fedoraproject.org/rpms/'
    RPMS_ALLOW_REPOSITORY = False
    RPMS_DEFAULT_CACHE = 'http://pkgs.fedoraproject.org/repo/pkgs/'
    RPMS_ALLOW_CACHE = False

    SSL_ENABLED = True
    SSL_CERTIFICATE_FILE = 'server.crt'
    SSL_CERTIFICATE_KEY_FILE = 'server.key'
    SSL_CA_CERTIFICATE_FILE = 'cacert.pem'

    PKGDB_API_URL = 'https://admin.stg.fedoraproject.org/pkgdb/api'

    # Available backends are: console, file, journal.
    LOG_BACKEND = 'journal'

    # Path to log file when LOG_BACKEND is set to "file".
    LOG_FILE = 'rida.log'

    # Available log levels are: debug, info, warn, error.
    LOG_LEVEL = 'info'


class DevConfiguration(BaseConfiguration):
    LOG_BACKEND = 'console'
    HOST = '0.0.0.0'


class ProdConfiguration(BaseConfiguration):
    pass
