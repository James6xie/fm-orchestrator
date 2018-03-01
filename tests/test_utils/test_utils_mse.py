# Copyright (c) 2017  Red Hat, Inc.
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


from datetime import datetime
import hashlib

import gi
gi.require_version('Modulemd', '1.0')  # noqa
from gi.repository import Modulemd
from mock import patch
import pytest

import module_build_service.utils
from module_build_service import models, conf
from tests import (db, clean_database)


class TestUtilsModuleStreamExpansion:

    def setup_method(self, test_method):
        clean_database()

        def mocked_context(modulebuild_instance):
            """
            Changes the ModuleBuild.context behaviour to return
            ModuleBuild.build_context instead of computing new context hash.
            """
            return modulebuild_instance.build_context

        # For these tests, we need the ModuleBuild.context to return the well-known
        # context as we define it in test data. Therefore patch the ModuleBuild.context
        # to return ModuleBuild.build_context, which we can control.
        self.modulebuild_context_patcher = patch(
            "module_build_service.models.ModuleBuild.context", autospec=True)
        modulebuild_context = self.modulebuild_context_patcher.start()
        modulebuild_context.side_effect = mocked_context

    def teardown_method(self, test_method):
        clean_database()
        self.modulebuild_context_patcher.stop()

    def _make_module(self, nsvc, requires_list, build_requires_list):
        """
        Creates new models.ModuleBuild defined by `nsvc` string with requires
        and buildrequires set according to `requires_list` and `build_requires_list`.

        :param str nsvc: name:stream:version:context of a module.
        :param list_of_dicts requires_list: List of dictionaries defining the
            requires in the mmd requires field format.
        :param list_of_dicts build_requires_list: List of dictionaries defining the
            build_requires_list in the mmd build_requires_list field format.
        :rtype: ModuleBuild
        :return: New Module Build.
        """
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

        if not isinstance(requires_list, list):
            requires_list = [requires_list]
        if not isinstance(build_requires_list, list):
            build_requires_list = [build_requires_list]

        deps_list = []
        for requires, build_requires in zip(requires_list, build_requires_list):
            deps = Modulemd.Dependencies()
            for req_name, req_streams in requires.items():
                deps.add_requires(req_name, req_streams)
            for req_name, req_streams in build_requires.items():
                deps.add_buildrequires(req_name, req_streams)
            deps_list.append(deps)
        mmd.set_dependencies(deps_list)

        module_build = module_build_service.models.ModuleBuild()
        module_build.name = name
        module_build.stream = stream
        module_build.version = version
        module_build.state = models.BUILD_STATES['ready']
        module_build.scmurl = 'git://pkgs.stg.fedoraproject.org/modules/unused.git?#ff1ea79'
        module_build.batch = 1
        module_build.owner = 'Tom Brady'
        module_build.time_submitted = datetime(2017, 2, 15, 16, 8, 18)
        module_build.time_modified = datetime(2017, 2, 15, 16, 19, 35)
        module_build.rebuild_strategy = 'changed-and-after'
        module_build.build_context = context
        module_build.runtime_context = context
        module_build.modulemd = mmd.dumps()
        db.session.add(module_build)
        db.session.commit()

        return module_build

    def _get_modules_build_required_by_module_recursively(self, module_build):
        """
        Convenience wrapper around get_modules_build_required_by_module_recursively
        returning the list with nsvc strings of modules returned by this the wrapped
        method.
        """
        modules = module_build_service.utils.get_modules_build_required_by_module_recursively(
            db.session, module_build.mmd())
        nsvcs = [":".join([m.get_name(), m.get_stream(), str(m.get_version()), m.get_context()])
                 for m in modules]
        return nsvcs

    def _generate_default_modules(self):
        """
        Generates gtk:1, gtk:2, foo:1 and foo:2 modules requiring the
        platform:f28 and platform:f29 modules.
        """
        self._make_module("gtk:1:0:c2", {"platform": ["f28"]}, {})
        self._make_module("gtk:1:0:c3", {"platform": ["f29"]}, {})
        self._make_module("gtk:2:0:c4", {"platform": ["f28"]}, {})
        self._make_module("gtk:2:0:c5", {"platform": ["f29"]}, {})
        self._make_module("foo:1:0:c2", {"platform": ["f28"]}, {})
        self._make_module("foo:1:0:c3", {"platform": ["f29"]}, {})
        self._make_module("foo:2:0:c4", {"platform": ["f28"]}, {})
        self._make_module("foo:2:0:c5", {"platform": ["f29"]}, {})
        self._make_module("platform:f28:0:c10", {}, {})
        self._make_module("platform:f29:0:c11", {}, {})

    @pytest.mark.parametrize('requires,build_requires,expected', [
        ({}, {"gtk": ["1", "2"]},
         ['platform:f29:0:c11', 'gtk:2:0:c4', 'gtk:2:0:c5',
          'platform:f28:0:c10', 'gtk:1:0:c2', 'gtk:1:0:c3']),

        ({}, {"gtk": ["1"], "foo": ["1"]},
         ['platform:f28:0:c10', 'gtk:1:0:c2', 'gtk:1:0:c3',
          'foo:1:0:c2', 'foo:1:0:c3', 'platform:f29:0:c11']),

        ({}, {"gtk": ["1"], "foo": ["1"], "platform": ["f28"]},
         ['platform:f28:0:c10', 'gtk:1:0:c2', 'gtk:1:0:c3',
          'foo:1:0:c2', 'foo:1:0:c3', 'platform:f29:0:c11']),

        ([{}, {}], [{"gtk": ["1"], "foo": ["1"]}, {"gtk": ["2"], "foo": ["2"]}],
         ['foo:1:0:c2', 'foo:1:0:c3', 'foo:2:0:c4', 'foo:2:0:c5',
          'platform:f28:0:c10', 'platform:f29:0:c11', 'gtk:1:0:c2',
          'gtk:1:0:c3', 'gtk:2:0:c4', 'gtk:2:0:c5']),

        ({}, {"gtk": ["-2"], "foo": ["-2"]},
         ['foo:1:0:c2', 'foo:1:0:c3', 'platform:f29:0:c11',
          'platform:f28:0:c10', 'gtk:1:0:c2', 'gtk:1:0:c3']),

        ({}, {"gtk": ["-1", "1"], "foo": ["-2", "1"]},
         ['foo:1:0:c2', 'foo:1:0:c3', 'platform:f29:0:c11',
          'platform:f28:0:c10', 'gtk:1:0:c2', 'gtk:1:0:c3']),
    ])
    def test_get_required_modules_simple(self, requires, build_requires, expected):
        module_build = self._make_module("app:1:0:c1", requires, build_requires)
        self._generate_default_modules()
        nsvcs = self._get_modules_build_required_by_module_recursively(module_build)
        print nsvcs
        assert set(nsvcs) == set(expected)

    def _generate_default_modules_recursion(self):
        """
        Generates the gtk:1 module requiring foo:1 module requiring bar:1
        and lorem:1 modules which require base:f29 module requiring
        platform:f29 module :).
        """
        self._make_module("gtk:1:0:c2", {"foo": ["unknown"]}, {})
        self._make_module("gtk:1:1:c2", {"foo": ["1"]}, {})
        self._make_module("foo:1:0:c2", {"bar": ["unknown"]}, {})
        self._make_module("foo:1:1:c2", {"bar": ["1"], "lorem": ["1"]}, {})
        self._make_module("bar:1:0:c2", {"base": ["unknown"]}, {})
        self._make_module("bar:1:1:c2", {"base": ["f29"]}, {})
        self._make_module("lorem:1:0:c2", {"base": ["unknown"]}, {})
        self._make_module("lorem:1:1:c2", {"base": ["f29"]}, {})
        self._make_module("base:f29:0:c3", {"platform": ["f29"]}, {})
        self._make_module("platform:f29:0:c11", {}, {})

    @pytest.mark.parametrize('requires,build_requires,expected', [
        ({}, {"gtk": ["1"]},
         ['foo:1:1:c2', 'base:f29:0:c3', 'platform:f29:0:c11',
          'bar:1:1:c2', 'gtk:1:1:c2', 'lorem:1:1:c2']),

        ({}, {"foo": ["1"]},
         ['foo:1:1:c2', 'base:f29:0:c3', 'platform:f29:0:c11',
          'bar:1:1:c2', 'lorem:1:1:c2']),
    ])
    def test_get_required_modules_recursion(self, requires, build_requires, expected):
        module_build = self._make_module("app:1:0:c1", requires, build_requires)
        self._generate_default_modules_recursion()
        nsvcs = self._get_modules_build_required_by_module_recursively(module_build)
        print nsvcs
        assert set(nsvcs) == set(expected)
