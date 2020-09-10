import json
import os
import psutil
import pytest
import requests
import time

from subprocess import Popen
from tests import read_staged_data_as_yaml


base_dir = os.path.dirname(__file__)
yaml = read_staged_data_as_yaml("testmodule.yaml")

LOCAL_MBS_URL = "http://localhost:5000/module-build-service/1/module-builds/"


def submit_yaml_build(module_name):
    """Submit module build with custom name to get a unique NVR each time."""
    yaml["data"]["name"] = module_name
    data = {"modulemd": str(yaml), "module_name": "testmodule"}
    r = requests.post(LOCAL_MBS_URL, data=json.dumps(data))
    if r.status_code > 300:
        pytest.fail(str(r.json()))
    return r.json()["id"]


def wait_for_module_build(build_id, timeout=60, interval=5):
    """Wait for module build to be ready

    :param int build_id: build definition (either id or Build object)
    :param float timeout: timeout in seconds
    :param float interval: scan interval in seconds
    """
    start = time.time()

    while (time.time() - start) < timeout:
        state = requests.get(LOCAL_MBS_URL + str(build_id)).json()["state_name"]
        if state == "ready":
            return
        time.sleep(interval)
    pytest.skip("Wait for build timed out after {}s".format(timeout))


@pytest.fixture()
def run_debug_mbs_instance():
    """Starts a 'debug' MBS instance:
    * mbs-frontend (no auth, yaml import enabled)
    * moksha hub (in memory messaging)
    * tests.test_build.test_build.FakeModuleBuilder as builder backend (always succeeds)

    Optionally:
    Set MBS_TEST_INSTANCE_PID env variable to run test against your own running instance.
    If you intend to run a standalone instance, make sure you have these env vars set:
    * MODULE_BUILD_SERVICE_DEVELOPER_ENV=0
    * MBS_CONFIG_SECTION=TestConfiguration
    * MBS_CONFIG_FILE=tests/test_memory/mbs_configuration.py
    * DATABASE_URI=postgresql+psycopg2://postgres:@127.0.0.1/mbstest

    ...then 'python tests/test_memory/mbs_debug.py' (and 'kill -10 <PID>' to start debugger)
    """

    process = None
    try:
        running_instance_pid = int(os.environ.get("MBS_TEST_INSTANCE_PID"))
        yield running_instance_pid
    except TypeError or ValueError:
        mbs_config_file_path = os.path.join(base_dir, "mbs_configuration.py")
        env = {
            "MBS_CONFIG_SECTION": "TestConfiguration",
            "MBS_CONFIG_FILE": mbs_config_file_path,
        }
        # Pass the preset database configuration (if present)
        if os.environ.get("DATABASE_URI"):
            env["DATABASE_URI"] = os.environ.get("DATABASE_URI")

        mbs_exec_script = os.path.join(base_dir, "mbs_debug.py")
        process = Popen(["python", mbs_exec_script], stdin=None, stdout=None, env=env)
        time.sleep(5)  # wait a couple of secs for MBS to start
        yield process.pid
    if process:
        process.terminate()


@pytest.mark.parametrize("num_builds", [20])
def test_submit_build(require_platform_and_default_arch, run_debug_mbs_instance, num_builds):
    pid = run_debug_mbs_instance
    process = psutil.Process(pid)

    def get_rss():  # resident set size in MB
        return process.memory_info().rss / 1000000
    consumed_memory = []

    for i in range(num_builds):
        build_id = submit_yaml_build("test-module-{}".format(i))
        # wait for the build to finish, so that the build logger is flushed/closed
        wait_for_module_build(build_id, interval=0.5, timeout=10)
        consumed_memory.append(get_rss())

    print("Memory [MB]: {}".format(consumed_memory))

    if (consumed_memory[-1] - consumed_memory[0]) > 0.1:
        pytest.fail("Memory is leaking, [MB]: {}".format(consumed_memory))
