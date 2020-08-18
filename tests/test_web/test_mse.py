# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
from __future__ import absolute_import

import pytest

from module_build_service.common.errors import StreamAmbigous, ValidationError
from module_build_service.scheduler.db_session import db_session
from module_build_service.web.mse import (
    expand_mse_streams, generate_expanded_mmds, get_mmds_required_by_module_recursively,
    generate_mmds_from_static_contexts
)
from tests import make_module_in_db


@pytest.mark.usefixtures("require_empty_database")
class TestModuleStreamExpansion:

    def _get_mmds_required_by_module_recursively(self, module_build, db_session):
        """
        Convenience wrapper around get_mmds_required_by_module_recursively
        returning the list with nsvc strings of modules returned by this the wrapped
        method.
        """
        mmd = module_build.mmd()
        expand_mse_streams(db_session, mmd)
        modules = get_mmds_required_by_module_recursively(db_session, mmd)
        nsvcs = [m.get_nsvc() for m in modules]
        return nsvcs

    def _generate_default_modules(self):
        """
        Generates gtk:1, gtk:2, foo:1 and foo:2 modules requiring the
        platform:f28 and platform:f29 modules.
        """
        platform_f28 = make_module_in_db("platform:f28:0:c10")
        platform_f29 = make_module_in_db("platform:f29:0:c11")
        f28_deps = [{
            "requires": {"platform": ["f28"]},
            "buildrequires": {"platform": ["f28"]},
        }]
        f29_deps = [{
            "requires": {"platform": ["f29"]},
            "buildrequires": {"platform": ["f29"]},
        }]
        make_module_in_db("gtk:1:0:c2", f28_deps, base_module=platform_f28)
        make_module_in_db("gtk:1:0:c3", f29_deps, base_module=platform_f29)
        make_module_in_db("gtk:2:0:c4", f28_deps, base_module=platform_f28)
        make_module_in_db("gtk:2:0:c5", f29_deps, base_module=platform_f29)
        make_module_in_db("foo:1:0:c2", f28_deps, base_module=platform_f28)
        make_module_in_db("foo:1:0:c3", f29_deps, base_module=platform_f29)
        make_module_in_db("foo:2:0:c4", f28_deps, base_module=platform_f28)
        make_module_in_db("foo:2:0:c5", f29_deps, base_module=platform_f29)
        make_module_in_db("app:1:0:c6", f29_deps, base_module=platform_f29)

    def test_generate_expanded_mmds_context(self):
        self._generate_default_modules()
        module_build = make_module_in_db(
            "app:1:0:c1", [{
                "requires": {"gtk": ["1", "2"]},
                "buildrequires": {
                    "platform": ["f28"],
                    "gtk": ["1", "2"]
                },
            }],
        )
        mmds = generate_expanded_mmds(db_session, module_build.mmd())
        contexts = {mmd.get_context() for mmd in mmds}
        assert {"e1e005fb", "ce132a1e"} == contexts

    @pytest.mark.parametrize(
        "module_deps,stream_ambigous,expected_xmd,expected_buildrequires",
        [
            (
                [{
                    "requires": {"gtk": ["1", "2"]},
                    "buildrequires": {"platform": ["f28"], "gtk": ["1", "2"]},
                }],
                True,
                {
                    frozenset(["platform:f28:0:c10", "gtk:2:0:c4"]),
                    frozenset(["platform:f28:0:c10", "gtk:1:0:c2"])
                },
                {frozenset(["gtk:1", "platform:f28"]), frozenset(["gtk:2", "platform:f28"])},
            ),
            (
                [{
                    "requires": {"foo": ["1"]},
                    "buildrequires": {"platform": ["f28"], "foo": ["1"], "gtk": ["1", "2"]},
                }],
                True,
                {
                    frozenset(["foo:1:0:c2", "gtk:1:0:c2", "platform:f28:0:c10"]),
                    frozenset(["foo:1:0:c2", "gtk:2:0:c4", "platform:f28:0:c10"]),
                },
                {
                    frozenset(["foo:1", "gtk:1", "platform:f28"]),
                    frozenset(["foo:1", "gtk:2", "platform:f28"]),
                },
            ),
            (
                [{
                    "requires": {"gtk": ["1"], "foo": ["1"]},
                    "buildrequires": {"platform": ["f28"], "gtk": ["1"], "foo": ["1"]},
                }],
                False,
                {frozenset(["foo:1:0:c2", "gtk:1:0:c2", "platform:f28:0:c10"])},
                {frozenset(["foo:1", "gtk:1", "platform:f28"])},
            ),
            (
                [{
                    "requires": {"gtk": ["1"], "foo": ["1"]},
                    "buildrequires": {"gtk": ["1"], "foo": ["1"], "platform": ["f28"]},
                }],
                False,
                {frozenset(["foo:1:0:c2", "gtk:1:0:c2", "platform:f28:0:c10"])},
                {frozenset(["foo:1", "gtk:1", "platform:f28"])},
            ),
            (
                [{
                    "requires": {"gtk": ["-2"], "foo": ["-2"]},
                    "buildrequires": {"platform": ["f28"], "gtk": ["-2"], "foo": ["-2"]},
                }],
                True,
                {frozenset(["foo:1:0:c2", "gtk:1:0:c2", "platform:f28:0:c10"])},
                {frozenset(["foo:1", "gtk:1", "platform:f28"])},
            ),
            (
                [{
                    "requires": {"gtk": ["1"], "foo": ["1"]},
                    "buildrequires": {"platform": ["f28"], "gtk": ["1"]},
                }],
                False,
                {frozenset(["gtk:1:0:c2", "platform:f28:0:c10"])},
                {frozenset(["gtk:1", "platform:f28"])},
            ),
            (
                [{
                    "requires": {"gtk": []},
                    "buildrequires": {"platform": ["f28"], "gtk": ["1"]},
                }],
                True,
                {frozenset(["gtk:1:0:c2", "platform:f28:0:c10"])},
                {frozenset(["gtk:1", "platform:f28"])},
            ),
            (
                [{
                    "requires": {},
                    "buildrequires": {"platform": ["f29"], "app": ["1"]},
                }],
                False,
                {frozenset(["app:1:0:c6", "platform:f29:0:c11"])},
                {frozenset(["app:1", "platform:f29"])},
            ),
        ],
    )
    def test_generate_expanded_mmds_buildrequires(
        self, module_deps, stream_ambigous, expected_xmd, expected_buildrequires
    ):
        self._generate_default_modules()
        module_build = make_module_in_db("app:1:0:c1", module_deps)

        # Check that generate_expanded_mmds raises an exception if stream is ambigous
        # and also that it does not raise an exception otherwise.
        if stream_ambigous:
            with pytest.raises(StreamAmbigous):
                generate_expanded_mmds(
                    db_session, module_build.mmd(), raise_if_stream_ambigous=True)
        else:
            generate_expanded_mmds(db_session, module_build.mmd(), raise_if_stream_ambigous=True)

        # Check that if stream is ambigous and we define the stream, it does not raise
        # an exception.
        if stream_ambigous:
            default_streams = {}
            for ns in list(expected_buildrequires)[0]:
                name, stream = ns.split(":")
                default_streams[name] = stream
            generate_expanded_mmds(
                db_session,
                module_build.mmd(),
                raise_if_stream_ambigous=True,
                default_streams=default_streams,
            )

        mmds = generate_expanded_mmds(db_session, module_build.mmd())

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
                {frozenset(["gtk:1"]), frozenset(["gtk:2"])},
            ),
            (
                [{
                    "requires": {"gtk": ["1", "2"]},
                    "buildrequires": {"platform": [], "gtk": ["1"]},
                }],
                {frozenset(["gtk:1", "gtk:2"])},
            ),
            (
                [{
                    "requires": {"gtk": ["1"], "foo": ["1"]},
                    "buildrequires": {"platform": [], "gtk": ["1"], "foo": ["1"]},
                }],
                {frozenset(["foo:1", "gtk:1"])},
            ),
            (
                [{
                    "requires": {"gtk": ["-2"], "foo": ["-2"]},
                    "buildrequires": {"platform": [], "gtk": ["-2"], "foo": ["-2"]},
                }],
                {frozenset(["foo:1", "gtk:1"])},
            ),
            (
                [{
                    "requires": {"gtk": [], "foo": []},
                    "buildrequires": {"platform": [], "gtk": ["1"], "foo": ["1"]},
                }],
                {frozenset([])},
            ),
        ],
    )
    def test_generate_expanded_mmds_requires(self, module_deps, expected):
        self._generate_default_modules()
        module_build = make_module_in_db("app:1:0:c1", module_deps)
        mmds = generate_expanded_mmds(db_session, module_build.mmd())

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
    def test_get_required_modules_simple(self, module_deps, expected):
        module_build = make_module_in_db("app:1:0:c1", module_deps)
        self._generate_default_modules()
        nsvcs = self._get_mmds_required_by_module_recursively(module_build, db_session)
        assert set(nsvcs) == set(expected)

    def _generate_default_modules_recursion(self):
        """
        Generates the gtk:1 module requiring foo:1 module requiring bar:1
        and lorem:1 modules which require base:f29 module requiring
        platform:f29 module :).
        """
        base_module = make_module_in_db("platform:f29:0:c11")
        make_module_in_db(
            "gtk:1:0:c2",
            [{"requires": {"foo": ["unknown"]}, "buildrequires": {}}],
            base_module=base_module)
        make_module_in_db(
            "gtk:1:1:c2",
            [{"requires": {"foo": ["1"]}, "buildrequires": {}}],
            base_module=base_module)
        make_module_in_db(
            "foo:1:0:c2",
            [{"requires": {"bar": ["unknown"]}, "buildrequires": {}}],
            base_module=base_module)
        make_module_in_db(
            "foo:1:1:c2",
            [{"requires": {"bar": ["1"], "lorem": ["1"]}, "buildrequires": {}}],
            base_module=base_module)
        make_module_in_db(
            "bar:1:0:c2",
            [{"requires": {"base": ["unknown"]}, "buildrequires": {}}],
            base_module=base_module)
        make_module_in_db(
            "bar:1:1:c2",
            [{"requires": {"base": ["f29"]}, "buildrequires": {}}],
            base_module=base_module)
        make_module_in_db(
            "lorem:1:0:c2",
            [{"requires": {"base": ["unknown"]}, "buildrequires": {}}],
            base_module=base_module)
        make_module_in_db(
            "lorem:1:1:c2",
            [{"requires": {"base": ["f29"]}, "buildrequires": {}}],
            base_module=base_module)
        make_module_in_db(
            "base:f29:0:c3",
            [{"requires": {"platform": ["f29"]}, "buildrequires": {}}],
            base_module=base_module)

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
    def test_get_required_modules_recursion(self, module_deps, expected):
        module_build = make_module_in_db("app:1:0:c1", module_deps)
        self._generate_default_modules_recursion()
        nsvcs = self._get_mmds_required_by_module_recursively(module_build, db_session)
        assert set(nsvcs) == set(expected)

    def _generate_default_modules_modules_multiple_stream_versions(self):
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
            "platform:f29.0.0:0:c11", virtual_streams=["f29"])
        make_module_in_db("gtk:1:0:c2", f29_dep, base_module=f290000)

        f290100 = make_module_in_db(
            "platform:f29.1.0:0:c11", virtual_streams=["f29"])
        make_module_in_db("gtk:1:1:c2", f29_dep, base_module=f290100)
        make_module_in_db("gtk:1:2:c2", f29_dep, base_module=f290100)

        f290200 = make_module_in_db(
            "platform:f29.2.0:0:c11", virtual_streams=["f29"])
        make_module_in_db("gtk:1:3:c2", f29_dep, base_module=f290200)

    @pytest.mark.parametrize(
        "module_deps,expected",
        [
            (
                [{
                    "requires": {},
                    "buildrequires": {"platform": ["f29.1.0"], "gtk": ["1"]},
                }],
                ["platform:f29.0.0:0:c11", "gtk:1:2:c2", "platform:f29.1.0:0:c11"],
            )
        ],
    )
    def test_get_required_modules_stream_versions(self, module_deps, expected):
        module_build = make_module_in_db("app:1:0:c1", module_deps)
        self._generate_default_modules_modules_multiple_stream_versions()
        nsvcs = self._get_mmds_required_by_module_recursively(module_build, db_session)
        assert set(nsvcs) == set(expected)

    def test_generate_expanded_mmds_static_context(self):
        """
        Tests if generate_expanded_mmds will not change the context of a module if provided
        with a static one.
        """
        module_deps = [{
            "requires": {"gtk": ["1"], "foo": ["1"]},
            "buildrequires": {"platform": ["f28"], "gtk": ["1"], "foo": ["1"]},
        }]
        self._generate_default_modules()
        module_build = make_module_in_db("app:1:0:static", module_deps)

        mmds = generate_expanded_mmds(db_session, module_build.mmd(), static_context=True)

        assert type(mmds) is list
        assert len(mmds) == 1

        current_context = mmds[0].get_context()

        assert current_context == "static"

    def test_generate_mmds_from_static_context(self):
        self._generate_default_modules()
        module_build = make_module_in_db(
            "app:1:0:c1",
            dependencies=[{
                "requires": {"gtk": ["1", "2"]},
                "buildrequires": {
                    "platform": ["f28"],
                    "gtk": ["1", "2"]
                }}],
            xmd={
                "mbs": {},
                "mbs_options": {
                    "contexts": {
                        "context1": {
                            "requires": {
                                "gtk": "1"
                            },
                            "buildrequires": {
                                "platform": "f28",
                                "gtk": "1",
                            }
                        },
                        "context2": {
                            "requires": {
                                "gtk": "2"
                            },
                            "buildrequires": {
                                "platform": "f28",
                                "gtk": "2",
                            },
                        }
                    }
                }
            }
        )

        mmds = generate_mmds_from_static_contexts(module_build.mmd())

        expected_contexts = ["context1", "context2"]
        expected_deps = {
            "context1": {
                "buildrequires": {
                    "platform": ["f28"],
                    "gtk": ["1"],
                },
                "requires": {
                    "gtk": ["1"],
                },
            },
            "context2": {
                "buildrequires": {
                    "platform": ["f28"],
                    "gtk": ["2"],
                },
                "requires": {
                    "gtk": ["2"],
                },
            },
        }

        assert type(mmds) is list
        assert len(mmds) == 2

        for mmd in mmds:
            current_context = mmd.get_context()
            current_xmd = mmd.get_xmd()

            assert current_context in expected_contexts
            assert "contexts" not in current_xmd

            deps = mmd.get_dependencies()

            assert len(deps) == 1

            buildrequires = deps[0].get_buildtime_modules()

            for module in buildrequires:
                current_stream = deps[0].get_buildtime_streams(module)
                assert len(current_stream) == 1
                assert expected_deps[current_context]["buildrequires"][module] == current_stream

            requires = deps[0].get_runtime_modules()

            for module in requires:
                current_stream = deps[0].get_runtime_streams(module)
                assert len(current_stream) == 1
                assert expected_deps[current_context]["requires"][module] == current_stream

    def test_generate_expanded_mmds_static_context_empty_xmd(self):
        module_build = make_module_in_db(
            "app:1:0:c1",
            xmd={})
        mmd = module_build.mmd()
        mmd.set_xmd({})
        with pytest.raises(ValidationError):
            generate_mmds_from_static_contexts(mmd)

    def test_generate_expanded_mmds_static_context_no_contexts(self):
        module_build = make_module_in_db(
            "app:1:0:c1",
            xmd={"mbs": {}, "mbs_options": {}})

        with pytest.raises(ValidationError):
            generate_mmds_from_static_contexts(module_build.mmd())

    def test_generate_expanded_mmds_static_context_missing_buildrequires(self):
        xmd = {
            "mbs": {},
            "mbs_options": {
                "contexts": {"context1": {"requires": {"gtk": ["1"]}}}
            }
        }

        module_build = make_module_in_db(
            "app:1:0:c1",
            xmd=xmd)

        with pytest.raises(ValidationError):
            generate_mmds_from_static_contexts(module_build.mmd())

    def test_generate_expanded_mmds_static_context_missing_requires(self):
        xmd = {
            "mbs": {},
            "mbs_options": {
                "contexts": {"context1": {"buildrequires": {"platform": ["f28"]}}}
            }
        }

        module_build = make_module_in_db(
            "app:1:0:c1",
            xmd=xmd)

        with pytest.raises(ValidationError):
            generate_mmds_from_static_contexts(module_build.mmd())

    def test_generate_expanded_mmds_static_context_wrong_type(self):
        xmd = {"mbs": {}, "mbs_options": {"contexts": []}}
        module_build = make_module_in_db(
            "app:1:0:c1",
            xmd=xmd)

        with pytest.raises(ValidationError):
            generate_mmds_from_static_contexts(module_build.mmd())

    def test_generate_expanded_mmds_static_context_missing_stream(self):
        xmd = {
            "mbs": {},
            "mbs_options": {
                "contexts": {
                    "context1": {
                        "buildrequires": {"platform": "f28"},
                        "requires": {"gtk": None},
                    }
                }
            }
        }

        module_build = make_module_in_db(
            "app:1:0:c1", xmd=xmd)

        with pytest.raises(ValidationError) as ex:
            generate_mmds_from_static_contexts(module_build.mmd())
            err_msg = ex.value.args[0]
            assert "gtk" in err_msg
            assert "requires" in err_msg
            assert "context1" in err_msg

    def test_generate_expanded_mmds_static_context_stream_invalid_type(self):
        xmd = {
            "mbs": {},
            "mbs_options": {
                "contexts": {
                    "context1": {
                        "buildrequires": {"platform": "f28"},
                        "requires": {"gtk": {"dict": "1"}},
                    }
                }
            }
        }

        module_build = make_module_in_db(
            "app:1:0:c1",
            xmd=xmd)

        with pytest.raises(ValidationError) as ex:
            generate_mmds_from_static_contexts(module_build.mmd())
            err_msg = ex.value.args[0]
            assert "gtk" in err_msg
            assert "requires" in err_msg
            assert "context1" in err_msg
            assert "dict" in err_msg
            assert "str" in err_msg

    def test_generate_expanded_mmds_static_context_used_mse(self):
        xmd = {
            "mbs": {},
            "mbs_options": {
                "contexts": {
                    "context1": {
                        "buildrequires": {"platform": "f28"},
                        "requires": {"gtk": "-f28"},
                    }
                }
            }
        }
        module_build = make_module_in_db(
            "app:1:0:c1",
            xmd=xmd)

        with pytest.raises(ValidationError) as ex:
            generate_mmds_from_static_contexts(module_build.mmd())
            err_msg = ex.value.args[0]
            assert "gtk" in err_msg
            assert "requires" in err_msg
            assert "context1" in err_msg
            assert "-f28" in err_msg
