# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT

import utils


def test_scratch_build(test_env, repo, koji):
    """
    Run a scratch build with "rebuild_strategy=all".

    Check that:
    * the module build is done with the correct components
    * the module build completes in the "done" state
      (as opposed to the "ready" state)
    * no content generator builds are created in Koji
    """
    build = utils.Build(test_env["packaging_utility"], test_env["mbs_api"])
    build.run("--watch", "--scratch", "--optional", "rebuild_strategy=all")

    assert build.state_name == "done"
    assert sorted(build.components(state="COMPLETE")) == sorted(
        repo.components + ["module-build-macros"]
    )

    cg_build = koji.get_build(build.nvr())
    cg_devel_build = koji.get_build(build.nvr(name_suffix="-devel"))
    assert not (cg_build or cg_devel_build)
