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

import time
import sched
from functools import wraps

from module_build_service import log


KOJI_BUILD_CHANGE = "koji_build_change"
KOJI_TAG_CHANGE = "koji_tag_change"
KOJI_REPO_CHANGE = "koji_repo_change"
MBS_MODULE_STATE_CHANGE = "mbs_module_state_change"
GREENWAVE_DECISION_UPDATE = "greenwave_decision_update"


class Scheduler(sched.scheduler):
    """
    Subclass of `sched.scheduler` allowing to schedule handlers calls.

    If one of the MBS handler functions need to call another handler, they need to do it in a safe
    way - such another handler call should not be done in the middle of another handler's
    execution.

    This class provides an solution for that. Handler can schedule run of other handler using
    the `add` method. The handlers should use `mbs_event_handler` decorator which ensures that
    the `run` method is called at the end of handler's execution and other scheduler handlers
    are executed.
    """

    def add(self, handler, arguments=()):
        """
        Schedule execution of `handler` with `arguments`.
        """
        self.enter(0, 0, handler, arguments)

    def run(self):
        """
        Runs scheduled handlers.
        """
        log.debug("Running event scheduler with following events:")
        for event in self.queue:
            log.debug("    %r", event)
        sched.scheduler.run(self)

    def reset(self):
        """
        Resets the Scheduler to initial state.
        """
        while not self.empty():
            self.cancel(self.queue[0])


scheduler = Scheduler(time.time, delayfunc=lambda x: x)


def mbs_event_handler():
    """
    A decorator for MBS event handlers. It implements common tasks which should otherwise
    be repeated in every MBS event handler, for example:

      - at the end of handler, call events.scheduler.run().
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            finally:
                scheduler.run()

        return wrapper

    return decorator