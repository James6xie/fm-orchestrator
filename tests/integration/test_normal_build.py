# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT

import utils


def test_normal_build(test_env, repo, koji):
    """
    Run build with `rhpkg-stage module-build --optional rebuild_strategy=all`

    Checks:
    * Check that MBS will submit all the component builds
    * Check that buildorder of components is respected
    * Check that MBS will create two content generator builds representing the module:
        - [module]
        - [module]-devel
    * Check that MBS changed the buildrequired platform to have a suffix of “z”
        if a Platform stream is representing a GA RHEL release.
    """
    build = utils.Build(test_env["packaging_utility"], test_env["mbs_api"])
    repo.bump()
    build_id = build.run(
        "--optional",
        "rebuild_strategy=all",
        reuse=test_env["testdata"]["normal_build"].get("build_id"),
    )
    build.watch()

    assert sorted(build.component_names()) == sorted(repo.components + ["module-build-macros"])

    expected_buildorder = test_env["testdata"]["normal_build"]["buildorder"]
    expected_buildorder = [set(batch) for batch in expected_buildorder]
    actual_buildorder = build.batches()
    assert actual_buildorder == expected_buildorder

    cg_build = koji.get_build(build.nvr())
    cg_devel_build = koji.get_build(build.nvr(name_suffix="-devel"))
    assert cg_build and cg_devel_build
    assert cg_devel_build['extra']['typeinfo']['module']['module_build_service_id'] == int(build_id)

    modulemd = koji.get_modulemd(cg_build)
    actual_platforms = modulemd["data"]["dependencies"][0]["buildrequires"]["platform"]
    expected_platforms = repo.platform
    platform_ga = test_env["testdata"]["normal_build"].get("platform_is_ga")
    if platform_ga:
        expected_platforms = [f"{pf}.z" for pf in expected_platforms]
    assert expected_platforms == actual_platforms
