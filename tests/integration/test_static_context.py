
def test_static_context(clone_and_start_build, mbs):
    repo, builds = clone_and_start_build

    static_contexts = repo.modulemd["data"]["xmd"]["mbs_options"]["contexts"]

    assert len(builds) == len(static_contexts)

    for build in builds:
        mbs.wait_for_module_build(build, lambda b: b.get("state") >= 0)
        build = mbs.get_module_build(build)
        assert build.get("context") in static_contexts
