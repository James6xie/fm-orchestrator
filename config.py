from os import path


class BaseConfiguration(object):
    # Make this random (used to generate session keys)
    SECRET_KEY = '74d9e9f9cd40e66fc6c4c2e9987dce48df3ce98542529fd0'
    basedir = path.abspath(path.dirname(__file__))
    SQLALCHEMY_DATABASE_URI = 'sqlite:///{0}'.format(path.join(
        basedir, 'module_build_service.db'))
    SQLALCHEMY_TRACK_MODIFICATIONS = True
    # Where we should run when running "manage.py runssl" directly.
    HOST = '127.0.0.1'
    PORT = 5000

    SYSTEM = 'koji'
    MESSAGING = 'fedmsg' # or amq
    KOJI_CONFIG = '/etc/module_build_service/koji.conf'
    KOJI_PROFILE = 'koji'
    KOJI_ARCHES = ['i686', 'armv7hl', 'x86_64']
    KOJI_PROXYUSER = True
    COPR_CONFIG = '/etc/rida/copr.conf'
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

    FAS_URL = 'https://admin.stg.fedoraproject.org/accounts'
    REQUIRE_PACKAGER = True

    # Available backends are: console, file, journal.
    LOG_BACKEND = 'journal'

    # Path to log file when LOG_BACKEND is set to "file".
    LOG_FILE = 'module_build_service.log'

    # Available log levels are: debug, info, warn, error.
    LOG_LEVEL = 'info'

    # Settings for Kerberos
    KRB_KEYTAB = None
    KRB_PRINCIPAL = None
    KRB_CCACHE = None

    # AMQ prefixed variables are required only while using 'amq' as messaging backend
    # Addresses to listen to
    AMQ_RECV_ADDRESSES = ['amqps://messaging.mydomain.com/Consumer.m8y.VirtualTopic.eng.koji',
            'amqps://messaging.mydomain.com/Consumer.m8y.VirtualTopic.eng.module_build_service',]
    # Address for sending messages
    AMQ_DEST_ADDRESS = 'amqps://messaging.mydomain.com/Consumer.m8y.VirtualTopic.eng.module_build_service'
    AMQ_CERT_FILE = '/etc/module_build_service/msg-m8y-client.crt'
    AMQ_PRIVATE_KEY_FILE = '/etc/module_build_service/msg-m8y-client.key'
    AMQ_TRUSTED_CERT_FILE = '/etc/module_build_service/Root-CA.crt'

class DevConfiguration(BaseConfiguration):
    LOG_BACKEND = 'console'
    LOG_LEVEL = 'debug'
    HOST = '0.0.0.0'


    if path.exists('/home/fedora/modularity.keytab'):
        KRB_PRINCIPAL = 'modularity@STG.FEDORAPROJECT.ORG'
        KRB_KEYTAB = '/home/fedora/modularity.keytab'
        KRB_CCACHE = '/var/tmp/krb5cc'
    else:
        # This requires that your principal be listed server side in
        # ProxyPrincipals, and that is only true for our modularity system
        # user.  See:   https://infrastructure.fedoraproject.org/cgit/ansible.git/commit/?id=a28a93dad75248c30c1792ec35f588c8e317c067
        KOJI_PROXYUSER = False

    REQUIRE_PACKAGER = False
    # You only need these FAS options if you turn on authorization
    # with REQUIRE_PACKAGER=True
    #FAS_USERNAME = 'put your fas username here'
    #FAS_PASSWORD = 'put your fas password here....'
    #FAS_PASSWORD = os.environ('FAS_PASSWORD') # you could store it here
    #FAS_PASSWORD = commands.getoutput('pass your_fas_password').strip()

    KOJI_ARCHES = ['x86_64']

class TestConfiguration(BaseConfiguration):
    LOG_BACKEND = 'console'
    LOG_LEVEL = 'debug'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    DEBUG = True


class ProdConfiguration(BaseConfiguration):
    FAS_USERNAME = 'TODO'
    #FAS_PASSWORD = 'another password'
