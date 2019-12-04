# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT

import utils


def test_reuse_all_components(test_env, repo, koji):
    """Rebuild the test module again, without changing any of the components with:

    `fedpkg module-build -w --optional rebuild_strategy=only-changed`

    Checks:
    * Verify that all the components are reused from the first build.
    * Verify that module-build-macros is not built in the second build.
    """
    build = utils.Build(test_env["packaging_utility"], test_env["mbs_api"])
    repo.bump()
    build.run(
        "--watch",
        "--optional",
        "rebuild_strategy=all",
        reuse=test_env["testdata"]["reuse_all_components"].get("build_id"),
    )
    task_ids = build.component_task_ids()
    task_ids.pop("module-build-macros")

    repo.bump()
    build.run(
        "-w",
        "--optional",
        "rebuild_strategy=only-changed",
        reuse=test_env["testdata"]["reuse_all_components"].get("build_id_reused"))
    reused_task_ids = build.component_task_ids()

    assert not build.components(package="module-build-macros")
    assert task_ids == reused_task_ids
