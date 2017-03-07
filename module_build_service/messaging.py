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
import kobo.rpmlib
try:
    from inspect import signature
except ImportError:
    from funcsigs import signature

from module_build_service import log, conf


class BaseMessage(object):
    def __init__(self, msg_id):
        """
        A base class to abstract messages from different backends
        :param msg_id: the id of the msg (e.g. 2016-SomeGUID)
        """
        self.msg_id = msg_id

        # Moksha calls `consumer.validate` on messages that it receives, and
        # even though we have validation turned off in the config there's still
        # a step that tries to access `msg['body']`, `msg['topic']` and
        # `msg.get('topic')`.
        # These are here just so that the `validate` method won't raise an
        # exception when we push our fake messages through.
        # Note that, our fake message pushing has worked for a while... but the
        # *latest* version of fedmsg has some code that exercises the bug.  I
        # didn't hit this until I went to test in jenkins.
        self.body = {}
        self.topic = None

    def __repr__(self):
        init_sig = signature(self.__init__)

        args_strs = (
            "{}={!r}".format(name, getattr(self, name))
            if param.default != param.empty
            else repr(getattr(self, name))
            for name, param in init_sig.parameters.items())

        return "{}({})".format(type(self).__name__, ', '.join(args_strs))

    def __getitem__(self, key):
        """ Used to trick moksha into thinking we are a dict. """
        return getattr(self, key)

    def __setitem__(self, key, value):
        """ Used to trick moksha into thinking we are a dict. """
        return setattr(self, key, value)

    def get(self, key, value=None):
        """ Used to trick moksha into thinking we are a dict. """
        return getattr(self, key, value)

    def __json__(self):
        return dict(msg_id=self.msg_id, topic=self.topic, body=self.body)

    @staticmethod
    def from_amq(topic, msg):
        msg_obj = None

        if not hasattr(msg, 'properties'):
            return None  # Unrelated message not identifying service origin
        properties = json.loads(msg.properties, encoding='utf8')
        service = properties.get('service')

        if service not in _messaging_backends['amq']['services']:
            log.debug('Skipping msg due service=%s which is not related (msg=%r): ' % (service, msg))
            return None

        # This probably appies only for brew
        # Also wouldn't be easier to use properties?
        if service == 'koji':
            content = json.loads(msg.body, encoding='utf8')['content']
            log.debug("Found koji related msg: %s" % msg)
            method = content['info']['method']
            msg_type = content['info']['type']

            if method == 'newRepo':
                attr = content['attribute']
                state = content['info']['new']
                if attr == "state" and state == "CLOSED":
                    repo_tag = content['info']['request']
                    assert len(repo_tag) == 1
                    msg_obj = KojiRepoChange(msg.id, repo_tag[0])

            elif method == 'build' and msg_type == 'TaskStateChange':
                attr = content['attribute']
                if attr == "state":
                    build_id = content['info']['id']
                    # TODO: Someone with AMQ knowledge should check if
                    # info.id is build id or task_id here. For now I presume
                    # it is task_id.
                    task_id = content['info']['id']
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
                        msg.id, build_id, task_id, build_state, build_name,
                        build_version, build_release)

        elif service == 'mbs':
            log.debug("Found mbs related msg: %s" % msg)
            body = json.loads(msg.body, encoding='utf8')
            if topic == 'module.state.change':
                msg_obj = MBSModule(
                    msg.id, body['id'], body['state'])

        if msg_obj:
            return msg_obj

        log.debug('Skipping unrecognized message: %s' % msg)
        return None

    @staticmethod
    def from_fedmsg(topic, msg):
        """
        Takes a fedmsg topic and message and converts it to a message object
        :param topic: the topic of the fedmsg message
        :param msg: the message contents from the fedmsg message
        :return: an object of BaseMessage descent if the message is a type
        that the app looks for, otherwise None is returned
        """
        topic_categories = _messaging_backends['fedmsg']['services']
        categories_re = '|'.join(map(re.escape, topic_categories))
        regex_pattern = re.compile(
            (r'(?P<category>' + categories_re + r')(?:\.)'
             r'(?P<object>build|repo|module)(?:(?:\.)'
             r'(?P<subobject>state|build))?(?:\.)(?P<event>change|done|end)$'))
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

            # Ignore all messages from the secondary koji instances.
            if category == 'buildsys':
                instance = msg_inner_msg.get('instance', 'primary')
                if instance != 'primary':
                    log.debug("Ignoring message from %r koji hub." % instance)
                    return

            if category == 'buildsys' and object == 'build' and \
                    subobject == 'state' and event == 'change':
                build_id = msg_inner_msg.get('build_id')
                task_id = msg_inner_msg.get('task_id')
                build_new_state = msg_inner_msg.get('new')
                build_name = msg_inner_msg.get('name')
                build_version = msg_inner_msg.get('version')
                build_release = msg_inner_msg.get('release')

                if task_id is None:
                    log.debug("Saw a koji build change with no task_id.")
                    return

                msg_obj = KojiBuildChange(
                    msg_id, build_id, task_id, build_new_state, build_name,
                    build_version, build_release)

            elif category == 'buildsys' and object == 'repo' and \
                    subobject is None and event == 'done':
                repo_tag = msg_inner_msg.get('tag')
                msg_obj = KojiRepoChange(msg_id, repo_tag)

            elif category == 'mbs' and object == 'module' and \
                    subobject == 'state' and event == 'change':
                msg_obj = MBSModule(
                    msg_id, msg_inner_msg.get('id'), msg_inner_msg.get('state'))

            elif conf.system == category == 'copr' and object == 'build':
                build = msg_inner_msg.get('build')
                status = msg_inner_msg.get('status')
                pkg = msg_inner_msg.get('pkg')
                what = msg_inner_msg.get('what')
                msg_obj = CoprBuildEnd(msg_id, build, status, pkg, what)

            # If the message matched the regex and is important to the app,
            # it will be returned
            if msg_obj:
                return msg_obj

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
    :param module_build_id: the optional id of the module_build in the database
    :param state_reason: the optional reason as to why the state changed
    """
    def __init__(self, msg_id, build_id, task_id, build_new_state, build_name,
                 build_version, build_release, module_build_id=None,
                 state_reason=None):
        if task_id is None:
            raise ValueError("KojiBuildChange with a null task_id is invalid.")
        super(KojiBuildChange, self).__init__(msg_id)
        self.build_id = build_id
        self.task_id = task_id
        self.build_new_state = build_new_state
        self.build_name = build_name
        self.build_version = build_version
        self.build_release = build_release
        self.module_build_id = module_build_id
        self.state_reason = state_reason


class KojiRepoChange(BaseMessage):
    """ A class that inherits from BaseMessage to provide a message
    object for a repo's info (in fedmsg this replaces the msg dictionary)
    :param msg_id: the id of the msg (e.g. 2016-SomeGUID)
    :param repo_tag: the repo's tag (e.g. SHADOWBUILD-f25-build)
    """
    def __init__(self, msg_id, repo_tag):
        super(KojiRepoChange, self).__init__(msg_id)
        self.repo_tag = repo_tag


class CoprBuildEnd(object):
    """ A wrapper class that transforms copr message attributes
    to a KojiBuildChange message object
    :param msg_id: the id of the msg (e.g. 2016-SomeGUID)
    :param build_id: the id of the build (e.g. 264382)
    :param status: the new build state
    (see http://copr-backend.readthedocs.io/package/constants.html#backend.constants.BuildStatus )
    :param pkg: the full name of what is being built
    (e.g. mutt-kz-1.5.23.1-1.20150203.git.c8504a8a.fc21)
    :param state_reason: the optional reason as to why the state changed
    """
    def __new__(cls, msg_id, build_id, status, pkg, what=None):
        nvr = kobo.rpmlib.parse_nvra(pkg)
        return KojiBuildChange(
            msg_id=msg_id,
            build_id=build_id,
            task_id=build_id,
            build_new_state=status,
            build_name=nvr["name"],
            build_version=nvr["version"],
            build_release=".".join(s for s in [nvr["release"], nvr["epoch"], nvr["arch"]] if s),
            state_reason=what,
        )


class MBSModule(BaseMessage):
    """ A class that inherits from BaseMessage to provide a message
    object for a module event generated by module_build_service
    :param msg_id: the id of the msg (e.g. 2016-SomeGUID)
    :param module_build_id: the id of the module build
    :param module_build_state: the state of the module build
    """
    def __init__(self, msg_id, module_build_id, module_build_state):
        super(MBSModule, self).__init__(msg_id)
        self.module_build_id = module_build_id
        self.module_build_state = module_build_state


def publish(topic, msg, conf, service):
    """
    Publish a single message to a given backend, and return
    :param topic: the topic of the message (e.g. module.state.change)
    :param msg: the message contents of the message (typically JSON)
    :param conf: a Config object from the class in config.py
    :param service: the system that is publishing the message (e.g. mbs)
    :return:
    """
    try:
        handler = _messaging_backends[conf.messaging]['publish']
    except KeyError:
        raise KeyError("No messaging backend found for %r" % conf.messaging)
    return handler(topic, msg, conf, service)


def _fedmsg_publish(topic, msg, conf, service):
    # fedmsg doesn't really need access to conf, however other backends do
    import fedmsg
    return fedmsg.publish(topic, msg=msg, modname=service)


# A counter used for in-memory messages.
_in_memory_msg_id = 0
_initial_messages = []


def _in_memory_publish(topic, msg, conf, service):
    """ Puts the message into the in memory work queue. """
    # Increment the message ID.
    global _in_memory_msg_id
    _in_memory_msg_id += 1

    # Create fake fedmsg from the message so we can reuse
    # the BaseMessage.from_fedmsg code to get the particular BaseMessage
    # class instance.
    wrapped_msg = BaseMessage.from_fedmsg(
        service + "." + topic,
        {"msg_id": str(_in_memory_msg_id), "msg": msg},
    )

    # Put the message to queue.
    from module_build_service.scheduler.consumer import work_queue_put
    try:
        work_queue_put(wrapped_msg)
    except ValueError as e:
        log.warn("No MBSConsumer found.  Shutting down?  %r" % e)
    except AttributeError as e:
        # In the event that `moksha.hub._hub` hasn't yet been initialized, we
        # need to store messages on the side until it becomes available.
        # As a last-ditch effort, try to hang initial messages in the config.
        log.warn("Hub not initialized.  Queueing on the side.")
        _initial_messages.append(wrapped_msg)


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
        if isinstance(val, (list, tuple)):
            assert val, 'config.%s is not supposed to be empty' % attr
            # individual urls
            for v in val:
                assert v and '://' in v, 'config.%s: value "%s" does not seem like a valid url' % (attr, val)
        # string values
        else:
            assert val and '://' in val, 'config.%s: value "%s" does not seem like a valid url' % (attr, val)

    msngr = proton.Messenger()
    msngr.certificate = conf.amq_cert_file
    msngr.private_key = conf.amq_private_key_file
    msngr.trusted_certificates = conf.amq_trusted_cert_file
    msngr.start()
    for url in conf.amq_recv_addresses:
        msngr.subscribe(url)
        log.debug('proton.Messenger: Subscribing to address=%s' % url)
    return msngr


def _amq_publish(topic, msg, conf, service):
    import proton
    msngr = _amq_get_messenger(conf)
    message = proton.Message()
    message.address = conf.amq_dest_address
    message.subject = topic
    message.properties['service'] = service
    message.content = json.dumps(msg, ensure_ascii=False).encode('utf8')
    msngr.put(message)
    msngr.send()


_messaging_backends = {
    'fedmsg': {
        'publish': _fedmsg_publish,
        'services': ['buildsys', 'mbs', 'copr']
    },
    'amq': {
        'publish': _amq_publish,
        'services': ['koji', 'mbs']
    },
    'in_memory': {
        'publish': _in_memory_publish,
        'services': []
    }
}
