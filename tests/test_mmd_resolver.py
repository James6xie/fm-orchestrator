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

import collections
import pytest

from module_build_service.mmd_resolver import MMDResolver
from module_build_service import Modulemd


class TestMMDResolver:

    def setup_method(self, test_method):
        self.mmd_resolver = MMDResolver()

    def teardown_method(self, test_method):
        pass

    @staticmethod
    def _make_mmd(nsvc, requires):
        name, stream, version = nsvc.split(":", 2)
        mmd = Modulemd.Module()
        mmd.set_mdversion(2)
        mmd.set_name(name)
        mmd.set_stream(stream)
        mmd.set_summary("foo")
        mmd.set_description("foo")
        licenses = Modulemd.SimpleSet()
        licenses.add("GPL")
        mmd.set_module_licenses(licenses)

        if ":" in version:
            version, context = version.split(":")
            mmd.set_context(context)
            add_requires = Modulemd.Dependencies.add_requires
        else:
            add_requires = Modulemd.Dependencies.add_buildrequires
        mmd.set_version(int(version))

        if not isinstance(requires, list):
            requires = [requires]
        else:
            requires = requires

        deps_list = []
        for reqs in requires:
            deps = Modulemd.Dependencies()
            for req_name, req_streams in reqs.items():
                add_requires(deps, req_name, req_streams)
            deps_list.append(deps)
        mmd.set_dependencies(deps_list)

        return mmd

    @pytest.mark.parametrize(
        "deps, expected", (
            ([], "None"),
            ([{"x": []}], "module(x)"),
            ([{"x": ["1"]}], "(module(x) with module(x:1))"),
            ([{"x": ["-1"]}], "(module(x) without module(x:1))"),
            ([{"x": ["1", "2"]}], "(module(x) with (module(x:1) or module(x:2)))"),
            ([{"x": ["-1", "2"]}], "(module(x) with module(x:2))"),
            ([{"x": [], "y": []}], "(module(x) and module(y))"),
            ([{"x": []}, {"y": []}], "(module(x) or module(y))"),
        )
    )
    def test_deps2reqs(self, deps, expected):
        # Sort by keys here to avoid unordered dicts
        deps = [collections.OrderedDict(sorted(dep.items())) for dep in deps]
        reqs = self.mmd_resolver._deps2reqs(deps)
        assert str(reqs) == expected

    @pytest.mark.parametrize(
        "buildrequires, expected", (
            ({"platform": []}, [
                [["platform:f28:0:c0:x86_64"],
                 ["platform:f29:0:c0:x86_64"]],
            ]),
            ({"platform": ["f28"]}, [
                [["platform:f28:0:c0:x86_64"]],
            ]),
            ({"platform": ["-f28"]}, [
                [["platform:f29:0:c0:x86_64"]],
            ]),
            ({"gtk": [], "qt": []}, [
                [["gtk:3:0:c8:x86_64", "qt:4:0:c8:x86_64", "platform:f28:0:c0:x86_64"],
                 ["gtk:4:0:c8:x86_64", "qt:4:0:c8:x86_64", "platform:f28:0:c0:x86_64"],
                 ["gtk:3:0:c8:x86_64", "qt:5:0:c8:x86_64", "platform:f28:0:c0:x86_64"],
                 ["gtk:4:0:c8:x86_64", "qt:5:0:c8:x86_64", "platform:f28:0:c0:x86_64"]],
            ]),
            ({"gtk": [], "qt": [], "platform": []}, [
                [["gtk:3:0:c8:x86_64", "qt:4:0:c8:x86_64", "platform:f28:0:c0:x86_64"],
                 ["gtk:4:0:c8:x86_64", "qt:4:0:c8:x86_64", "platform:f28:0:c0:x86_64"],
                 ["gtk:3:0:c8:x86_64", "qt:5:0:c8:x86_64", "platform:f28:0:c0:x86_64"],
                 ["gtk:4:0:c8:x86_64", "qt:5:0:c8:x86_64", "platform:f28:0:c0:x86_64"],
                 ["gtk:3:0:c9:x86_64", "qt:4:0:c9:x86_64", "platform:f29:0:c0:x86_64"],
                 ["gtk:4:0:c9:x86_64", "qt:4:0:c9:x86_64", "platform:f29:0:c0:x86_64"],
                 ["gtk:3:0:c9:x86_64", "qt:5:0:c9:x86_64", "platform:f29:0:c0:x86_64"],
                 ["gtk:4:0:c9:x86_64", "qt:5:0:c9:x86_64", "platform:f29:0:c0:x86_64"]],
            ]),
            ([{"qt": [], "platform": ["f28"]},
              {"gtk": [], "platform": ["-f28"]}], [
                [["qt:4:0:c8:x86_64", "platform:f28:0:c0:x86_64"],
                 ["qt:5:0:c8:x86_64", "platform:f28:0:c0:x86_64"]],
                [["gtk:3:0:c9:x86_64", "platform:f29:0:c0:x86_64"],
                 ["gtk:4:0:c9:x86_64", "platform:f29:0:c0:x86_64"]],
            ]),
            ({"mess": []}, [
                [["mess:1:0:c0:x86_64", "gtk:3:0:c8:x86_64", "platform:f28:0:c0:x86_64"]],
            ]),
            ({"mess": [], "platform": []}, [
                [["mess:1:0:c0:x86_64", "gtk:3:0:c8:x86_64", "platform:f28:0:c0:x86_64"],
                 ["mess:1:0:c0:x86_64", "gtk:4:0:c9:x86_64", "platform:f29:0:c0:x86_64"]],
            ]),
        )
    )
    def test_solve(self, buildrequires, expected):
        modules = (
            ("platform:f28:0:c0", {}),
            ("platform:f29:0:c0", {}),
            ("gtk:3:0:c8", {"platform": ["f28"]}),
            ("gtk:3:0:c9", {"platform": ["f29"]}),
            ("gtk:4:0:c8", {"platform": ["f28"]}),
            ("gtk:4:0:c9", {"platform": ["f29"]}),
            ("qt:4:0:c8", {"platform": ["f28"]}),
            ("qt:4:0:c9", {"platform": ["f29"]}),
            ("qt:5:0:c8", {"platform": ["f28"]}),
            ("qt:5:0:c9", {"platform": ["f29"]}),
            ("mess:1:0:c0", [{"gtk": ["3"], "platform": ["f28"]},
                             {"gtk": ["4"], "platform": ["-f28"]}]),
        )
        for n, req in modules:
            self.mmd_resolver.add_modules(self._make_mmd(n, req))

        app = self._make_mmd("app:1:0", buildrequires)
        expanded = self.mmd_resolver.solve(app)

        expected = set(frozenset(["app:1:0:%d:src" % c] + e)
                       for c, exp in enumerate(expected)
                       for e in exp)

        assert expanded == expected
