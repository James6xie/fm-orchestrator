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
# Written by Jakub Kadlcik <jkadlcik@redhat.com>


import unittest
import mock
import module_build_service.builder


@unittest.skip("We need not yet released version of python-copr. Let's skip this for some time")
class TestCoprBuilder(unittest.TestCase):

    def setUp(self):
        self.config = mock.Mock()
        self.config.copr_config = None

    @mock.patch("copr.CoprClient.get_module_repo")
    def test_tag_to_repo(self, get_module_repo):
        # Mock the CoprClient.get_module_repo to return something, without requesting a Copr instance
        def get_module_repo_mock(owner, nvr):
            return ResponseMock({
                "output": "ok",
                "repo": "http://copr-be-instance/results/{}/{}/modules".format(owner, nvr)
            })
        get_module_repo.side_effect = get_module_repo_mock

        repo = module_build_service.builder.GenericBuilder.tag_to_repo(
            "copr", self.config, "foo-module-name-0.25-9", None)
        self.assertEquals(repo, "http://copr-be-instance/results/@copr/foo-module-name-0.25-9/modules")

    @mock.patch("copr.CoprClient.get_module_repo")
    def test_non_existing_tag_to_repo(self, get_module_repo):
        # Let's pretend that CoprClient.get_module_repo couldn't find the project on Copr instance
        get_module_repo.return_value = ResponseMock({"output": "notok", "error": "some error"})
        self.assertRaises(ValueError,
                          lambda: module_build_service.builder.GenericBuilder.tag_to_repo(
                              "copr", self.config, None, None))


class ResponseMock(object):
    def __init__(self, data):
        self._data = data

    @property
    def data(self):
        return self._data
