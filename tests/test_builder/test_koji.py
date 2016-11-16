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
# Written by Jan Kaluza <jkaluza@redhat.com>

import unittest
import mock

import module_build_service.messaging
import module_build_service.scheduler.handlers.repos
import module_build_service.models
import module_build_service.builder


class TestKojiBuilder(unittest.TestCase):

    def setUp(self):
        self.config = mock.Mock()
        self.config.koji_profile = 'staging'
        self.config.koji_repository_url = 'https://kojipkgs.stg.fedoraproject.org/repos'

    def test_tag_to_repo(self):
        """ Test that when a repo msg hits us and we have no match,
        that we do nothing gracefully.
        """
        repo = module_build_service.builder.GenericBuilder.tag_to_repo(
            "koji", self.config,
            "module-base-runtime-0.25-9",
            "x86_64")
        self.assertEquals(repo, "https://kojipkgs.stg.fedoraproject.org/repos"
                          "/module-base-runtime-0.25-9/latest/x86_64")
