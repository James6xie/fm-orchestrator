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


class TestConfiguration(BaseConfiguration):
    LOG_LEVEL = "debug"
    SQLALCHEMY_DATABASE_URI = environ.get(
        "DATABASE_URI", "sqlite:///{0}".format(path.join(dbdir, "mbstest.db")))
    DEBUG = True
    MESSAGING = "in_memory"

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

    # Celery tasks will be executed locally for local builds
    CELERY_TASK_ALWAYS_EAGER = True


class OfflineLocalBuildConfiguration(LocalBuildConfiguration):
    RESOLVER = "local"


class DevConfiguration(LocalBuildConfiguration):
    DEBUG = True
