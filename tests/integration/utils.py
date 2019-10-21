# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT


class MBS:

    def __init__(self, api):
        self._api = api


class Git:

    def __init__(self, url):
        self._url = url


class Koji:

    def __init__(self, server, topurl):
        self._server = server
        self._topurl = topurl
