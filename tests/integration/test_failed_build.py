# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT

import utils


def test_failed_build(test_env, scenario, repo, koji):
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
        "--optional",
        "rebuild_strategy=all",
        reuse=scenario.get("build_id"),
    )
    build.watch()

    assert build.state_name == "failed"
    batch = scenario["batch"]
    failing_components = scenario["failing_components"]
    canceled_components = scenario["canceled_components"]
    assert sorted(failing_components) == sorted(build.component_names(state="FAILED", batch=batch))
    assert sorted(canceled_components) == sorted(
        build.component_names(state="COMPLETE", batch=batch)
        + build.component_names(state="CANCELED", batch=batch)
    )
