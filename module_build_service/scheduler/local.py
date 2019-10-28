# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT

import fedmsg
import logging
import module_build_service.models
import moksha.hub

from module_build_service.db_session import db_session

log = logging.getLogger(__name__)


"""
This module contains functions to control fedmsg-hub running locally for local
module build and running tests within test_build.py particularly.
"""

__all__ = ["main", "make_simple_stop_condition"]


def main(initial_messages, stop_condition):
    """ Run the consumer until some condition is met.

    Setting stop_condition to None will run the consumer forever.
    """

    config = fedmsg.config.load_config()
    config["mbsconsumer"] = True
    config["mbsconsumer.stop_condition"] = stop_condition
    config["mbsconsumer.initial_messages"] = initial_messages

    # Moksha requires that we subscribe to *something*, so tell it /dev/null
    # since we'll just be doing in-memory queue-based messaging for this single
    # build.
    config["zmq_enabled"] = True
    config["zmq_subscribe_endpoints"] = "ipc:///dev/null"

    # Lazy import consumer to avoid potential import cycle.
    # For example, in some cases, importing event message from events.py would
    # cause importing the consumer module, which then starts to import relative
    # code inside handlers module, and the original code is imported eventually.
    import module_build_service.scheduler.consumer

    consumers = [module_build_service.scheduler.consumer.MBSConsumer]

    # Note that the hub we kick off here cannot send any message.  You
    # should use fedmsg.publish(...) still for that.
    moksha.hub.main(
        # Pass in our config dict
        options=config,
        # Only run the specified consumers if any are so specified.
        consumers=consumers,
        # Do not run default producers.
        producers=[],
        # Tell moksha to quiet its logging.
        framework=False,
    )


def make_simple_stop_condition():
    """ Return a simple stop_condition callable.

    Intended to be used with the main() function here in manage.py and tests.

    The stop_condition returns true when the latest module build enters the any
    of the finished states.
    """

    def stop_condition(message):
        # XXX - We ignore the message here and instead just query the DB.

        # Grab the latest module build.
        module = (
            db_session.query(module_build_service.models.ModuleBuild)
            .order_by(module_build_service.models.ModuleBuild.id.desc())
            .first()
        )
        done = (
            module_build_service.models.BUILD_STATES["failed"],
            module_build_service.models.BUILD_STATES["ready"],
            module_build_service.models.BUILD_STATES["done"],
        )
        result = module.state in done
        log.debug("stop_condition checking %r, got %r" % (module, result))

        # moksha.hub.main starts the hub and runs it in a separate thread. When
        # the result is True, remove the db_session from that thread local so
        # that any pending queries in the transaction will not block other
        # queries made from other threads.
        # This is useful for testing particularly.
        if result:
            db_session.remove()

        return result

    return stop_condition
