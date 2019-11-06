# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT

"""
This module defines constant for events emitted by external services that work
with MBS together to complete a module build.

The event name is defined in general as much as possible, especially for the
events from Koji. Because some instance based on Koji, like Brew, might send
messages to different topics on different message bus. For example, when a
build is complete, Koji sends a message to topic buildsys.build.state.change,
however Brew sends to topic brew.build.complete, etc.
"""

KOJI_BUILD_CHANGE = "koji_build_change"
KOJI_TAG_CHANGE = "koji_tag_change"
KOJI_REPO_CHANGE = "koji_repo_change"
MBS_MODULE_STATE_CHANGE = "mbs_module_state_change"
GREENWAVE_DECISION_UPDATE = "greenwave_decision_update"
