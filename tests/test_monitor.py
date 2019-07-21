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
# Written by Filip Valder <fvalder@redhat.com>

import os
import pytest
import requests
import mock
import module_build_service.config as mbs_config
import module_build_service.monitor
from module_build_service import models
from conf.config import TestConfiguration

from six.moves import reload_module
from tests import app, init_data, make_module_in_db

num_of_metrics = 18


class TestViews:
    def setup_method(self, test_method):
        self.client = app.test_client()
        init_data(2)

    def test_metrics(self):
        rv = self.client.get("/module-build-service/1/monitor/metrics")

        count = len([
            l for l in rv.get_data(as_text=True).splitlines()
            if (l.startswith("# TYPE") and "_created " not in l)
        ])
        assert count == num_of_metrics


def test_standalone_metrics_server_disabled_by_default():
    with pytest.raises(requests.exceptions.ConnectionError):
        requests.get("http://127.0.0.1:10040/metrics")


def test_standalone_metrics_server():
    os.environ["MONITOR_STANDALONE_METRICS_SERVER_ENABLE"] = "true"
    reload_module(module_build_service.monitor)

    r = requests.get("http://127.0.0.1:10040/metrics")
    count = len([
        l for l in r.text.splitlines()
        if (l.startswith("# TYPE") and "_created " not in l)
    ])
    assert count == num_of_metrics


@mock.patch("module_build_service.monitor.builder_failed_counter.labels")
@mock.patch("module_build_service.monitor.builder_success_counter.inc")
def test_monitor_state_changing_success(succ_cnt, failed_cnt, db_session):
    conf = mbs_config.Config(TestConfiguration)
    b = make_module_in_db(
        "pkg:0.1:1:c1", [{
            "requires": {"platform": ["el8"]},
            "buildrequires": {"platform": ["el8"]},
        }],
        db_session=db_session)
    b.transition(db_session, conf, models.BUILD_STATES["wait"])
    b.transition(db_session, conf, models.BUILD_STATES["build"])
    b.transition(db_session, conf, models.BUILD_STATES["done"])
    db_session.commit()
    succ_cnt.assert_called_once()
    failed_cnt.assert_not_called()


@mock.patch("module_build_service.monitor.builder_failed_counter.labels")
@mock.patch("module_build_service.monitor.builder_success_counter.inc")
def test_monitor_state_changing_failure(succ_cnt, failed_cnt, db_session):
    failure_type = "user"
    conf = mbs_config.Config(TestConfiguration)
    b = make_module_in_db(
        "pkg:0.1:1:c1", [{
            "requires": {"platform": ["el8"]},
            "buildrequires": {"platform": ["el8"]},
        }],
        db_session=db_session)
    b.transition(db_session, conf, models.BUILD_STATES["wait"])
    b.transition(db_session, conf, models.BUILD_STATES["build"])
    b.transition(db_session, conf, models.BUILD_STATES["failed"], failure_type=failure_type)
    db_session.commit()
    succ_cnt.assert_not_called()
    failed_cnt.assert_called_once_with(reason=failure_type)
