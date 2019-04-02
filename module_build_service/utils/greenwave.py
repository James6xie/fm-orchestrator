# -*- coding: utf-8 -*-
# Copyright (c) 2019  Red Hat, Inc.
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
# Written by Valerij Maljulin <vmaljuli@redhat.com>


import requests
import json
from module_build_service import log, conf
from module_build_service.errors import GreenwaveError


class Greenwave(object):
    def __init__(self):
        """
        Initialize greenwave instance with config
        """
        self.url = conf.greenwave_url
        if not self.url:
            raise GreenwaveError("No Greenwave URL set")
        self._decision_context = conf.greenwave_decision_context
        if not self.decision_context:
            raise GreenwaveError("No Greenwave decision context set")
        self._subj_type = conf.greenwave_subject_type
        self._gw_timeout = conf.greenwave_timeout

    def query_decision(self, build, prod_version):
        """
        Query decision to greenwave
        :param build: build object
        :type build: module_build_service.models.ModuleBuild
        :param prod_version: The product version string used for querying WaiverDB
        :type prod_version: str
        :return: response
        :rtype: dict
        """
        payload = {
            "decision_context": self.decision_context,
            "product_version": prod_version,
            "subject_type": self.subject_type,
            "subject_identifier": build.nvr_string
        }
        url = "{0}/decision".format(self.url)
        headers = {"Content-Type": "application/json"}
        try:
            response = requests.post(
                url=url, headers=headers, data=json.dumps(payload), timeout=self.timeout)
        except requests.exceptions.Timeout:
            raise GreenwaveError("Greenwave request timed out")
        except Exception as exc:
            log.exception(str(exc))
            raise GreenwaveError("Greenwave request error")

        try:
            resp_json = response.json()
        except ValueError:
            log.debug("Greenwave response content (status {0}): {1}".format(
                response.status_code, response.text))
            raise GreenwaveError("Greenwave returned invalid JSON.")

        log.debug('Query to Greenwave result: status=%d, content="%s"',
                  (response.status_code, resp_json))

        if response.status_code == 200:
            return resp_json

        try:
            err_msg = resp_json["message"]
        except KeyError:
            err_msg = response.text
        raise GreenwaveError("Greenwave returned {0} status code. Message: {1}".format(
            response.status_code, err_msg))

    @property
    def url(self):
        return self._url

    @url.setter
    def url(self, value):
        value = value.rstrip("/")
        if value:
            self._url = value

    @property
    def decision_context(self):
        return self._decision_context

    @property
    def subject_type(self):
        return self._subj_type

    @property
    def timeout(self):
        return self._gw_timeout

    @timeout.setter
    def timeout(self, value):
        self._gw_timeout = value
