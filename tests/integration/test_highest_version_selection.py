# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT


def test_highest_version_selection(pkg_util, scenario, repo, mbs, require_koji_resolver):
    """
    Build module with stream with multiple versions in buildrequires.

    Checks:
    * Check that the highest version of build in required stream is used.
    """
    repo.bump()
    builds = pkg_util.run("--optional", "rebuild_strategy=all",
                          reuse=scenario.get("build_id"))
    build = builds[0]
    module_id = build.module_build_data['id']
    build_info = mbs.get_module_build(module_id)
    module_version_used = build_info.data['buildrequires']['testmodule']['version']
    module_builds = mbs.get_builds(scenario['stream_module'], scenario['test_stream'])
    module_versions = [build.data['version'] for build
                       in module_builds]
    assert len(module_versions) >= 2, 'More than one version is needed.'
    error_msg = 'Version used is not the latest.'
    assert module_version_used == max(module_versions), error_msg
