# -*- coding: utf-8 -*-


# Copyright (c) 2016  Red Hat, Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# Written by Petr Šabata <contyk@redhat.com>

"""The module build orchestrator for Modularity, the builder.

This is the main component of the orchestrator and is responsible for
proper scheduling component builds in the supported build systems.
"""

# TODO: Load configuration.
# TODO: Listen for bus messages from build systems about builds being done.
# TODO: Periodically check the state of the build systems' tasks, in case some
#       messages got lost.
# TODO: Emit messages about the module build being done.
# TODO; Watch the database and process modules in the wait state.
# TODO: Construct the name of the tag/target according to the policy and record
#       it in PDC.
# TODO: Create the relevant koji tags and targets.
# TODO: Query the PDC to find what modules satisfy the build dependencies and
#       their tag names.
# TODO: Set tag inheritance for the created tag, using the build dependencies'
#       tags.
# TODO: Ensure the RPM %dist tag is set according to the policy.
# TODO: Build the module components in the prepared tag.
# TODO: Set the build state to build once the module build is started.
# TODO: Set the build state to done once the module build is done.
# TODO: Set the build state to failed if the module build fails.
