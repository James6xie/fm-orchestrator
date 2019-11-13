# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
from os import environ, path

confdir = path.abspath(path.dirname(__file__))
dbdir = path.abspath(path.join(confdir, "..")) if confdir.endswith("conf") else confdir


class WebConfiguration(object):
    # Where we should run when running "manage.py run" directly.
    HOST = "0.0.0.0"
    PORT = 5000


class TestConfiguration(WebConfiguration):
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


class ProdConfiguration(WebConfiguration):
    pass


class LocalBuildConfiguration(WebConfiguration):
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
