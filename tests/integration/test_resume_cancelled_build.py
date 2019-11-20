# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT

import utils
import time


def test_resume_cancelled_build(test_env, repo, koji):
    """
    Run the  build with "rebuild_strategy=all".
    Wait until the module-build-macros build is submitted to Koji.
    Cancel module build.
    Resume the module with "rhpkg-stage module-build -w".

    Check that:
      * Check that the testmodule had actually been cancelled
      * Check that the testmodule build succeeded

    """
    build = utils.Build(test_env["packaging_utility"], test_env["mbs_api"])
    repo.bump()
    build.run(
        "--optional",
        "rebuild_strategy=all",
    )
    build.wait_for_koji_task_id(package="module-build-macros", batch=1)
    build.cancel()
    # Behave like a human: restarting the build too quickly would lead to an error.
    time.sleep(10)
    build.run("--watch")

    assert build.state_name == "ready"
    assert build.was_cancelled()
