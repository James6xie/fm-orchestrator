import getpass


def test_rest_module_build(clone_and_start_build, mbs, koji, pkg_util):
    """Start a module build and query MBS API for build details (?verbose=True).
    Assert as many values as possible.

    * There is no need for exhaustive testing of the REST API here,
    as extensive coverage of it is already implemented in tests/test_web/test_views.py.
    """
    repo, builds = clone_and_start_build
    assert len(builds) >= 1

    username = getpass.getuser()
    build_id = builds[0].id
    giturl = pkg_util.giturl()

    # wait until 'build' state
    mbs.wait_for_module_build(build_id, lambda bld: bld.get("state") == 2)

    build = mbs.get_module_build(build_id)
    assert build.get("id") == build_id
    assert build.get("owner") == username
    assert build.get("rebuild_strategy") == "all"
    # additional '?' in url for for branch parameter (packaging utility prints url without it)
    assert build.get("scmurl").replace("?", "") == giturl
    assert build.get("state_name") == "build"
    assert build.get("name") == repo.module_name
    assert build.get("stream") == repo.branch
    assert not build.get("scratch")

    assert build.get("tasks")
    if repo.modulemd["data"]["components"]:
        if repo.modulemd["data"]["components"].get("rpms"):
            rpms = [k for k in repo.modulemd["data"]["components"]["rpms"]]
            rpms.append("module-build-macros")
            assert len(rpms) == len(build.get('component_builds'))
            for rpm in rpms:
                assert build.get("tasks")["rpms"][rpm]
        else:
            assert not build.get('component_builds')

    assert type(build.get("id")) is int
    assert build.get("name")
    assert not build.get("time_completed")
