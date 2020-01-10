# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT

import utils


def test_no_components(test_env, repo, koji):
    """
    Submit the testmodule build with `fedpkg module-build`

    Checks:
    * Verify that no components were built when no components are defined in modulemd
    * Verify that the testmodule build succeeds

    """
    build = utils.Build(test_env["packaging_utility"], test_env["mbs_api"])
    repo.bump()
    build.run(reuse=test_env["testdata"]["no_components"].get("build_id"))
    build.watch()

    assert build.state_name == "ready"
    assert not build.data["component_builds"]
