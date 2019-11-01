# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
import mock

import module_build_service.messaging
import module_build_service.scheduler.handlers.repos
import module_build_service.models
from module_build_service.db_session import db_session
from module_build_service.models import ComponentBuild
from tests import conf, scheduler_init_data


class TestRepoDone:

    @mock.patch("module_build_service.models.ModuleBuild.from_repo_done_event")
    def test_no_match(self, from_repo_done_event):
        """ Test that when a repo msg hits us and we have no match,
        that we do nothing gracefully.
        """
        scheduler_init_data()
        from_repo_done_event.return_value = None
        msg = module_build_service.messaging.KojiRepoChange(
            "no matches for this...", "2016-some-nonexistent-build")
        module_build_service.scheduler.handlers.repos.done(config=conf, msg=msg)

    @mock.patch(
        "module_build_service.builder.KojiModuleBuilder."
        "KojiModuleBuilder.recover_orphaned_artifact",
        return_value=[],
    )
    @mock.patch(
        "module_build_service.builder.KojiModuleBuilder."
        "KojiModuleBuilder.get_average_build_time",
        return_value=0.0,
    )
    @mock.patch(
        "module_build_service.builder.KojiModuleBuilder."
        "KojiModuleBuilder.list_tasks_for_components",
        return_value=[],
    )
    @mock.patch(
        "module_build_service.builder.KojiModuleBuilder.KojiModuleBuilder.buildroot_ready",
        return_value=True,
    )
    @mock.patch("module_build_service.builder.KojiModuleBuilder.KojiModuleBuilder.get_session")
    @mock.patch("module_build_service.builder.KojiModuleBuilder.KojiModuleBuilder.build")
    @mock.patch(
        "module_build_service.builder.KojiModuleBuilder.KojiModuleBuilder.buildroot_connect"
    )
    def test_a_single_match(
        self, connect, build_fn, get_session, ready, list_tasks_fn, mock_gabt, mock_uea
    ):
        """ Test that when a repo msg hits us and we have a single match.
        """
        scheduler_init_data()
        get_session.return_value = mock.Mock(), "development"
        build_fn.return_value = 1234, 1, "", None

        msg = module_build_service.messaging.KojiRepoChange(
            "some_msg_id", "module-testmodule-master-20170109091357-7c29193d-build")
        module_build_service.scheduler.handlers.repos.done(config=conf, msg=msg)
        build_fn.assert_called_once_with(
            artifact_name="tangerine",
            source=(
                "https://src.fedoraproject.org/rpms/tangerine?"
                "#fbed359411a1baa08d4a88e0d12d426fbf8f602c"
            ),
        )

    @mock.patch("module_build_service.builder.KojiModuleBuilder.KojiModuleBuilder.finalize")
    @mock.patch(
        "module_build_service.builder.KojiModuleBuilder."
        "KojiModuleBuilder.recover_orphaned_artifact",
        return_value=[],
    )
    @mock.patch(
        "module_build_service.builder.KojiModuleBuilder."
        "KojiModuleBuilder.get_average_build_time",
        return_value=0.0,
    )
    @mock.patch(
        "module_build_service.builder.KojiModuleBuilder."
        "KojiModuleBuilder.list_tasks_for_components",
        return_value=[],
    )
    @mock.patch(
        "module_build_service.builder.KojiModuleBuilder.KojiModuleBuilder.buildroot_ready",
        return_value=True,
    )
    @mock.patch("module_build_service.builder.KojiModuleBuilder.KojiModuleBuilder.get_session")
    @mock.patch("module_build_service.builder.KojiModuleBuilder.KojiModuleBuilder.build")
    @mock.patch(
        "module_build_service.builder.KojiModuleBuilder.KojiModuleBuilder.buildroot_connect"
    )
    def test_a_single_match_finalize(
        self, connect, build_fn, get_session, ready, list_tasks_fn, mock_gabt, mock_uea, finalizer
    ):
        """ Test that when a repo msg hits us and we have a single match.
        """
        scheduler_init_data(tangerine_state=1)
        get_session.return_value = mock.Mock(), "development"
        build_fn.return_value = 1234, 1, "", None

        # Ensure the time_completed is None, so we can test it is set to
        # some date once the build is finalized.
        module_build = module_build_service.models.ModuleBuild.get_by_id(db_session, 2)
        module_build.time_completed = None
        db_session.commit()

        def mocked_finalizer(succeeded=None):
            # Check that the time_completed is set in the time when
            # finalizer is called.
            assert succeeded is True
            module_build = module_build_service.models.ModuleBuild.get_by_id(db_session, 2)
            assert module_build.time_completed is not None

        finalizer.side_effect = mocked_finalizer

        msg = module_build_service.messaging.KojiRepoChange(
            "some_msg_id", "module-testmodule-master-20170109091357-7c29193d-build")
        module_build_service.scheduler.handlers.repos.done(config=conf, msg=msg)

        finalizer.assert_called_once()

    @mock.patch(
        "module_build_service.builder.KojiModuleBuilder."
        "KojiModuleBuilder.recover_orphaned_artifact",
        return_value=[],
    )
    @mock.patch(
        "module_build_service.builder.KojiModuleBuilder."
        "KojiModuleBuilder.get_average_build_time",
        return_value=0.0,
    )
    @mock.patch(
        "module_build_service.builder.KojiModuleBuilder."
        "KojiModuleBuilder.list_tasks_for_components",
        return_value=[],
    )
    @mock.patch(
        "module_build_service.builder.KojiModuleBuilder.KojiModuleBuilder.buildroot_ready",
        return_value=True,
    )
    @mock.patch("module_build_service.builder.KojiModuleBuilder.KojiModuleBuilder.get_session")
    @mock.patch("module_build_service.builder.KojiModuleBuilder.KojiModuleBuilder.build")
    @mock.patch(
        "module_build_service.builder.KojiModuleBuilder.KojiModuleBuilder.buildroot_connect"
    )
    def test_a_single_match_build_fail(
        self, connect, build_fn, config, ready, list_tasks_fn, mock_gabt, mock_uea
    ):
        """ Test that when a KojiModuleBuilder.build fails, the build is
        marked as failed with proper state_reason.
        """
        scheduler_init_data()
        config.return_value = mock.Mock(), "development"
        build_fn.return_value = None, 4, "Failed to submit artifact tangerine to Koji", None

        msg = module_build_service.messaging.KojiRepoChange(
            "some_msg_id", "module-testmodule-master-20170109091357-7c29193d-build")
        module_build_service.scheduler.handlers.repos.done(config=conf, msg=msg)
        build_fn.assert_called_once_with(
            artifact_name="tangerine",
            source=(
                "https://src.fedoraproject.org/rpms/tangerine?"
                "#fbed359411a1baa08d4a88e0d12d426fbf8f602c"
            ),
        )
        component_build = db_session.query(
            module_build_service.models.ComponentBuild
        ).filter_by(package="tangerine").one()
        assert component_build.state_reason == "Failed to submit artifact tangerine to Koji"

    @mock.patch("module_build_service.scheduler.handlers.repos.log.info")
    def test_erroneous_regen_repo_received(self, mock_log_info):
        """ Test that when an unexpected KojiRepoRegen message is received, the module doesn't
        complete or go to the next build batch.
        """
        scheduler_init_data(1)

        component_build = db_session.query(ComponentBuild).filter_by(package="tangerine").one()
        component_build.tagged = False
        db_session.commit()

        msg = module_build_service.messaging.KojiRepoChange(
            "some_msg_id", "module-testmodule-master-20170109091357-7c29193d-build")

        module_build_service.scheduler.handlers.repos.done(config=conf, msg=msg)

        mock_log_info.assert_called_with(
            "Ignoring repo regen, because not all components are tagged."
        )
        module_build = module_build_service.models.ModuleBuild.get_by_id(db_session, 2)
        # Make sure the module build didn't transition since all the components weren't tagged
        assert module_build.state == module_build_service.models.BUILD_STATES["build"]

    @mock.patch(
        "module_build_service.builder.KojiModuleBuilder."
        "KojiModuleBuilder.list_tasks_for_components",
        return_value=[],
    )
    @mock.patch(
        "module_build_service.builder.KojiModuleBuilder.KojiModuleBuilder.buildroot_ready",
        return_value=True,
    )
    @mock.patch("module_build_service.builder.KojiModuleBuilder.KojiModuleBuilder.get_session")
    @mock.patch("module_build_service.builder.KojiModuleBuilder.KojiModuleBuilder.build")
    @mock.patch(
        "module_build_service.builder.KojiModuleBuilder.KojiModuleBuilder.buildroot_connect"
    )
    @mock.patch(
        "module_build_service.builder.GenericBuilder.default_buildroot_groups",
        return_value={"build": [], "srpm-build": []},
    )
    def test_failed_component_build(
        self, dbg, connect, build_fn, config, ready, list_tasks_fn
    ):
        """ Test that when a KojiModuleBuilder.build fails, the build is
        marked as failed with proper state_reason.
        """
        scheduler_init_data(3)
        config.return_value = mock.Mock(), "development"
        build_fn.return_value = None, 4, "Failed to submit artifact x to Koji", None

        msg = module_build_service.messaging.KojiRepoChange(
            "some_msg_id", "module-testmodule-master-20170109091357-7c29193d-build")
        module_build_service.scheduler.handlers.repos.done(config=conf, msg=msg)

        module_build = module_build_service.models.ModuleBuild.get_by_id(db_session, 2)
        assert module_build.state == module_build_service.models.BUILD_STATES["failed"]
