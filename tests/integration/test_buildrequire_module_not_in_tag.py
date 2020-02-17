# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
import pytest
from sh import ErrorReturnCode


def test_buildrequire_module_not_in_tag(pkg_util, scenario, repo, koji):
    """
        Run a build with with an invalid 'build_require' module.
        I.e.: required module is picked in such a way,
        that it is not tagged according to the the base module (platform) requirements,
        see platform's modulemd file and its 'koji_tag_with_modules' attribute
        (e.g.: platform: el-8.1.0 --> rhel-8.1.0-modules-build).

        Koji resolver is expected to not be able to satisfy this build requirement and hence fail the build.

        Assert that:
        * the module build hasn't been accepted by MBS - rhpkg utility returns something else than 0

        If assert fails:
        * cancel all triggered module builds

        """

    repo.bump()

    try:
        builds = pkg_util.run(
            "--optional",
            "rebuild_strategy=all"
        )

        for build in builds:
            print("Canceling module-build {}...".format(build.id))
            pkg_util.cancel(build)

        pytest.fail("build_require satisfied and module build accepted by MBS!")

    except ErrorReturnCode as e:
        # expected outcome is that build submission fails
        pass
