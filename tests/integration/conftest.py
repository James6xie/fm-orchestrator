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


@pytest.fixture(scope="session")
def pkg_util(test_env):
    """Fixture to interact with the packaging utility

    :return: Packaging utility configured for the tests
    :rtype: object of utils.PackagingUtility
    """
    return utils.PackagingUtility(test_env["packaging_utility"], test_env["mbs_api"])


@pytest.fixture(scope="function")
def scenario(request, test_env):
    """Configuration data for the scenario

    Find out the name of the scenario (anything that follows "test_"),
    and return the corresponding configuration.

    This is a convenience fixture to serve as a shortcut to access
    scenario configuration.
    """
    scenario_name = request.function.__name__.split("test_", 1)[1]
    scenario = test_env["testdata"].get(scenario_name)
    if not scenario:
        pytest.skip("No test scenario in 'test.env' for: {}".format(request.function.__name__))
    return scenario


@pytest.fixture(scope="function")
def repo(scenario, test_env):
    """Clone the module repo to be used by the scenario

    1) Get the module repo from the scenario configuration.
    2) Clone the repo in a temporary location and switch the current working directory into it.

    :param pytest.fixture scenario: test scenario fixture
    :param pytest.fixture test_env: test environment fixture
    :return: repository object the tests can work with
    :rtype: utils.Repo
    """
    module = scenario["module"]
    branch = scenario["branch"]
    with tempfile.TemporaryDirectory() as tempdir:
        pkg_util = utils.PackagingUtility(test_env["packaging_utility"], None)  # no need for MBS
        pkg_util.clone("--branch", branch, f"modules/{module}", tempdir)
        with pushd(tempdir):
            yield utils.Repo(module, branch)


@pytest.fixture(scope="session")
def koji(test_env):
    """Koji session for the instance MBS is configured to work with."""
    return utils.Koji(**test_env["koji"])


@pytest.fixture(scope="session")
def mbs(test_env):
    """MBS instance session."""
    return utils.MBS(test_env["mbs_api"])


@pytest.fixture(scope="function")
def clone_and_start_build(repo, pkg_util):
    """Shortcut for tests that need a running build/s. Auto clean-up.

    :return: repo and list of submitted builds
    :rtype utils.Repo, list:
    """
    repo.bump()
    builds = pkg_util.run("--optional", "rebuild_strategy=all")
    yield repo, builds
    for build in builds:
        try:
            pkg_util.cancel(build)
        except sh.ErrorReturnCode:
            pass  # we don't need to bother with clean-up errors


@pytest.fixture(scope="function")
def require_koji_resolver(repo, scenario, test_env, mbs):
    """Check that koji resolver is present."""
    stream = repo.modulemd['data']['dependencies'][0]['buildrequires']['platform']
    platform_build = mbs.get_module_builds(name="platform", stream=stream)[0]
    resolver = platform_build.get_modulemd()['data']['xmd']['mbs']\
        .get('koji_tag_with_modules')
    if not resolver:
        pytest.skip('koji resolver is not configured.')
