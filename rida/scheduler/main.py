#!/usr/bin/python3
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
#            Ralph Bean <rbean@redhat.com>

"""The module build orchestrator for Modularity, the builder.

This is the main component of the orchestrator and is responsible for
proper scheduling component builds in the supported build systems.
"""


import inspect
import logging
import os
import threading

import rida.config
import rida.logger
import rida.messaging
import rida.scheduler.handlers.modules
#import rida.scheduler.handlers.builds
import sys

import koji

log = logging.getLogger(__name__)

# Load config from git checkout or the default location
config = None
here = sys.path[0]
if here not in ('/usr/bin', '/bin', '/usr/local/bin'):
    # git checkout
    config = rida.config.from_file("rida.conf")
else:
    # production
    config = rida.config.from_file()

# TODO: Utilized rida.builder to prepare the buildroots and build components.
# TODO: Set the build state to build once the module build is started.
# TODO: Set the build state to done once the module build is done.
# TODO: Set the build state to failed if the module build fails.

def module_build_state_from_msg(msg):

    state = int(msg['msg']['state'])
    # TODO better handling
    assert state in rida.BUILD_STATES.values(), "state=%s(%s) is not in %s" % (state, type(state), rida.BUILD_STATES.values())
    return state

class Messaging(threading.Thread):

    # These are our main lookup tables for figuring out what to run in response
    # to what messaging events.
    on_build_change = {
        koji.BUILD_STATES["BUILDING"]: lambda x: x
    }
    on_module_change = {
        rida.BUILD_STATES["init"]: rida.scheduler.handlers.modules.init,
    }

    def sanity_check(self):
        """ On startup, make sure our implementation is sane. """
        # Ensure we have every state covered
        for state in rida.BUILD_STATES:
            if state not in self.on_module_change:
                raise KeyError("Module build states %r not handled." % state)
        for state in koji.BUILD_STATES:
            if state not in self.on_build_change:
                raise KeyError("Koji build states %r not handled." % state)

        all_fns = self.on_build_change.items() + self.on_module_change.items()
        for key, callback in all_fns:
            expected = ['conf', 'db', 'msg']
            argspec = inspect.getargspec(callback)
            if argspec != expected:
                raise ValueError("Callback %r, state %r has argspec %r!=%r" % (
                    callback, key, argspec, expected))

    def run(self):
        #self.sanity_check()
        # TODO: Check for modules that can be set to done/failed
        # TODO: Act on these things somehow
        # TODO: Emit messages about doing so
        for msg in rida.messaging.listen(backend=config.messaging):
            log.debug("Saw %r, %r" % (msg['msg_id'], msg['topic']))
            log.debug(msg)

            # Choose a handler for this message
            if '.buildsys.build.state.change' in msg['topic']:
                handler = self.on_build_change[msg['msg']['init']]
            elif '.rida.module.state.change' in msg['topic']:
                handler = self.on_module_change[module_build_state_from_msg(msg)]
            else:
                log.debug("Unhandled message...")
                continue

            # Execute our chosen handler
            with rida.database.Database(config) as session:
                handler(config, session, msg)

class Polling(threading.Thread):
    def run(self):
        while True:
            # TODO: Check for module builds in the wait state
            # TODO: Check component builds in the open state
            # TODO: Check for modules that can be set to done/failed
            # TODO: Act on these things somehow
            # TODO: Emit messages about doing so
            # TODO: Sleep for a configuration-determined interval
            pass


def main():
    rida.logger.init_logging(config)
    log.info("Starting ridad.")
    try:
        messaging_thread = Messaging()
        polling_thread = Polling()
        messaging_thread.start()
        polling_thread.start()
    except KeyboardInterrupt:
        # FIXME: Make this less brutal
        os._exit()