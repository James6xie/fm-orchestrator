# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT

import re

from module_build_service import log
from module_build_service.scheduler import events


class MessageParser(object):
    """Base class for parsing messages received from a specific message bus

    :param topic_categories: list of known services, that MBS can handle the
        messages sent from them. For example, a value could be
        ``["buildsys", "mbs", "greenwave"]``.
    :type topic_categories: list[str]
    """

    def __init__(self, topic_categories):
        self.topic_categories = topic_categories

    def parse(self, msg):
        raise NotImplementedError()


class FedmsgMessageParser(MessageParser):

    def parse(self, msg):
        """
        Parse a received message and convert it to a consistent format

        :param dict msg: the message contents from the message bus.
        :return: a mapping representing the corresponding event.
            If the topic isn't recognized, None is returned.
        :rtype: dict or None
        """

        if "body" in msg:
            msg = msg["body"]
        topic = msg["topic"]
        categories_re = "|".join(map(re.escape, self.topic_categories))
        regex_pattern = re.compile(
            r"(?P<category>" + categories_re + r")"
            r"(?:(?:\.)(?P<object>build|repo|module|decision))?"
            r"(?:(?:\.)(?P<subobject>state|build))?"
            r"(?:\.)(?P<event>change|done|end|tag|update)$"
        )
        regex_results = re.search(regex_pattern, topic)

        if regex_results:
            category = regex_results.group("category")
            object = regex_results.group("object")
            subobject = regex_results.group("subobject")
            event = regex_results.group("event")

            msg_id = msg.get("msg_id")
            msg_inner_msg = msg.get("msg")

            # If there isn't a msg dict in msg then this message can be skipped
            if not msg_inner_msg:
                log.debug(
                    "Skipping message without any content with the " 'topic "{0}"'.format(topic))
                return None

            # Ignore all messages from the secondary koji instances.
            if category == "buildsys":
                instance = msg_inner_msg.get("instance", "primary")
                if instance != "primary":
                    log.debug("Ignoring message from %r koji hub." % instance)
                    return

                if object == "build" and subobject == "state" and event == "change":
                    build_id = msg_inner_msg.get("build_id")
                    task_id = msg_inner_msg.get("task_id")
                    build_new_state = msg_inner_msg.get("new")
                    build_name = msg_inner_msg.get("name")
                    build_version = msg_inner_msg.get("version")
                    build_release = msg_inner_msg.get("release")

                    return events.KojiBuildChange(
                        msg_id,
                        build_id,
                        task_id,
                        build_new_state,
                        build_name,
                        build_version,
                        build_release,
                    )

                if object == "repo" and subobject is None and event == "done":
                    repo_tag = msg_inner_msg.get("tag")
                    return events.KojiRepoChange(msg_id, repo_tag)

                if event == "tag":
                    tag = msg_inner_msg.get("tag")
                    name = msg_inner_msg.get("name")
                    version = msg_inner_msg.get("version")
                    release = msg_inner_msg.get("release")
                    nvr = None
                    if name and version and release:
                        nvr = "-".join((name, version, release))
                    return events.KojiTagChange(msg_id, tag, name, nvr)

            if (category == "mbs"
                    and object == "module" and subobject == "state" and event == "change"):
                return events.MBSModule(
                    msg_id,
                    msg_inner_msg.get("id"),
                    msg_inner_msg.get("state"))

            if (category == "greenwave"
                    and object == "decision" and subobject is None and event == "update"):
                return events.GreenwaveDecisionUpdate(
                    msg_id=msg_id,
                    decision_context=msg_inner_msg.get("decision_context"),
                    policies_satisfied=msg_inner_msg.get("policies_satisfied"),
                    subject_identifier=msg_inner_msg.get("subject_identifier"),
                )
