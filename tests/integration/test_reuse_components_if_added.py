import copy


def extracted_test_function(repo, pkg_util, scenario):
    """Test if previous components are reused properly, after components are added/removed.

    Prerequisites:
        EMPTY (no components/RPMs) module MD file
    Steps:
        1) Make changes to the modulemd according to test scenario (first build)
        2) Make a clean build (rebuild strategy : all).
        3) Add/remove RPMs according to test scenario (second build)
        4) Rebuild, rebuild strategy according to test scenario
        5) Revert to the initial state.

    :param utils.Repo repo: repo fixture
    :param utils.PackagingUtility pkg_util: pkg_util fixture
    :param dict scenario: see example.test.env
    """
    test_rpms = repo.components

    # Prepare test data from test.env scenario
    first_build_rpms = {test_rpms[i] for i in scenario["first_build"]}
    second_build_rpms = {test_rpms[i] for i in scenario["second_build"]}
    expected_reused = {test_rpms[i] for i in scenario["expected_reused"]}
    expected_rebuilt = {test_rpms[i] for i in scenario["expected_rebuilt"]}
    rebuild_strategy = scenario["rebuild_strategy"]

    # Save initial state
    original_metadata = repo.modulemd
    original_rpms = repo.modulemd["data"]["components"]["rpms"]

    # Prepare initial build metadata & push
    tmp_metadata = copy.deepcopy(original_metadata)
    tmp_metadata["data"]["components"]["rpms"] = {}
    for rpm in first_build_rpms:
        tmp_metadata["data"]["components"]["rpms"][rpm] = original_rpms[rpm]

    repo.write_to_modulemd(tmp_metadata)
    repo.add_all_commit_and_push(f'1st build: "{first_build_rpms}"')

    try:
        # Make an initial build (to be later reused)
        builds = pkg_util.run("--watch", "--optional", "rebuild_strategy=all")
        assert len(builds) == 1, "Initial build failed!"

        # Prepare 2nd build metadata & push
        tmp_metadata["data"]["components"]["rpms"] = {}
        for rpm in second_build_rpms:
            tmp_metadata["data"]["components"]["rpms"][rpm] = original_rpms[rpm]
        repo.write_to_modulemd(tmp_metadata)
        repo.add_all_commit_and_push(f'2nd build: "{second_build_rpms}"')

        # Make a new build
        builds = pkg_util.run("--watch", "--optional", f"rebuild_strategy={rebuild_strategy}")
        assert len(builds) == 1, "Second (re)build failed!"

        build = builds[0]
        # we don"t care about module-build-macros
        build_components = [c for c in build.components() if c["package"] != "module-build-macros"]

        # Partition components by "reused" state - package name only
        reused_msg = "Reused component from previous module build"
        actually_reused = {
            c["package"] for c in build_components if c["state_reason"] == reused_msg
        }
        actually_rebuilt = {
            c["package"] for c in build_components if c["state_reason"] != reused_msg
        }

        assert actually_reused == expected_reused
        assert actually_rebuilt == expected_rebuilt

    finally:  # Revert the change
        repo.write_to_modulemd(original_metadata)
        repo.add_all_commit_and_push("Revert")


# Each function needs its own test branch due to parallel execution.
# Module branch provides data - i.e. RPM components - and test.env provides
# scenario to be executed, i.e. which RPMs go to the 1st and 2nd build
# as well as expected result - see test.env example.
def test_reuse_components_if_added_1(repo, pkg_util, scenario):
    extracted_test_function(repo, pkg_util, scenario)


def test_reuse_components_if_added_2(repo, pkg_util, scenario):
    extracted_test_function(repo, pkg_util, scenario)


def test_reuse_components_if_removed_1(repo, pkg_util, scenario):
    extracted_test_function(repo, pkg_util, scenario)


def test_reuse_components_if_removed_2(repo, pkg_util, scenario):
    extracted_test_function(repo, pkg_util, scenario)
