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

from mock import patch, PropertyMock
import pytest

import module_build_service.utils
from module_build_service import Modulemd, models
from module_build_service.errors import StreamAmbigous
from tests import clean_database, make_module_in_db, init_data, read_staged_data


class TestUtilsModuleStreamExpansion:
    def setup_method(self, test_method):
        clean_database(False)

    def teardown_method(self, test_method):
        clean_database()

    def _get_mmds_required_by_module_recursively(self, module_build, db_session):
        """
        Convenience wrapper around get_mmds_required_by_module_recursively
        returning the list with nsvc strings of modules returned by this the wrapped
        method.
        """
        mmd = module_build.mmd()
        module_build_service.utils.expand_mse_streams(db_session, mmd)
        modules = module_build_service.utils.get_mmds_required_by_module_recursively(
            db_session, mmd)
        nsvcs = [m.get_nsvc() for m in modules]
        return nsvcs

    def _generate_default_modules(self, db_session):
        """
        Generates gtk:1, gtk:2, foo:1 and foo:2 modules requiring the
        platform:f28 and platform:f29 modules.
        """
        platform_f28 = make_module_in_db("platform:f28:0:c10", db_session=db_session)
        platform_f29 = make_module_in_db("platform:f29:0:c11", db_session=db_session)
        f28_deps = [{
            "requires": {"platform": ["f28"]},
            "buildrequires": {"platform": ["f28"]},
        }]
        f29_deps = [{
            "requires": {"platform": ["f29"]},
            "buildrequires": {"platform": ["f29"]},
        }]
        make_module_in_db("gtk:1:0:c2", f28_deps, base_module=platform_f28, db_session=db_session)
        make_module_in_db("gtk:1:0:c3", f29_deps, base_module=platform_f29, db_session=db_session)
        make_module_in_db("gtk:2:0:c4", f28_deps, base_module=platform_f28, db_session=db_session)
        make_module_in_db("gtk:2:0:c5", f29_deps, base_module=platform_f29, db_session=db_session)
        make_module_in_db("foo:1:0:c2", f28_deps, base_module=platform_f28, db_session=db_session)
        make_module_in_db("foo:1:0:c3", f29_deps, base_module=platform_f29, db_session=db_session)
        make_module_in_db("foo:2:0:c4", f28_deps, base_module=platform_f28, db_session=db_session)
        make_module_in_db("foo:2:0:c5", f29_deps, base_module=platform_f29, db_session=db_session)
        make_module_in_db("app:1:0:c6", f29_deps, base_module=platform_f29, db_session=db_session)

    def test_generate_expanded_mmds_context(self, db_session):
        self._generate_default_modules(db_session)
        module_build = make_module_in_db(
            "app:1:0:c1", [{
                "requires": {"gtk": ["1", "2"]},
                "buildrequires": {
                    "platform": ["f28"],
                    "gtk": ["1", "2"]
                },
            }],
            db_session=db_session)
        mmds = module_build_service.utils.generate_expanded_mmds(
            db_session, module_build.mmd())
        contexts = set([mmd.get_context() for mmd in mmds])
        assert set(["e1e005fb", "ce132a1e"]) == contexts

    @pytest.mark.parametrize(
        "module_deps,stream_ambigous,expected_xmd,expected_buildrequires",
        [
            (
                [{
                    "requires": {"gtk": ["1", "2"]},
                    "buildrequires": {"platform": ["f28"], "gtk": ["1", "2"]},
                }],
                True,
                set(
                    [
                        frozenset(["platform:f28:0:c10", "gtk:2:0:c4"]),
                        frozenset(["platform:f28:0:c10", "gtk:1:0:c2"]),
                    ]
                ),
                set([frozenset(["gtk:1", "platform:f28"]), frozenset(["gtk:2", "platform:f28"])]),
            ),
            (
                [{
                    "requires": {"foo": ["1"]},
                    "buildrequires": {"platform": ["f28"], "foo": ["1"], "gtk": ["1", "2"]},
                }],
                True,
                set(
                    [
                        frozenset(["foo:1:0:c2", "gtk:1:0:c2", "platform:f28:0:c10"]),
                        frozenset(["foo:1:0:c2", "gtk:2:0:c4", "platform:f28:0:c10"]),
                    ]
                ),
                set(
                    [
                        frozenset(["foo:1", "gtk:1", "platform:f28"]),
                        frozenset(["foo:1", "gtk:2", "platform:f28"]),
                    ]
                ),
            ),
            (
                [{
                    "requires": {"gtk": ["1"], "foo": ["1"]},
                    "buildrequires": {"platform": ["f28"], "gtk": ["1"], "foo": ["1"]},
                }],
                False,
                set([frozenset(["foo:1:0:c2", "gtk:1:0:c2", "platform:f28:0:c10"])]),
                set([frozenset(["foo:1", "gtk:1", "platform:f28"])]),
            ),
            (
                [{
                    "requires": {"gtk": ["1"], "foo": ["1"]},
                    "buildrequires": {"gtk": ["1"], "foo": ["1"], "platform": ["f28"]},
                }],
                False,
                set([frozenset(["foo:1:0:c2", "gtk:1:0:c2", "platform:f28:0:c10"])]),
                set([frozenset(["foo:1", "gtk:1", "platform:f28"])]),
            ),
            (
                [{
                    "requires": {"gtk": ["-2"], "foo": ["-2"]},
                    "buildrequires": {"platform": ["f28"], "gtk": ["-2"], "foo": ["-2"]},
                }],
                True,
                set([frozenset(["foo:1:0:c2", "gtk:1:0:c2", "platform:f28:0:c10"])]),
                set([frozenset(["foo:1", "gtk:1", "platform:f28"])]),
            ),
            (
                [{
                    "requires": {"gtk": ["1"], "foo": ["1"]},
                    "buildrequires": {"platform": ["f28"], "gtk": ["1"]},
                }],
                False,
                set([frozenset(["gtk:1:0:c2", "platform:f28:0:c10"])]),
                set([frozenset(["gtk:1", "platform:f28"])]),
            ),
            (
                [{
                    "requires": {"gtk": []},
                    "buildrequires": {"platform": ["f28"], "gtk": ["1"]},
                }],
                True,
                set([frozenset(["gtk:1:0:c2", "platform:f28:0:c10"])]),
                set([frozenset(["gtk:1", "platform:f28"])]),
            ),
            (
                [{
                    "requires": {},
                    "buildrequires": {"platform": ["f29"], "app": ["1"]},
                }],
                False,
                set([frozenset(["app:1:0:c6", "platform:f29:0:c11"])]),
                set([frozenset(["app:1", "platform:f29"])]),
            ),
        ],
    )
    def test_generate_expanded_mmds_buildrequires(
        self, module_deps, stream_ambigous, expected_xmd, expected_buildrequires, db_session
    ):
        self._generate_default_modules(db_session)
        module_build = make_module_in_db("app:1:0:c1", module_deps, db_session=db_session)

        # Check that generate_expanded_mmds raises an exception if stream is ambigous
        # and also that it does not raise an exception otherwise.
        if stream_ambigous:
            with pytest.raises(StreamAmbigous):
                module_build_service.utils.generate_expanded_mmds(
                    db_session, module_build.mmd(), raise_if_stream_ambigous=True)
        else:
            module_build_service.utils.generate_expanded_mmds(
                db_session, module_build.mmd(), raise_if_stream_ambigous=True)

        # Check that if stream is ambigous and we define the stream, it does not raise
        # an exception.
        if stream_ambigous:
            default_streams = {}
            for ns in list(expected_buildrequires)[0]:
                name, stream = ns.split(":")
                default_streams[name] = stream
            module_build_service.utils.generate_expanded_mmds(
                db_session,
                module_build.mmd(),
                raise_if_stream_ambigous=True,
                default_streams=default_streams,
            )

        mmds = module_build_service.utils.generate_expanded_mmds(db_session, module_build.mmd())

        buildrequires_per_mmd_xmd = set()
        buildrequires_per_mmd_buildrequires = set()
        for mmd in mmds:
            xmd = mmd.get_xmd()
            br_nsvcs = []
            for name, detail in xmd["mbs"]["buildrequires"].items():
                br_nsvcs.append(
                    ":".join([name, detail["stream"], detail["version"], detail["context"]]))
            buildrequires_per_mmd_xmd.add(frozenset(br_nsvcs))

            assert len(mmd.get_dependencies()) == 1

            buildrequires = set()
            dep = mmd.get_dependencies()[0]
            for req_name in dep.get_buildtime_modules():
                for req_stream in dep.get_buildtime_streams(req_name):
                    buildrequires.add(":".join([req_name, req_stream]))
            buildrequires_per_mmd_buildrequires.add(frozenset(buildrequires))

        assert buildrequires_per_mmd_xmd == expected_xmd
        assert buildrequires_per_mmd_buildrequires == expected_buildrequires

    @pytest.mark.parametrize(
        "module_deps,expected",
        [
            (
                [{
                    "requires": {"gtk": ["1", "2"]},
                    "buildrequires": {"platform": [], "gtk": ["1", "2"]},
                }],
                set([frozenset(["gtk:1"]), frozenset(["gtk:2"])]),
            ),
            (
                [{
                    "requires": {"gtk": ["1", "2"]},
                    "buildrequires": {"platform": [], "gtk": ["1"]},
                }],
                set([frozenset(["gtk:1", "gtk:2"])]),
            ),
            (
                [{
                    "requires": {"gtk": ["1"], "foo": ["1"]},
                    "buildrequires": {"platform": [], "gtk": ["1"], "foo": ["1"]},
                }],
                set([frozenset(["foo:1", "gtk:1"])]),
            ),
            (
                [{
                    "requires": {"gtk": ["-2"], "foo": ["-2"]},
                    "buildrequires": {"platform": [], "gtk": ["-2"], "foo": ["-2"]},
                }],
                set([frozenset(["foo:1", "gtk:1"])]),
            ),
            (
                [{
                    "requires": {"gtk": [], "foo": []},
                    "buildrequires": {"platform": [], "gtk": ["1"], "foo": ["1"]},
                }],
                set([frozenset([])]),
            ),
        ],
    )
    def test_generate_expanded_mmds_requires(self, module_deps, expected, db_session):
        self._generate_default_modules(db_session)
        module_build = make_module_in_db("app:1:0:c1", module_deps, db_session=db_session)
        mmds = module_build_service.utils.generate_expanded_mmds(db_session, module_build.mmd())

        requires_per_mmd = set()
        for mmd in mmds:
            assert len(mmd.get_dependencies()) == 1
            mmd_requires = set()
            dep = mmd.get_dependencies()[0]
            for req_name in dep.get_runtime_modules():
                for req_stream in dep.get_runtime_streams(req_name):
                    mmd_requires.add(":".join([req_name, req_stream]))
            requires_per_mmd.add(frozenset(mmd_requires))

        assert requires_per_mmd == expected

    @pytest.mark.parametrize(
        "module_deps,expected",
        [
            (
                [{"requires": {}, "buildrequires": {"platform": [], "gtk": ["1", "2"]}}],
                [
                    "platform:f29:0:c11",
                    "gtk:2:0:c4",
                    "gtk:2:0:c5",
                    "platform:f28:0:c10",
                    "gtk:1:0:c2",
                    "gtk:1:0:c3",
                ],
            ),
            (
                [{
                    "requires": {},
                    "buildrequires": {"platform": [], "gtk": ["1"], "foo": ["1"]}
                }],
                [
                    "platform:f28:0:c10",
                    "gtk:1:0:c2",
                    "gtk:1:0:c3",
                    "foo:1:0:c2",
                    "foo:1:0:c3",
                    "platform:f29:0:c11",
                ],
            ),
            (
                [{
                    "requires": {},
                    "buildrequires": {"gtk": ["1"], "foo": ["1"], "platform": ["f28"]}
                }],
                ["platform:f28:0:c10", "gtk:1:0:c2", "foo:1:0:c2"],
            ),
            (
                [
                    {
                        "requires": {},
                        "buildrequires": {"platform": [], "gtk": ["1"], "foo": ["1"]}
                    },
                    {
                        "requires": {},
                        "buildrequires": {"platform": [], "gtk": ["2"], "foo": ["2"]},
                    }
                ],
                [
                    "foo:1:0:c2",
                    "foo:1:0:c3",
                    "foo:2:0:c4",
                    "foo:2:0:c5",
                    "platform:f28:0:c10",
                    "platform:f29:0:c11",
                    "gtk:1:0:c2",
                    "gtk:1:0:c3",
                    "gtk:2:0:c4",
                    "gtk:2:0:c5",
                ],
            ),
            (
                [{
                    "requires": {},
                    "buildrequires": {"platform": [], "gtk": ["-2"], "foo": ["-2"]},
                }],
                [
                    "foo:1:0:c2",
                    "foo:1:0:c3",
                    "platform:f29:0:c11",
                    "platform:f28:0:c10",
                    "gtk:1:0:c2",
                    "gtk:1:0:c3",
                ],
            ),
        ],
    )
    def test_get_required_modules_simple(self, module_deps, expected, db_session):
        module_build = make_module_in_db("app:1:0:c1", module_deps, db_session=db_session)
        self._generate_default_modules(db_session)
        nsvcs = self._get_mmds_required_by_module_recursively(module_build, db_session)
        assert set(nsvcs) == set(expected)

    def _generate_default_modules_recursion(self, db_session):
        """
        Generates the gtk:1 module requiring foo:1 module requiring bar:1
        and lorem:1 modules which require base:f29 module requiring
        platform:f29 module :).
        """
        base_module = make_module_in_db("platform:f29:0:c11", db_session=db_session)
        make_module_in_db(
            "gtk:1:0:c2",
            [{"requires": {"foo": ["unknown"]}, "buildrequires": {}}],
            base_module=base_module, db_session=db_session)
        make_module_in_db(
            "gtk:1:1:c2",
            [{"requires": {"foo": ["1"]}, "buildrequires": {}}],
            base_module=base_module, db_session=db_session)
        make_module_in_db(
            "foo:1:0:c2",
            [{"requires": {"bar": ["unknown"]}, "buildrequires": {}}],
            base_module=base_module, db_session=db_session)
        make_module_in_db(
            "foo:1:1:c2",
            [{"requires": {"bar": ["1"], "lorem": ["1"]}, "buildrequires": {}}],
            base_module=base_module, db_session=db_session)
        make_module_in_db(
            "bar:1:0:c2",
            [{"requires": {"base": ["unknown"]}, "buildrequires": {}}],
            base_module=base_module, db_session=db_session)
        make_module_in_db(
            "bar:1:1:c2",
            [{"requires": {"base": ["f29"]}, "buildrequires": {}}],
            base_module=base_module, db_session=db_session)
        make_module_in_db(
            "lorem:1:0:c2",
            [{"requires": {"base": ["unknown"]}, "buildrequires": {}}],
            base_module=base_module, db_session=db_session)
        make_module_in_db(
            "lorem:1:1:c2",
            [{"requires": {"base": ["f29"]}, "buildrequires": {}}],
            base_module=base_module, db_session=db_session)
        make_module_in_db(
            "base:f29:0:c3",
            [{"requires": {"platform": ["f29"]}, "buildrequires": {}}],
            base_module=base_module, db_session=db_session)

    @pytest.mark.parametrize(
        "module_deps,expected",
        [
            (
                [{
                    "requires": {},
                    "buildrequires": {"platform": [], "gtk": ["1"]},
                }],
                [
                    "foo:1:1:c2",
                    "base:f29:0:c3",
                    "platform:f29:0:c11",
                    "bar:1:1:c2",
                    "gtk:1:1:c2",
                    "lorem:1:1:c2",
                ],
            ),
            (
                [{
                    "requires": {},
                    "buildrequires": {"platform": [], "foo": ["1"]},
                }],
                ["foo:1:1:c2", "base:f29:0:c3", "platform:f29:0:c11", "bar:1:1:c2", "lorem:1:1:c2"],
            ),
        ],
    )
    def test_get_required_modules_recursion(self, module_deps, expected, db_session):
        module_build = make_module_in_db("app:1:0:c1", module_deps, db_session=db_session)
        self._generate_default_modules_recursion(db_session)
        nsvcs = self._get_mmds_required_by_module_recursively(module_build, db_session)
        assert set(nsvcs) == set(expected)

    def _generate_default_modules_modules_multiple_stream_versions(self, db_session):
        """
        Generates the gtk:1 module requiring foo:1 module requiring bar:1
        and lorem:1 modules which require base:f29 module requiring
        platform:f29 module :).
        """
        f29_dep = [{
            "requires": {"platform": ["f29"]},
            "buildrequires": {"platform": ["f29"]}
        }]

        f290000 = make_module_in_db(
            "platform:f29.0.0:0:c11", db_session=db_session, virtual_streams=["f29"])
        make_module_in_db("gtk:1:0:c2", f29_dep, base_module=f290000, db_session=db_session)

        f290100 = make_module_in_db(
            "platform:f29.1.0:0:c11", db_session=db_session, virtual_streams=["f29"])
        make_module_in_db("gtk:1:1:c2", f29_dep, base_module=f290100, db_session=db_session)
        make_module_in_db("gtk:1:2:c2", f29_dep, base_module=f290100, db_session=db_session)

        f290200 = make_module_in_db(
            "platform:f29.2.0:0:c11", db_session=db_session, virtual_streams=["f29"])
        make_module_in_db("gtk:1:3:c2", f29_dep, base_module=f290200, db_session=db_session)

    @pytest.mark.parametrize(
        "module_deps,expected",
        [
            (
                [{
                    "requires": {},
                    "buildrequires": {"platform": ["f29.1.0"], "gtk": ["1"]},
                }],
                ["platform:f29.0.0:0:c11", "gtk:1:0:c2", "gtk:1:2:c2", "platform:f29.1.0:0:c11"],
            )
        ],
    )
    def test_get_required_modules_stream_versions(self, module_deps, expected, db_session):
        module_build = make_module_in_db("app:1:0:c1", module_deps, db_session=db_session)
        self._generate_default_modules_modules_multiple_stream_versions(db_session)
        nsvcs = self._get_mmds_required_by_module_recursively(module_build, db_session)
        assert set(nsvcs) == set(expected)

    def test__get_base_module_mmds(self, db_session):
        """Ensure the correct results are returned without duplicates."""
        init_data(data_size=1, multiple_stream_versions=True)
        mmd = module_build_service.utils.load_mmd(read_staged_data("testmodule_v2.yaml"))
        deps = mmd.get_dependencies()[0]
        new_deps = Modulemd.Dependencies()
        for stream in deps.get_runtime_streams("platform"):
            new_deps.add_runtime_stream("platform", stream)
        new_deps.add_buildtime_stream("platform", "f29.1.0")
        new_deps.add_buildtime_stream("platform", "f29.2.0")
        mmd.remove_dependencies(deps)
        mmd.add_dependencies(new_deps)

        mmds = module_build_service.utils.mse.get_base_module_mmds(db_session, mmd)
        expected = set(["platform:f29.0.0", "platform:f29.1.0", "platform:f29.2.0"])
        # Verify no duplicates were returned before doing set operations
        assert len(mmds["ready"]) == len(expected)
        # Verify the expected ones were returned
        actual = set()
        for mmd_ in mmds["ready"]:
            actual.add("{}:{}".format(mmd_.get_module_name(), mmd_.get_stream_name()))
        assert actual == expected

    @pytest.mark.parametrize("virtual_streams", (None, ["f29"], ["lp29"]))
    def test__get_base_module_mmds_virtual_streams(self, virtual_streams, db_session):
        """Ensure the correct results are returned without duplicates."""
        init_data(data_size=1, multiple_stream_versions=True)
        mmd = module_build_service.utils.load_mmd(read_staged_data("testmodule_v2"))
        deps = mmd.get_dependencies()[0]
        new_deps = Modulemd.Dependencies()
        for stream in deps.get_runtime_streams("platform"):
            new_deps.add_runtime_stream("platform", stream)
        new_deps.add_buildtime_stream("platform", "f29.2.0")
        mmd.remove_dependencies(deps)
        mmd.add_dependencies(new_deps)

        make_module_in_db(
            "platform:lp29.1.1:12:c11",
            db_session=db_session, virtual_streams=virtual_streams)

        mmds = module_build_service.utils.mse.get_base_module_mmds(db_session, mmd)
        if virtual_streams == ["f29"]:
            expected = set(
                ["platform:f29.0.0", "platform:f29.1.0", "platform:f29.2.0", "platform:lp29.1.1"])
        else:
            expected = set(["platform:f29.0.0", "platform:f29.1.0", "platform:f29.2.0"])
        # Verify no duplicates were returned before doing set operations
        assert len(mmds["ready"]) == len(expected)
        # Verify the expected ones were returned
        actual = set()
        for mmd_ in mmds["ready"]:
            actual.add("{}:{}".format(mmd_.get_module_name(), mmd_.get_stream_name()))
        assert actual == expected

    @patch(
        "module_build_service.config.Config.allow_only_compatible_base_modules",
        new_callable=PropertyMock, return_value=False
    )
    def test__get_base_module_mmds_virtual_streams_only_major_versions(self, cfg, db_session):
        """Ensure the correct results are returned without duplicates."""
        init_data(data_size=1, multiple_stream_versions=["foo28", "foo29", "foo30"])

        # Mark platform:foo28 as garbage to test that it is still considered as compatible.
        platform = db_session.query(models.ModuleBuild).filter_by(
            name="platform", stream="foo28").first()
        platform.state = "garbage"
        db_session.add(platform)
        db_session.commit()

        mmd = module_build_service.utils.load_mmd(read_staged_data("testmodule_v2"))
        deps = mmd.get_dependencies()[0]
        new_deps = Modulemd.Dependencies()
        for stream in deps.get_runtime_streams("platform"):
            new_deps.add_runtime_stream("platform", stream)
        new_deps.add_buildtime_stream("platform", "foo29")
        mmd.remove_dependencies(deps)
        mmd.add_dependencies(new_deps)

        mmds = module_build_service.utils.mse.get_base_module_mmds(db_session, mmd)
        expected = {}
        expected["ready"] = set(["platform:foo29", "platform:foo30"])
        expected["garbage"] = set(["platform:foo28"])

        # Verify no duplicates were returned before doing set operations
        assert len(mmds) == len(expected)
        for k in expected.keys():
            assert len(mmds[k]) == len(expected[k])
            # Verify the expected ones were returned
            actual = set()
            for mmd_ in mmds[k]:
                actual.add("{}:{}".format(mmd_.get_module_name(), mmd_.get_stream_name()))
            assert actual == expected[k]
