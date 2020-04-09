# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT


def test_reuse_tagged_module(pkg_util, scenario, repo, koji, mbs):
    """
    Check that for newer builds, Koji resolver picks the appropriately tagged
    module build to be reused.

    Preconditions:
        1) Selected module under test has historically at least one tagged build in Koji.
           This Koji build is tagged with the preconfigured 'koji_tag_with_modules' tag.
        2) At least one build afterwards with build strategy 'all'

    Steps:
        1) Build module.
        2) Query MBS for its 'reused' module & get the NVR.
        3) Query MBS for its buildrequire platform & get the 'koji_tag_with_modules'.
        4) Query Koji for the 'reused' build (NVR).
        5) Query Koji for all builds tagged with the 'koji_tag_with_modules'.

    Checks:
        Assert that the 'reused' build is in the tagged collection.
    """

    repo.bump()

    # Build the build-under-test (should reuse all previous components)
    builds = pkg_util.run("--watch")
    assert len(builds) == 1
    new_build = builds[0]

    # Get the reused module as NVR
    reused_build_id = new_build.module_build_data['reused_module_id']
    assert reused_build_id
    reused_build = mbs.get_module_build(reused_build_id)
    assert len(reused_build.nvr()) == 3

    # Find configured 'koji_tag_with_modules' tag in the base module's metadata
    platform_stream = new_build.module_build_data['buildrequires']['platform'].get('stream')
    assert platform_stream

    platform_builds = mbs.get_module_builds(name='platform', stream=platform_stream, verbose=True)
    platform_builds = [b for b in platform_builds if b.module_build_data['state'] == 5]  # 'ready'
    assert len(platform_builds) == 1, f"Platform {platform_stream}: no build in state ready."

    metadata = platform_builds[0].get_modulemd()
    koji_tag_with_modules = metadata['data']['xmd']['mbs'].get('koji_tag_with_modules')
    assert koji_tag_with_modules, \
        f"Platform {platform_stream}: missing 'koji_tag_with_modules', Koji resolver disabled."

    # Get the reused build as Koji build
    reused_koji_id = koji.get_build(reused_build.nvr())['id']

    # Get all Koji builds tagged with our 'koji_tag_with_modules'
    tagged_builds = koji._session.listTagged(koji_tag_with_modules)
    assert tagged_builds, f"No builds tagged with: '{koji_tag_with_modules}'!"

    assert reused_koji_id in [b['id'] for b in tagged_builds],\
        f"Koji build '{reused_build.nvr()}' is not tagged with '{koji_tag_with_modules}'!"
