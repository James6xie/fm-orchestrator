
def test_scratch_final_mmd(scenario, repo, mbs, pkg_util):
    """Test that scratch builds have properly generated final mmds.

    Steps:
    * Submit a scratch build and wait for it to be ready.
    * Query MBS API for final mmds.

    Checks:
    * That there's a mmd for each arch.
    * Content of the final mmd is roughly as expected.
    """
    builds = pkg_util.run("--scratch", reuse=scenario.get("build_id"))
    assert len(builds) == 1
    build = builds[0]
    mbs.wait_for_module_build_to_succeed(build)

    original_mmd = repo.modulemd
    expected_arches = set(build.module_build_data["arches"])
    expected_rpms = set(original_mmd["data"]["components"]["rpms"].keys())

    # Get the actual final mmds
    mmds = mbs.get_final_mmds(build)

    assert expected_arches == set(mmds.keys())

    for arch in expected_arches:
        mmd = mmds.get(arch)["data"]
        assert arch == mmd["arch"]
        assert expected_rpms == set(mmd["components"]["rpms"].keys())
        assert build.module_build_data["context"] == mmd["context"]

        # assert that the submitted rpms are present in the artifacts list
        actual_artifact_rpms = set(mmd["artifacts"]["rpms"])
        for rpm in expected_rpms:
            actual_rpm = build.components(package=rpm)
            assert actual_rpm
            n, v, r = actual_rpm[0]["nvr"].split("-")
            artifact_name = "{}-0:{}-{}.{}"
            artifacts = {artifact_name.format(n, v, r, a) for a in [arch, "src"]}
            assert artifacts.issubset(actual_artifact_rpms)
