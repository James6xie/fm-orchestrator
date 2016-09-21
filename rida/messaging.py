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
# Written by Ralph Bean <rbean@redhat.com>

"""Generic messaging functions."""


def publish(topic, msg, backend, modname='rida'):
    """ Publish a single message to a given backend, and return. """
    try:
        handler = _messaging_backends[backend]['publish']
    except KeyError:
        raise KeyError("No messaging backend found for %r" % backend)
    return handler(topic, msg, modname=modname)


def listen(backend, **kwargs):
    """ Yield messages from a given messaging backend.

    The ``**kwargs`` arguments will be passed on to the backend to do some
    backend-specific connection handling, throttling, or filtering.
    """
    try:
        handler = _messaging_backends[backend]['listen']
    except KeyError:
        raise KeyError("No messaging backend found for %r" % backend)

    for event in handler(**kwargs):
        yield event


def _fedmsg_publish(topic, msg, modname):
    import fedmsg
    return fedmsg.publish(topic=topic, msg=msg, modname=modname)


def _fedmsg_listen(**kwargs):
    import fedmsg
    for name, endpoint, topic, msg in fedmsg.tail_messages(**kwargs):
        yield msg

_messaging_backends = {
    'fedmsg': {
        'publish': _fedmsg_publish,
        'listen': _fedmsg_listen,
    },
}
