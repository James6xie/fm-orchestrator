# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT

import os
import sys
import tempfile

import pytest
import sh
import yaml

import utils

our_sh = sh(_out=sys.stdout, _err=sys.stderr, _tee=True)
from our_sh import pushd, Command  # noqa


@pytest.fixture(scope="session")
def test_env():
    """Load test environment configuration

    :return: Test environment configuration.
    :rtype:  dict
    """
    config_file = os.getenv("MBS_TEST_CONFIG", "test.env.yaml")
    with open(config_file) as f:
        env = yaml.safe_load(f)
    return env


@pytest.fixture(scope="function")
def repo(request, test_env):
    """Clone the module repo to be used by the test

    Find out the name of the test (anything that follow "test_"), and get
    the corresponding module repo from the test environment configuration.

    Clone the repo in a temporary location and switch the current working
    directory into it.

    :param pytest.FixtureRequest request: request object giving access
        to the requesting test context
    :param pytest.fixture test_env: test environment fixture
    :return: repository object the tests can work with
    :rtype: utils.Repo
    """
    with tempfile.TemporaryDirectory() as tempdir:
        testname = request.function.__name__.split("test_", 1)[1]
        repo_conf = test_env["testdata"][testname]
        packaging_util = Command(test_env["packaging_utility"]).bake(
            _out=sys.stdout, _err=sys.stderr, _tee=True
        )
        args = [
            "--branch",
            repo_conf["branch"],
            f"modules/{repo_conf['module']}",
            tempdir,
        ]
        packaging_util("clone", *args)
        with pushd(tempdir):
            yield utils.Repo(repo_conf["module"])


@pytest.fixture(scope="session")
def koji(test_env):
    """Koji session for the instance MBS is configured to work with
    """
    return utils.Koji(**test_env["koji"])
