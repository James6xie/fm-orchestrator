# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT

import os

import yaml
import pytest

from utils import MBS, Git, Koji


def load_test_env():
    """Load test environment configuration

    :return: Test environment configuration.
    :rtype:  dict
    """
    config_file = os.getenv("MBS_TEST_CONFIG", "test.env.yaml")
    with open(config_file) as f:
        env = yaml.safe_load(f)
    return env


test_env = load_test_env()


@pytest.fixture(scope="session")
def mbs():
    return MBS(test_env["mbs_api"])


@pytest.fixture(scope="session")
def git():
    return Git(test_env["git_url"])


@pytest.fixture(scope="session")
def koji():
    return Koji(**test_env["koji"])
