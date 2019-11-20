# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT

import os
import tempfile

import pytest
from sh import git, pushd
import yaml

import utils


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
    """Clone the git repo to be used by the test

    Find out the name of the test (anything that follow "test_"),
    and get the corresponding git repo configuration from the test
    environment configuration.

    Do a shallow clone of the git repo in a temporary location and
    switch the current working directory into it.

    :param pytest.FixtureRequest request: request object giving access
        to the requesting test context
    :param pytest.fixture test_env: test environment fixture
    :return: repository object the tests can work with
    :rtype: utils.Repo
    """
    with tempfile.TemporaryDirectory() as tempdir:
        testname = request.function.__name__.split("test_", 1)[1]
        repo_conf = test_env["testdata"][testname]
        url = test_env["git_url"] + repo_conf["module"]
        args = [
            "--branch",
            repo_conf["branch"],
            url,
            tempdir,
        ]
        git("clone", *args)
        with pushd(tempdir):
            yield utils.Repo(repo_conf["module"])


@pytest.fixture(scope="session")
def koji(test_env):
    """Koji session for the instance MBS is configured to work with
    """
    return utils.Koji(**test_env["koji"])
