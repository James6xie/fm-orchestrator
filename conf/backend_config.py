# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
from os import environ, path

confdir = path.abspath(path.dirname(__file__))
dbdir = path.abspath(path.join(confdir, "..")) if confdir.endswith("conf") else confdir


class BackendConfiguration(object):
    # How often should we resort to polling, in seconds
    # Set to zero to disable polling
    POLLING_INTERVAL = 600

    # Configs for running tasks asynchronously with Celery
    # For details of Celery configs, refer to Celery documentation:
    # https://docs.celeryproject.org/en/latest/userguide/configuration.html
    #
    # Each config name consists of namespace CELERY_ and the new Celery config
    # name converted to upper case. For example the broker url, Celery config
    # name is broker_url, then as you can see below, the corresponding config
    # name in MBS is CELERY_BROKER_URL.
    CELERY_BROKER_URL = ""
    CELERY_RESULT_BACKEND = ""
    CELERY_IMPORTS = []


class TestConfiguration(BackendConfiguration):
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

    # Greenwave configuration
    GREENWAVE_URL = "https://greenwave.example.local/api/v1.0/"
    GREENWAVE_DECISION_CONTEXT = "test_dec_context"
    GREENWAVE_SUBJECT_TYPE = "some-module"

    STREAM_SUFFIXES = {r"^el\d+\.\d+\.\d+\.z$": 0.1}


class ProdConfiguration(BackendConfiguration):
    pass


class LocalBuildConfiguration(BackendConfiguration):
    CACHE_DIR = "~/modulebuild/cache"
    LOG_LEVEL = "debug"
    MESSAGING = "in_memory"

    RESOLVER = "mbs"
    RPMS_ALLOW_REPOSITORY = True
    MODULES_ALLOW_REPOSITORY = True


class OfflineLocalBuildConfiguration(LocalBuildConfiguration):
    RESOLVER = "local"


class DevConfiguration(LocalBuildConfiguration):
    DEBUG = True
    CELERY_BROKER_URL = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND = "redis://localhost:6379/0"
