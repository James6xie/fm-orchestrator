from requests import HTTPError


def assert_build_in_build_state(mbs, build):
    """Assert build state was reached and then cancel the build using REST."""
    try:
        mbs.wait_for_module_build(build, lambda bld: bld.get("state") == 2, timeout=10)
    finally:
        mbs.cancel_module_build(build.id)


def test_rest_submit_module_build(pkg_util, scenario, repo, mbs):
    """Test module build submission. Tests only whether or not
    build gets accepted and transitions successfully to the build state.

    Two variants:
      * submit module build with modulemd yaml (test YAMLFileHandler)
      * submit module build with scmurl (test SCMHandler)
    ..are combined into one method to reuse 1 single test branch.

    Steps:
      * Submit module build using module's SCM URL (HTTP POST).
      * Assert that build reaches 'build' state.
      * Cancel the build (HTTP PATCH)
    """

    # 1) SCMURL submission
    repo.bump()

    scmurl = pkg_util.giturl().replace("#", "?#")
    branch = scenario["branch"]
    data = {"scmurl": scmurl, "branch": branch}

    builds = mbs.submit_module_build(data)
    assert len(builds) == 1
    assert_build_in_build_state(mbs, builds[0])

    # 2) YAML submission (might not be enabled, but if it is, let's test it)
    repo.bump()

    data = {"modulemd": str(repo.modulemd)}
    try:
        builds = mbs.submit_module_build(data)
    except HTTPError as e:
        if "YAML submission is not enabled" not in e.response.text:
            raise
    else:
        assert_build_in_build_state(mbs, builds[0])
