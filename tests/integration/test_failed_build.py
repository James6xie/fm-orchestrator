# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT

import utils


def test_failed_build(test_env, repo, koji):
    """
    Run the build with "rebuild_strategy=all".

    Check that:
      * Check that the module build eventually fails
      * Check that any other components in the same batch as the failed component are
        cancelled, if not completed.
    """
    build = utils.Build(test_env["packaging_utility"], test_env["mbs_api"])
    repo.bump()
    build.run(
        "--watch",
        "--scratch",
        "--optional",
        "rebuild_strategy=all",
        reuse=test_env["testdata"]["failed_build"].get("build_id"),
    )

    assert build.state_name == "failed"
    batch = test_env["testdata"]["failed_build"]["batch"]
    failing_components = test_env["testdata"]["failed_build"]["failing_components"]
    canceled_components = test_env["testdata"]["failed_build"]["canceled_components"]
    assert sorted(failing_components) == sorted(build.component_names(state="FAILED", batch=batch))
    assert sorted(canceled_components) == sorted(
        build.component_names(state="COMPLETE", batch=batch)
        + build.component_names(state="CANCELED", batch=batch)
    )
