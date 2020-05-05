def test_buildonly(clone_and_start_build, mbs):
    """Test the buildonly attribute

    Preconditions:
    * modulemd with at least 1 'buildonly = true' RPM component.

    Steps:
    * Start the  module build and wait for it to finish.
    * Assert that the expected filter field was created in the module metadata.
    """

    repo, builds = clone_and_start_build

    # Check the original modulemd
    modulemd = repo.modulemd
    assert not modulemd["data"].get("filter")
    assert modulemd["data"]["components"].get("rpms")
    rpms = modulemd["data"]["components"].get("rpms")

    build_only_rpms = [k for k, v in rpms.items() if bool(v.get("buildonly"))]
    other_rpms = [k for k, v in rpms.items() if not bool(v.get("buildonly"))]

    assert build_only_rpms, "No RPM has 'buildonly' field set to true"

    # Wait until our build is ready
    build_id = builds[0].id
    mbs.wait_for_module_build_to_succeed(build_id, timeout=(60 * 60), interval=30)

    # assert filter field in final modulemd
    modulemd = mbs.get_module_build(build_id).get_modulemd()
    assert modulemd["data"]["filter"], "No filters in the build metadata."
    assert modulemd["data"]["filter"]["rpms"], "No RPM filters in the build metadata."
    msg = "Expected RPM '{}' not found in the finished build filters."
    for rpm in build_only_rpms:
        assert rpm in modulemd["data"]["filter"]["rpms"], msg.format(rpm)

    msg = "Not expected RPM '{}' found in the finished build filters."
    for rpm in other_rpms:
        assert rpm not in modulemd["data"]["filter"]["rpms"], msg.format(rpm)
