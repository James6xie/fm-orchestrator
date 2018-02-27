# -*- coding: utf-8 -*-
#
# Copyright © 2018  Red Hat, Inc.
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
# Written by Jan Kaluža <jkaluza@redhat.com>
#            Igor Gnatenko <ignatenko@redhat.com>

import gi
gi.require_version('Modulemd', '1.0') # noqa
from gi.repository import Modulemd

import pytest
from mock import patch

from module_build_service.mmd_resolver import MMDResolver


class TestMMDResolver:

    def setup_method(self, test_method):
        self.mmd_resolver = MMDResolver()

    def teardown_method(self, test_method):
        pass

    def _make_mmd(self, nsvc, requires, build_requires):
        name, stream, version, context = nsvc.split(":")
        mmd = Modulemd.Module()
        mmd.set_mdversion(2)
        mmd.set_name(name)
        mmd.set_stream(stream)
        mmd.set_version(int(version))
        mmd.set_context(context)
        mmd.set_summary("foo")
        mmd.set_description("foo")
        licenses = Modulemd.SimpleSet()
        licenses.add("GPL")
        mmd.set_module_licenses(licenses)

        deps = Modulemd.Dependencies()
        for req_name, req_streams in requires.items():
            deps.add_requires(req_name, req_streams)
        for req_name, req_streams in build_requires.items():
            deps.add_buildrequires(req_name, req_streams)
        mmd.set_dependencies((deps, ))
        return mmd

    def test_solve_tree(self):
        mmds = []
        mmds.append(self._make_mmd("app:1:0:c1", {}, {"gtk": ["1", "2"]}))
        mmds.append(self._make_mmd("gtk:1:0:c2", {"font": ["a", "b"], "platform": ["f28"]}, {}))
        mmds.append(self._make_mmd("gtk:1:0:c3", {"font": ["a", "b"], "platform": ["f29"]}, {}))
        mmds.append(self._make_mmd("gtk:2:0:c4", {"font": ["a", "b"], "platform": ["f28"]}, {}))
        mmds.append(self._make_mmd("gtk:2:0:c5", {"font": ["a", "b"], "platform": ["f29"]}, {}))
        mmds.append(self._make_mmd("font:a:0:c6", {"platform": ["f28"]}, {}))
        mmds.append(self._make_mmd("font:a:0:c7", {"platform": ["f29"]}, {}))
        mmds.append(self._make_mmd("font:b:0:c8", {"platform": ["f28"]}, {}))
        mmds.append(self._make_mmd("font:b:0:c9", {"platform": ["f29"]}, {}))
        mmds.append(self._make_mmd("platform:f28:0:c10", {}, {}))
        mmds.append(self._make_mmd("platform:f29:0:c11", {}, {}))

        for mmd in mmds[1:]:
            self.mmd_resolver.add_available_module(mmd)
        expanded = self.mmd_resolver.solve(mmds[0])

        expected = set([
            frozenset(["gtk:1:0:c2", "platform:f28:0:c10", "font:b:0:c8"]),
            frozenset(["gtk:1:0:c3", "platform:f29:0:c11", "font:b:0:c9"]),
            frozenset(["gtk:2:0:c4", "platform:f28:0:c10", "font:b:0:c8"]),
            frozenset(["gtk:2:0:c5", "platform:f29:0:c11", "font:b:0:c9"]),
        ])

        assert expanded == expected

    def test_solve_tree_buildrequire_platform(self):
        mmds = []
        mmds.append(self._make_mmd("app:1:0:c1", {}, {"gtk": ["1", "2"], "platform": ["f28"]}))
        mmds.append(self._make_mmd("gtk:1:0:c2", {"font": ["a", "b"], "platform": ["f28"]}, {}))
        mmds.append(self._make_mmd("gtk:1:0:c3", {"font": ["a", "b"], "platform": ["f29"]}, {}))
        mmds.append(self._make_mmd("gtk:2:0:c4", {"font": ["a", "b"], "platform": ["f28"]}, {}))
        mmds.append(self._make_mmd("gtk:2:0:c5", {"font": ["a", "b"], "platform": ["f29"]}, {}))
        mmds.append(self._make_mmd("font:a:0:c6", {"platform": ["f28"]}, {}))
        mmds.append(self._make_mmd("font:a:0:c7", {"platform": ["f29"]}, {}))
        mmds.append(self._make_mmd("font:b:0:c8", {"platform": ["f28"]}, {}))
        mmds.append(self._make_mmd("font:b:0:c9", {"platform": ["f29"]}, {}))
        mmds.append(self._make_mmd("platform:f28:0:c10", {}, {}))
        mmds.append(self._make_mmd("platform:f29:0:c11", {}, {}))

        for mmd in mmds[1:]:
            self.mmd_resolver.add_available_module(mmd)
        expanded = self.mmd_resolver.solve(mmds[0])

        expected = set([
            frozenset(["gtk:1:0:c2", "platform:f28:0:c10", "font:b:0:c8"]),
            frozenset(["gtk:2:0:c4", "platform:f28:0:c10", "font:b:0:c8"]),
        ])

        assert expanded == expected

    def test_solve_tree_multiple_build_requires(self):
        mmds = []
        mmds.append(self._make_mmd("app:1:0:c1", {}, {"gtk": ["1", "2"], "foo": ["1", "2"]}))
        mmds.append(self._make_mmd("gtk:1:0:c2", {"platform": ["f28"]}, {}))
        mmds.append(self._make_mmd("gtk:1:0:c3", {"platform": ["f29"]}, {}))
        mmds.append(self._make_mmd("gtk:2:0:c4", {"platform": ["f28"]}, {}))
        mmds.append(self._make_mmd("gtk:2:0:c5", {"platform": ["f29"]}, {}))
        mmds.append(self._make_mmd("foo:1:0:c2", {"platform": ["f28"]}, {}))
        mmds.append(self._make_mmd("foo:1:0:c3", {"platform": ["f29"]}, {}))
        mmds.append(self._make_mmd("foo:2:0:c4", {"platform": ["f28"]}, {}))
        mmds.append(self._make_mmd("foo:2:0:c5", {"platform": ["f29"]}, {}))
        mmds.append(self._make_mmd("platform:f28:0:c10", {}, {}))
        mmds.append(self._make_mmd("platform:f29:0:c11", {}, {}))

        for mmd in mmds[1:]:
            self.mmd_resolver.add_available_module(mmd)
        expanded = self.mmd_resolver.solve(mmds[0])

        expected = set([
            frozenset(['foo:2:0:c5', 'gtk:1:0:c3', 'platform:f29:0:c11']),
            frozenset(['foo:2:0:c4', 'gtk:2:0:c4', 'platform:f28:0:c10']),
            frozenset(['foo:1:0:c2', 'gtk:2:0:c4', 'platform:f28:0:c10']),
            frozenset(['foo:2:0:c5', 'gtk:2:0:c5', 'platform:f29:0:c11']),
            frozenset(['foo:1:0:c3', 'gtk:2:0:c5', 'platform:f29:0:c11']),
            frozenset(['foo:1:0:c2', 'gtk:1:0:c2', 'platform:f28:0:c10']),
            frozenset(['foo:2:0:c4', 'gtk:1:0:c2', 'platform:f28:0:c10']),
            frozenset(['foo:1:0:c3', 'gtk:1:0:c3', 'platform:f29:0:c11'])
        ])

        assert expanded == expected
