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


import json
from mock import patch, Mock
import module_build_service.utils.greenwave
from tests import make_module


class TestGreenwaveQuery():
    @patch("module_build_service.utils.greenwave.requests")
    def test_greenwave_decision(self, mock_requests):
        resp_status = 200
        resp_content = {
            "applicable_policies": ["osci_compose_modules"],
            "policies_satisfied": True,
            "satisfied_requirements": [
                {
                    "result_id": 7336633,
                    "testcase": "test-ci.test-module.tier1",
                    "type": "test-result-passed"
                },
                {
                    "result_id": 7336650,
                    "testcase": "test-ci.test-module.tier2",
                    "type": "test-result-passed"
                }
            ],
            "summary": "All required tests passed",
            "unsatisfied_requirements": []
        }
        response = Mock()
        response.json.return_value = resp_content
        response.status_code = resp_status
        mock_requests.post.return_value = response

        fake_build = make_module("pkg:0.1:1:c1", requires_list={"platform": "el8"})

        gw = module_build_service.utils.greenwave.Greenwave()
        got_response = gw.query_decision(fake_build, prod_version="xxxx-8")

        assert got_response == resp_content
        assert json.loads(mock_requests.post.call_args_list[0][1]["data"]) == {
            "decision_context": "test_dec_context",
            "product_version": "xxxx-8", "subject_type": "some-module",
            "subject_identifier": "pkg-0.1-1.c1"}
        assert mock_requests.post.call_args_list[0][1]["headers"] == {
            "Content-Type": "application/json"}
        assert mock_requests.post.call_args_list[0][1]["url"] == \
            "https://greenwave.example.local/api/v1.0/decision"
