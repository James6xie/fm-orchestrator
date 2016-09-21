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
#            Matt Prahl <mprahl@redhat.com>

"""Generic messaging functions."""

import re
from rida import logger


class BaseMessage(object):
    def __init__(self, msg_id):
        """
        A base class to abstract messages from different backends
        :param msg_id: the id of the msg (e.g. 2016-SomeGUID)
        """
        self.msg_id = msg_id

    @staticmethod
    def from_fedmsg(topic, msg):
        """
        Takes a fedmsg topic and message and converts it to a message object
        :param topic: the topic of the fedmsg message
        :param msg: the message contents from the fedmsg message
        :return: an object of BaseMessage descent if the message is a type
        that the app looks for, otherwise None is returned
        """
        regex_pattern = re.compile(
            (r'(?P<category>buildsys|rida)(?:\.)'
             r'(?P<object>build|repo|module)(?:(?:\.)'
             r'(?P<subobject>state))?(?:\.)(?P<event>change|done)$'))
        regex_results = re.search(regex_pattern, topic)

        if regex_results:
            category = regex_results.group('category')
            object = regex_results.group('object')
            subobject = regex_results.group('subobject')
            event = regex_results.group('event')

            msg_id = msg.get('msg_id')
            msg_inner_msg = msg.get('msg')

            # If there isn't a msg dict in msg then this message can be skipped
            if not msg_inner_msg:
                logger.debug(('Skipping message without any content with the '
                             'topic "{0}"').format(topic))
                return None

            msg_obj = None

            if category == 'buildsys' and object == 'build' and \
                    subobject == 'state' and event == 'change':
                build_id = msg_inner_msg.get('build_id')
                build_new_state = msg_inner_msg.get('new')
                build_name = msg_inner_msg.get('name')
                build_version = msg_inner_msg.get('version')
                build_release = msg_inner_msg.get('release')

                msg_obj = KojiBuildChange(
                    msg_id, build_id, build_new_state, build_name,
                    build_version, build_release)

            elif category == 'buildsys' and object == 'repo' and \
                    subobject is None and event == 'done':
                repo_tag = msg_inner_msg.get('tag')
                msg_obj = KojiRepoChange(msg_id, repo_tag)

            elif category == 'rida' and object == 'module' and \
                    subobject == 'state' and event == 'change':
                msg_obj = RidaModule(
                    msg_id, msg_inner_msg.get('id'), msg_inner_msg.get('state'))

            # If the message matched the regex and is important to the app,
            # it will be returned
            if msg_obj:
                return msg_obj

        logger.debug('Skipping unrecognized message with the topic "{0}"'
                     .format(topic))
        return None


class KojiBuildChange(BaseMessage):
    """ A class that inherits from BaseMessage to provide a message
    object for a build's info (in fedmsg this replaces the msg dictionary)
    :param msg_id: the id of the msg (e.g. 2016-SomeGUID)
    :param build_id: the id of the build (e.g. 264382)
    :param build_new_state: the new build state, this is currently a Koji
    integer
    :param build_name: the name of what is being built
    (e.g. golang-googlecode-tools)
    :param build_version: the version of the build (e.g. 6.06.06)
    :param build_release: the release of the build (e.g. 4.fc25)
    """
    def __init__(self, msg_id, build_id, build_new_state, build_name,
                 build_version, build_release):
        super(KojiBuildChange, self).__init__(msg_id)
        self.build_id = build_id
        self.build_new_state = build_new_state
        self.build_name = build_name
        self.build_version = build_version
        self.build_release = build_release


class KojiRepoChange(BaseMessage):
    """ A class that inherits from BaseMessage to provide a message
    object for a repo's info (in fedmsg this replaces the msg dictionary)
    :param msg_id: the id of the msg (e.g. 2016-SomeGUID)
    :param repo_tag: the repo's tag (e.g. SHADOWBUILD-f25-build)
    """
    def __init__(self, msg_id, repo_tag):
        super(KojiRepoChange, self).__init__(msg_id)
        self.repo_tag = repo_tag


class RidaModule(BaseMessage):
    """ A class that inherits from BaseMessage to provide a message
    object for a module event generated by rida
    :param msg_id: the id of the msg (e.g. 2016-SomeGUID)
    :param module_build_id: the id of the module build
    :param module_build_state: the state of the module build
    """
    def __init__(self, msg_id, module_build_id, module_build_state):
        super(RidaModule, self).__init__(msg_id)
        self.module_build_id = module_build_id
        self.module_build_state = module_build_state


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
    """
    Parses a fedmsg event and constructs it into the appropriate message object
    """
    import fedmsg
    for name, endpoint, topic, msg in fedmsg.tail_messages(**kwargs):
        msg_obj = BaseMessage.from_fedmsg(topic, msg)
        if msg_obj:
            yield msg_obj

_messaging_backends = {
    'fedmsg': {
        'publish': _fedmsg_publish,
        'listen': _fedmsg_listen,
    },
}
