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

import logging
import os
import threading

import rida.config
import rida.messaging

log = logging.getLogger()

# TODO: Load the config file from environment
config = rida.config.from_file("rida.conf")

# TODO: Utilized rida.builder to prepare the buildroots and build components.
# TODO: Set the build state to build once the module build is started.
# TODO: Set the build state to done once the module build is done.
# TODO: Set the build state to failed if the module build fails.

class Messaging(threading.Thread):
    def run(self):
        while True:
            # TODO: Listen for bus messages from rida about module builds
            #       entering the wait state
            # TODO: Listen for bus messages from the buildsystem about
            #       component builds changing state
            # TODO: Check for modules that can be set to done/failed
            # TODO: Act on these things somehow
            # TODO: Emit messages about doing so
            for msg in rida.messaging.listen(backend=config.messaging):
                print("Saw %r with %r" % (msg['topic'], msg))
                if '.buildsys.build.state.change' in msg['topic']:
                    print("A build changed state in koji!!")
                elif '.rida.module.state.change' in msg['topic']:
                    print("Our frontend says that a module changed state!!")
                else:
                    pass

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


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)  # For now
    logging.info("Starting ridad.")
    try:
        messaging_thread = Messaging()
        polling_thread = Polling()
        messaging_thread.start()
        polling_thread.start()
    except KeyboardInterrupt:
        # FIXME: Make this less brutal
        os._exit()
