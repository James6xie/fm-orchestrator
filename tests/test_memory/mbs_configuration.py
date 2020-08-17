import os


class TestConfiguration:
    # TEST CONFIGURATION ('borrowed' from module_build_service.common.conf)
    SECRET_KEY = os.urandom(16)
    SQLALCHEMY_TRACK_MODIFICATIONS = True
    HOST = "0.0.0.0"
    PORT = 5000

    LOG_LEVEL = "debug"
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URI", "sqlite:///:memory:")
    DEBUG = True
    MESSAGING = "in_memory"
    PDC_URL = "https://pdc.fedoraproject.org/rest_api/v1"
    NET_TIMEOUT = 10
    NET_RETRY_INTERVAL = 1
    SCM_NET_TIMEOUT = 0.1
    SCM_NET_RETRY_INTERVAL = 0.1
    KOJI_CONFIG = "./conf/koji.conf"
    KOJI_PROFILE = "staging"
    KOJI_REPOSITORY_URL = "https://kojipkgs.stg.fedoraproject.org/repos"
    SCMURLS = ["https://src.stg.fedoraproject.org/modules/"]
    ALLOWED_GROUPS_TO_IMPORT_MODULE = {"mbs-import-module"}
    GREENWAVE_URL = "https://greenwave.example.local/api/v1.0/"
    GREENWAVE_DECISION_CONTEXT = "test_dec_context"
    GREENWAVE_SUBJECT_TYPE = "some-module"
    STREAM_SUFFIXES = {r"^el\d+\.\d+\.\d+\.z$": 0.1}
    CELERY_TASK_ALWAYS_EAGER = True

    NO_AUTH = True
    YAML_SUBMIT_ALLOWED = True
