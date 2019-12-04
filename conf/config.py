# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
from os import environ, path

# FIXME: workaround for this moment till confdir, dbdir (installdir etc.) are
# declared properly somewhere/somehow
confdir = path.abspath(path.dirname(__file__))
# use parent dir as dbdir else fallback to current dir
dbdir = path.abspath(path.join(confdir, "..")) if confdir.endswith("conf") else confdir


class BaseConfiguration(object):
    DEBUG = False
    # Make this random (used to generate session keys)
    SECRET_KEY = "74d9e9f9cd40e66fc6c4c2e9987dce48df3ce98542529fd0"
    SQLALCHEMY_DATABASE_URI = "sqlite:///{0}".format(path.join(dbdir, "module_build_service.db"))
    SQLALCHEMY_TRACK_MODIFICATIONS = True
    # Where we should run when running "manage.py run" directly.
    HOST = "0.0.0.0"
    PORT = 5000

    MESSAGING_TOPIC_PREFIX = ["org.fedoraproject.prod"]
    KOJI_CONFIG = "/etc/module-build-service/koji.conf"
    KOJI_PROFILE = "koji"
    ARCHES = ["i686", "armv7hl", "x86_64"]
    KOJI_REPOSITORY_URL = "https://kojipkgs.fedoraproject.org/repos"
    PDC_URL = "https://pdc.fedoraproject.org/rest_api/v1"
    PDC_INSECURE = False
    PDC_DEVELOP = True
    SCMURLS = ["https://src.fedoraproject.org/modules/"]

    # How often should we resort to polling, in seconds
    # Set to zero to disable polling
    POLLING_INTERVAL = 600

    # Determines how many builds that can be submitted to the builder
    # and be in the build state at a time. Set this to 0 for no restrictions
    NUM_CONCURRENT_BUILDS = 5

    RPMS_DEFAULT_REPOSITORY = "https://src.fedoraproject.org/rpms/"
    RPMS_DEFAULT_CACHE = "http://pkgs.fedoraproject.org/repo/pkgs/"

    MODULES_DEFAULT_REPOSITORY = "https://src.fedoraproject.org/modules/"

    # Path to log file when LOG_BACKEND is set to "file".
    LOG_FILE = "module_build_service.log"

    # Available log levels are: debug, info, warn, error.
    LOG_LEVEL = "info"

    # Settings for Kerberos
    KRB_KEYTAB = None
    KRB_PRINCIPAL = None

    # AMQ prefixed variables are required only while using 'amq' as messaging backend
    # Addresses to listen to
    AMQ_RECV_ADDRESSES = [
        "amqps://messaging.mydomain.com/Consumer.m8y.VirtualTopic.eng.koji",
        "amqps://messaging.mydomain.com/Consumer.m8y.VirtualTopic.eng.module_build_service",
    ]
    # Address for sending messages
    AMQ_DEST_ADDRESS = \
        "amqps://messaging.mydomain.com/Consumer.m8y.VirtualTopic.eng.module_build_service"
    AMQ_CERT_FILE = "/etc/module_build_service/msg-m8y-client.crt"
    AMQ_PRIVATE_KEY_FILE = "/etc/module_build_service/msg-m8y-client.key"
    AMQ_TRUSTED_CERT_FILE = "/etc/module_build_service/Root-CA.crt"

    # Configs for running tasks asynchronously with Celery
    # For details of Celery configs, refer to Celery documentation:
    # https://docs.celeryproject.org/en/latest/userguide/configuration.html
    #
    # Each config name consists of namespace CELERY_ and the new Celery config
    # name converted to upper case. For example the broker url, Celery config
    # name is broker_url, then as you can below, the corresponding config name
    # in MBS is CELERY_BROKER_URL.
    CELERY_BROKER_URL = ""
    CELERY_RESULT_BACKEND = ""
    CELERY_IMPORTS = [
        "module_build_service.scheduler.handlers.components",
        "module_build_service.scheduler.handlers.modules",
        "module_build_service.scheduler.handlers.repos",
        "module_build_service.scheduler.handlers.tags",
        "module_build_service.scheduler.handlers.greenwave",
    ]


class TestConfiguration(BaseConfiguration):
    LOG_LEVEL = "debug"
    SQLALCHEMY_DATABASE_URI = environ.get(
        "DATABASE_URI", "sqlite:///{0}".format(path.join(dbdir, "mbstest.db")))
    DEBUG = True
    MESSAGING = "in_memory"
    PDC_URL = "https://pdc.fedoraproject.org/rest_api/v1"

    # Global network-related values, in seconds
    NET_TIMEOUT = 3
    NET_RETRY_INTERVAL = 1
    # SCM network-related values, in seconds
    SCM_NET_TIMEOUT = 0.1
    SCM_NET_RETRY_INTERVAL = 0.1

    KOJI_CONFIG = "./conf/koji.conf"
    KOJI_PROFILE = "staging"
    SERVER_NAME = "localhost"

    KOJI_REPOSITORY_URL = "https://kojipkgs.stg.fedoraproject.org/repos"
    SCMURLS = ["https://src.stg.fedoraproject.org/modules/"]

    ALLOWED_GROUPS_TO_IMPORT_MODULE = {"mbs-import-module"}

    # Greenwave configuration
    GREENWAVE_URL = "https://greenwave.example.local/api/v1.0/"
    GREENWAVE_DECISION_CONTEXT = "test_dec_context"
    GREENWAVE_SUBJECT_TYPE = "some-module"

    STREAM_SUFFIXES = {r"^el\d+\.\d+\.\d+\.z$": 0.1}

    # Ensures task.delay executes locally instead of scheduling a task to a queue.
    CELERY_TASK_ALWAYS_EAGER = True


class ProdConfiguration(BaseConfiguration):
    pass


class LocalBuildConfiguration(BaseConfiguration):
    CACHE_DIR = "~/modulebuild/cache"
    LOG_LEVEL = "debug"
    MESSAGING = "in_memory"

    ALLOW_CUSTOM_SCMURLS = True
    RESOLVER = "mbs"
    RPMS_ALLOW_REPOSITORY = True
    MODULES_ALLOW_REPOSITORY = True


class OfflineLocalBuildConfiguration(LocalBuildConfiguration):
    RESOLVER = "local"


class DevConfiguration(LocalBuildConfiguration):
    DEBUG = True

    CELERY_BROKER_URL = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND = "redis://localhost:6379/0"
