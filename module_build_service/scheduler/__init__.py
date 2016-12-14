""" This is a sub-module for backend/scheduler functionality. """

import fedmsg
import moksha.hub

import module_build_service.scheduler.consumer


def main(initial_messages, stop_condition):
    """ Run the consumer until some condition is met.

    Setting stop_condition to None will run the consumer forever.
    """

    config = fedmsg.config.load_config()
    config['mbsconsumer'] = True
    config['mbsconsumer.stopcondition'] = stop_condition
    config['mbsconsumer.initial_messages'] = initial_messages

    consumers = [module_build_service.scheduler.consumer.MBSConsumer]

    # Rephrase the fedmsg-config.py config as moksha *.ini format for
    # zeromq. If we're not using zeromq (say, we're using STOMP), then just
    # assume that the moksha configuration is specified correctly already
    # in /etc/fedmsg.d/
    if config.get('zmq_enabled', True):
        moksha_options = dict(
            # XXX - replace this with a /dev/null endpoint.
            zmq_subscribe_endpoints=','.join(
                ','.join(bunch) for bunch in config['endpoints'].values()
            ),
        )
        config.update(moksha_options)

    # Note that the hub we kick off here cannot send any message.  You
    # should use fedmsg.publish(...) still for that.
    moksha.hub.main(
        # Pass in our config dict
        options=config,
        # Only run the specified consumers if any are so specified.
        consumers=consumers,
        # Tell moksha to quiet its logging.
        framework=False,
    )

def make_simple_stop_condition(session):
    """ Return a simple stop_condition callable.

    Intended to be used with the main() function here in manage.py and tests.

    The stop_condition returns true when the latest module build enters the any
    of the finished states.
    """

    def stop_condition(message):
        # XXX - We ignore the message here and instead just query the DB.

        # Grab the latest module build.
        module = session.query(models.ModuleBuild)\
            .order_by(models.ModuleBuild.id.desc())\
            .first()
        done = (
            module_build_service.models.BUILD_STATES["failed"],
            module_build_service.models.BUILD_STATES["ready"],
            # XXX should this one be removed?
            module_build_service.models.BUILD_STATES["done"],
        )
        return module.state in done

    return stop_condition
