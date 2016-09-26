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

import json
import os
import re
try:
    from inspect import signature
except ImportError:
    from funcsigs import signature

from rida import log


class BaseMessage(object):
    def __init__(self, msg_id):
        """
        A base class to abstract messages from different backends
        :param msg_id: the id of the msg (e.g. 2016-SomeGUID)
        """
        self.msg_id = msg_id

    def __repr__(self):
        init_sig = signature(self.__init__)

        args_strs = (
            "{}={!r}".format(name, getattr(self, name))
            if param.default != param.empty
            else repr(getattr(self, name))
            for name, param in init_sig.parameters.items())

        return "{}({})".format(type(self).__name__, ', '.join(args_strs))

    @staticmethod
    def from_amq(topic, msg):
        msg_obj = None
        properties = None
        body = None
        if hasattr('properties'):
            properties = json.loads(msg.properties, encoding='utf8')
            if not ((properties.get('service') == 'koji' or properties.get('service') == 'rida')):
                log.debug("Skipping msg: %s" % msg)
                return None

        service = properties.get('service')
        # This probably appies only for brew
        # Also wouldn't be easier to use properties?
        if service == 'koji':
            content = json.loads(msg.body, encoding='utf8')['content']
            log.debug("Found koji related msg: %s" % msg)
            method =  content['info']['method']
            msg_type =  content['info']['type']

            if method == 'newRepo':
                attr  = content['attribute']
                state = content['info']['new']
                if attr == "state" and state == "CLOSED":
                    repo_tag = content['info']['request']
                    assert len(repo_tag) == 1
                    msg_obj = KojiRepoChange(msg.id, repo_tag[0])

            elif method == 'build' and msg_type == 'TaskStateChange':
                attr = content['attribute']
                if attr == "state":
                    build_id = content['info']['id']
                    build_state = content['new']
                    # These are not available before build is assigned
                    build_name = None
                    build_version = None
                    build_release = None
                    nvr_req = set(['name', 'version', 'release'])
                    if nvr_req.issubset(set(content['info'].keys())):
                        build_name = content['info']['name']
                        build_version = content['info']['version']
                        build_release = content['info']['release']

                    msg_obj = KojiBuildChange(
                        msg.id, build_id, build_state, build_name,
                        build_version,build_release)

        elif service == 'rida':
            log.debug("Found rida related msg: %s" % msg)
            body = json.loads(msg.body, encoding='utf8')
            if topic == 'module.state.change':
               msg_obj = RidaModule(
                    msg.id, body['id'], body['state'] )

        if msg_obj:
            return msg_obj

        log.debug('Skipping unrecognized message: %s' % msg)
        return  None

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
                log.debug(('Skipping message without any content with the '
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

        log.debug('Skipping unrecognized message with the topic "{0}"'
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


def publish(topic, msg, conf, service='rida'):
    """
    Publish a single message to a given backend, and return
    :param topic: the topic of the message (e.g. module.state.change)
    :param msg: the message contents of the message (typically JSON)
    :param conf: a Config object from the class in config.py
    :param service: the system that is publishing the message (e.g. rida)
    :return:
    """
    try:
        handler = _messaging_backends[conf.messaging]['publish']
    except KeyError:
        raise KeyError("No messaging backend found for %r" % conf.messaging)
    return handler(topic, msg, service=service)


def listen(conf, **kwargs):
    """
    Yield messages from the messaging backend in conf.messaging.
    :param conf: a Config object from the class in config.py
    :param kwargs: any additional arguments to pass to the backend handler
    :return: yields a message object (child class from BaseMessage)
    """
    try:
        handler = _messaging_backends[conf.messaging]['listen']
    except KeyError:
        raise KeyError("No messaging backend found for %r" % conf.messaging)

    for event in handler(conf, **kwargs):
        yield event


def _fedmsg_publish(conf, topic, msg, service):
    import fedmsg
    return fedmsg.publish(topic, msg=msg, modname=service)

def _fedmsg_listen(conf, **kwargs): # XXX: should we keep conf?
    """
    Parses a fedmsg event and constructs it into the appropriate message object
    """
    import fedmsg
    for name, endpoint, topic, msg in fedmsg.tail_messages(**kwargs):
        msg_obj = BaseMessage.from_fedmsg(topic, msg)
        if msg_obj:
            yield msg_obj

def _amq_get_messenger(conf):
    import proton
    for attr in ('amq_private_key_file', 'amq_trusted_cert_file', 'amq_cert_file'):
        val = getattr(conf, attr)
        log.debug('Checking config.%s=%s' % (attr, val))
        assert os.path.exists(val), 'config.%s=%s file does not exist' % (attr, val)

    for attr in ('amq_recv_addresses', 'amq_dest_address'):
        val = getattr(conf, attr)
        log.debug('Checking config.%s=%s' % (attr, val))
        # list values
        if isinstance(val, list) or isinstance(val, tuple):
            assert val, 'config.%s is not supposed to be empty' % attr
            # individual urls
            for v in val:
                assert v and '://' in v, 'config.%s: value "%s" doesn not seem like a valid url' % (attr, val)
        # string values
        else:
            assert val and '://' in val, 'config.%s: value "%s" doesn not seem like a valid url' % (attr, val)

    mng = proton.Messenger()
    mng.certificate=conf.amq_cert_file
    mng.private_key=conf.amq_private_key_file
    mng.trusted_certificates=conf.amq_trusted_cert_file
    mng.start()
    for url in conf.amq_recv_addresses:
        mng.subscribe(url)
        log.debug('proton.Messenger: Subscribing to address=%s' % url)
    return mng

def _amq_listen(conf, **kwargs):
    import proton
    mng = _amq_get_messenger(conf)
    msg = proton.Message()
    while True:
        mng.recv()

        while mng.incoming:
            mng.get(msg)
            msg_obj = BaseMessage.from_amq(msg.address, msg)
            if msg_obj:
                yield msg_obj

def _amq_get_dst_address(conf, topic, msg, service):
    return conf.amq_broker_dest_url

def _amq_publish(conf, topic, msg, service):
    import proton
    mng = _amq_get_messenger(conf)
    message = proton.Message()
    message.address = _amq_get_dst_address(conf, topic, msg, service)
    message.subject = topic
    message.properties['service'] = service
    message.address = conf.amq_dest_address
    message.content = json.dumps(msg, ensure_ascii=False).encode('utf8')
    mng.put(message)
    mng.send()


_messaging_backends = {
    'fedmsg': {
        'publish': _fedmsg_publish,
        'listen': _fedmsg_listen,
    },
    'amq': {
        'publish': _amq_publish,
        'listen': _amq_listen,
    },
}
