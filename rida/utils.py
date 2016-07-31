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
# Written by Ralph Bean <rbean@redhat.com>
""" Utility functions for rida. """

import functools
import time

import koji


def retry(timeout=120, interval=30, wait_on=Exception):
    """ A decorator that allows to retry a section of code...
    ...until success or timeout.
    """
    def wrapper(function):
        @functools.wraps(function)
        def inner(*args, **kwargs):
            start = time.time()
            while True:
                if (time.time() - start) >= (timeout * 60.0):
                    raise  # This re-raises the last exception.
                try:
                    return function(*args, **kwargs)
                except wait_on:
                    time.sleep(interval)
        return inner
    return wrapper


def start_next_build_batch(module, session, builder, components=None):
    """ Starts a next round of the build cycle for a module. """

    if any([c.state == koji.BUILD_STATES['BUILDING']
            for c in module.component_builds ]):
        raise ValueError("Cannot start a batch when another is in flight.")

    # The user can either pass in a list of components to 'seed' the batch, or
    # if none are provided then we just select everything that hasn't
    # successfully built yet.
    unbuilt_components = components or [
        c for c in module.component_builds
        if c.state != koji.BUILD_STATES['COMPLETE']
    ]
    module.batch += 1
    for c in unbuilt_components:
        c.batch = module.batch
        c.task_id = builder.build(artifact_name=c.package, source=c.scmurl)

    session.commit()
