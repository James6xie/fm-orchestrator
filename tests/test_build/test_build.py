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
import koji
import vcr
import os
from os import path, mkdir
from os.path import dirname
from shutil import copyfile
from datetime import datetime, timedelta

from nose.tools import timed

import module_build_service.messaging
import module_build_service.scheduler.handlers.repos
import module_build_service.utils
from module_build_service.errors import Forbidden
from module_build_service import db, models, conf, build_logs

from mock import patch, PropertyMock, Mock

from tests import app, test_reuse_component_init_data, clean_database
import json
import itertools

from module_build_service.builder.base import GenericBuilder
from module_build_service.builder.KojiModuleBuilder import KojiModuleBuilder
import module_build_service.scheduler.consumer
from module_build_service.messaging import MBSModule

base_dir = dirname(dirname(__file__))
cassette_dir = base_dir + '/vcr-request-data/'

user = ('Homer J. Simpson', set(['packager']))


class FakeSCM(object):
    def __init__(self, mocked_scm, name, mmd_filename, commit=None):
        self.mocked_scm = mocked_scm
        self.name = name
        self.commit = commit
        self.mmd_filename = mmd_filename
        self.sourcedir = None

        self.mocked_scm.return_value.checkout = self.checkout
        self.mocked_scm.return_value.name = self.name
        self.mocked_scm.return_value.branch = 'master'
        self.mocked_scm.return_value.get_latest = self.get_latest
        self.mocked_scm.return_value.commit = self.commit
        self.mocked_scm.return_value.repository_root = "git://pkgs.stg.fedoraproject.org/modules/"
        self.mocked_scm.return_value.sourcedir = self.sourcedir
        self.mocked_scm.return_value.get_module_yaml = self.get_module_yaml

    def checkout(self, temp_dir):
        self.sourcedir = path.join(temp_dir, self.name)
        mkdir(self.sourcedir)
        base_dir = path.abspath(path.dirname(__file__))
        copyfile(path.join(base_dir, '..', 'staged_data', self.mmd_filename),
                 self.get_module_yaml())

        return self.sourcedir

    def get_latest(self, ref='master'):
        return ref

    def get_module_yaml(self):
        return path.join(self.sourcedir, self.name + ".yaml")


def _on_build_cb(cls, artifact_name, source):
    # Tag the build in the -build tag
    cls._send_tag(artifact_name)
    if not artifact_name.startswith("module-build-macros"):
        # Tag the build in the final tag
        cls._send_tag(artifact_name, build=False)


class FakeModuleBuilder(GenericBuilder):
    """
    Fake module builder which succeeds for every build.
    """

    backend = "test"
    # Global build_id/task_id we increment when new build is executed.
    _build_id = 1

    BUILD_STATE = "COMPLETE"
    INSTANT_COMPLETE = False
    DEFAULT_GROUPS = None

    on_build_cb = _on_build_cb
    on_cancel_cb = None
    on_buildroot_add_artifacts_cb = None
    on_tag_artifacts_cb = None

    @module_build_service.utils.validate_koji_tag('tag_name')
    def __init__(self, owner, module, config, tag_name, components):
        self.module_str = module
        self.tag_name = tag_name
        self.config = config
        self.on_build_cb = _on_build_cb

    @classmethod
    def reset(cls):
        FakeModuleBuilder.BUILD_STATE = "COMPLETE"
        FakeModuleBuilder.INSTANT_COMPLETE = False
        FakeModuleBuilder.on_build_cb = _on_build_cb
        FakeModuleBuilder.on_cancel_cb = None
        FakeModuleBuilder.on_buildroot_add_artifacts_cb = None
        FakeModuleBuilder.on_tag_artifacts_cb = None
        FakeModuleBuilder.DEFAULT_GROUPS = None
        FakeModuleBuilder.backend = 'test'

    def buildroot_connect(self, groups):
        default_groups = FakeModuleBuilder.DEFAULT_GROUPS or {
            'srpm-build':
                set(['shadow-utils', 'fedora-release', 'redhat-rpm-config',
                     'rpm-build', 'fedpkg-minimal', 'gnupg2', 'bash']),
            'build':
                set(['unzip', 'fedora-release', 'tar', 'cpio', 'gawk',
                     'gcc', 'xz', 'sed', 'findutils', 'util-linux', 'bash',
                     'info', 'bzip2', 'grep', 'redhat-rpm-config',
                     'diffutils', 'make', 'patch', 'shadow-utils',
                     'coreutils', 'which', 'rpm-build', 'gzip', 'gcc-c++'])}
        if groups != default_groups:
            raise ValueError("Wrong groups in FakeModuleBuilder.buildroot_connect()")

    def buildroot_prep(self):
        pass

    def buildroot_resume(self):
        pass

    def buildroot_ready(self, artifacts=None):
        return True

    def buildroot_add_dependency(self, dependencies):
        pass

    def buildroot_add_artifacts(self, artifacts, install=False):
        if FakeModuleBuilder.on_buildroot_add_artifacts_cb:
            FakeModuleBuilder.on_buildroot_add_artifacts_cb(self, artifacts, install)
        self._send_repo_done()

    def buildroot_add_repos(self, dependencies):
        pass

    def tag_artifacts(self, artifacts):
        if FakeModuleBuilder.on_tag_artifacts_cb:
            FakeModuleBuilder.on_tag_artifacts_cb(self, artifacts)
        for nvr in artifacts:
            # tag_artifacts received a list of NVRs, but the tag message expects the
            # component name
            artifact = models.ComponentBuild.query.filter_by(nvr=nvr).one().package
            self._send_tag(artifact)
            if not artifact.startswith('module-build-macros'):
                self._send_tag(artifact, build=False)

    @property
    def koji_session(self):
        session = Mock()
        session.newRepo.return_value = 123
        return session

    @property
    def module_build_tag(self):
        return {"name": self.tag_name + "-build"}

    def _send_repo_done(self):
        msg = module_build_service.messaging.KojiRepoChange(
            msg_id='a faked internal message',
            repo_tag=self.tag_name + "-build",
        )
        module_build_service.scheduler.consumer.work_queue_put(msg)

    def _send_tag(self, artifact, build=True):
        if build:
            tag = self.tag_name + "-build"
        else:
            tag = self.tag_name
        msg = module_build_service.messaging.KojiTagChange(
            msg_id='a faked internal message',
            tag=tag,
            artifact=artifact
        )
        module_build_service.scheduler.consumer.work_queue_put(msg)

    def _send_build_change(self, state, source, build_id):
        # build_id=1 and task_id=1 are OK here, because we are building just
        # one RPM at the time.
        msg = module_build_service.messaging.KojiBuildChange(
            msg_id='a faked internal message',
            build_id=build_id,
            task_id=build_id,
            build_name=path.basename(source),
            build_new_state=state,
            build_release="1",
            build_version="1"
        )
        module_build_service.scheduler.consumer.work_queue_put(msg)

    def build(self, artifact_name, source):
        print("Starting building artifact %s: %s" % (artifact_name, source))

        FakeModuleBuilder._build_id += 1

        if FakeModuleBuilder.on_build_cb:
            FakeModuleBuilder.on_build_cb(self, artifact_name, source)

        if FakeModuleBuilder.BUILD_STATE != "BUILDING":
            self._send_build_change(
                koji.BUILD_STATES[FakeModuleBuilder.BUILD_STATE], source,
                FakeModuleBuilder._build_id)

        if FakeModuleBuilder.INSTANT_COMPLETE:
            state = koji.BUILD_STATES['COMPLETE']
        else:
            state = koji.BUILD_STATES['BUILDING']

        reason = "Submitted %s to Koji" % (artifact_name)
        return FakeModuleBuilder._build_id, state, reason, None

    @staticmethod
    def get_disttag_srpm(disttag, module_build):
        # @FIXME
        return KojiModuleBuilder.get_disttag_srpm(disttag, module_build)

    def cancel_build(self, task_id):
        if FakeModuleBuilder.on_cancel_cb:
            FakeModuleBuilder.on_cancel_cb(self, task_id)

    def list_tasks_for_components(self, component_builds=None, state='active'):
        pass


def cleanup_moksha():
    # Necessary to restart the twisted reactor for the next test.
    import sys
    del sys.modules['twisted.internet.reactor']
    del sys.modules['moksha.hub.reactor']
    del sys.modules['moksha.hub']
    import moksha.hub.reactor # noqa


@patch.object(module_build_service.config.Config, 'system', new_callable=PropertyMock,
              return_value='test')
@patch("module_build_service.builder.GenericBuilder.default_buildroot_groups",
       return_value={
           'srpm-build':
           set(['shadow-utils', 'fedora-release', 'redhat-rpm-config',
                'rpm-build', 'fedpkg-minimal', 'gnupg2', 'bash']),
           'build':
           set(['unzip', 'fedora-release', 'tar', 'cpio', 'gawk',
                'gcc', 'xz', 'sed', 'findutils', 'util-linux', 'bash',
                'info', 'bzip2', 'grep', 'redhat-rpm-config',
                'diffutils', 'make', 'patch', 'shadow-utils',
                'coreutils', 'which', 'rpm-build', 'gzip', 'gcc-c++'])})
class TestBuild(unittest.TestCase):

    # Global variable used for tests if needed
    _global_var = None

    def setUp(self):
        GenericBuilder.register_backend_class(FakeModuleBuilder)
        self.client = app.test_client()
        clean_database()

        filename = cassette_dir + self.id()
        self.vcr = vcr.use_cassette(filename)
        self.vcr.__enter__()

    def tearDown(self):
        FakeModuleBuilder.reset()
        cleanup_moksha()
        self.vcr.__exit__()
        for i in range(20):
            try:
                os.remove(build_logs.path(i))
            except Exception:
                pass

    @timed(30)
    @patch('module_build_service.auth.get_user', return_value=user)
    @patch('module_build_service.scm.SCM')
    def test_submit_build(self, mocked_scm, mocked_get_user, conf_system, dbg):
        """
        Tests the build of testmodule.yaml using FakeModuleBuilder which
        succeeds everytime.
        """
        FakeSCM(mocked_scm, 'testmodule', 'testmodule.yaml',
                '620ec77321b2ea7b0d67d82992dda3e1d67055b4')

        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'branch': 'master', 'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#68932c90de214d9d13feefbd35246a81b6cb8d49'}))

        data = json.loads(rv.data)
        module_build_id = data['id']

        # Check that components are tagged after the batch is built.
        tag_groups = []
        tag_groups.append(set([u'perl-Tangerine?#f24-1-1', u'perl-List-Compare?#f25-1-1']))
        tag_groups.append(set([u'tangerine?#f23-1-1']))

        def on_tag_artifacts_cb(cls, artifacts):
            self.assertEqual(tag_groups.pop(0), set(artifacts))

        FakeModuleBuilder.on_tag_artifacts_cb = on_tag_artifacts_cb

        # Check that the components are added to buildroot after the batch
        # is built.
        buildroot_groups = []
        buildroot_groups.append(set([u'module-build-macros-0.1-1.module+fc4ed5f7.src.rpm-1-1']))
        buildroot_groups.append(set([u'perl-Tangerine?#f24-1-1', u'perl-List-Compare?#f25-1-1']))
        buildroot_groups.append(set([u'tangerine?#f23-1-1']))

        def on_buildroot_add_artifacts_cb(cls, artifacts, install):
            self.assertEqual(buildroot_groups.pop(0), set(artifacts))

        FakeModuleBuilder.on_buildroot_add_artifacts_cb = on_buildroot_add_artifacts_cb

        msgs = []
        stop = module_build_service.scheduler.make_simple_stop_condition(db.session)
        module_build_service.scheduler.main(msgs, stop)

        # All components should be built and module itself should be in "done"
        # or "ready" state.
        for build in models.ComponentBuild.query.filter_by(module_id=module_build_id).all():
            self.assertEqual(build.state, koji.BUILD_STATES['COMPLETE'])
            self.assertTrue(build.module_build.state in [models.BUILD_STATES["done"],
                                                         models.BUILD_STATES["ready"]])

        # All components has to be tagged, so tag_groups and buildroot_groups are empty...
        self.assertEqual(tag_groups, [])
        self.assertEqual(buildroot_groups, [])
        module_build = models.ModuleBuild.query.get(module_build_id)
        self.assertEqual(module_build.module_builds_trace[0].state, models.BUILD_STATES['init'])
        self.assertEqual(module_build.module_builds_trace[1].state, models.BUILD_STATES['wait'])
        self.assertEqual(module_build.module_builds_trace[2].state, models.BUILD_STATES['build'])
        self.assertEqual(module_build.module_builds_trace[3].state, models.BUILD_STATES['done'])
        self.assertEqual(module_build.module_builds_trace[4].state, models.BUILD_STATES['ready'])
        self.assertEqual(len(module_build.module_builds_trace), 5)

    @timed(30)
    @patch('module_build_service.auth.get_user', return_value=user)
    @patch('module_build_service.scm.SCM')
    def test_submit_build_no_components(self, mocked_scm, mocked_get_user, conf_system, dbg):
        """
        Tests the build of a module with no components
        """
        FakeSCM(mocked_scm, 'python3', 'python3-no-components.yaml',
                '620ec77321b2ea7b0d67d82992dda3e1d67055b4')

        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'branch': 'master', 'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#68932c90de214d9d13feefbd35246a81b6cb8d49'}))

        data = json.loads(rv.data)
        module_build_id = data['id']

        msgs = []
        stop = module_build_service.scheduler.make_simple_stop_condition(db.session)
        module_build_service.scheduler.main(msgs, stop)

        module_build = models.ModuleBuild.query.filter_by(id=module_build_id).one()
        # Make sure no component builds were registered
        self.assertEqual(len(module_build.component_builds), 0)
        # Make sure the build is done
        self.assertEqual(module_build.state, models.BUILD_STATES['ready'])

    @timed(30)
    @patch('module_build_service.auth.get_user', return_value=user)
    @patch('module_build_service.scm.SCM')
    def test_submit_build_from_yaml_not_allowed(
            self, mocked_scm, mocked_get_user, conf_system, dbg):
        FakeSCM(mocked_scm, "testmodule", "testmodule.yaml")

        testmodule = os.path.join(base_dir, 'staged_data', 'testmodule.yaml')
        with open(testmodule) as f:
            yaml = f.read()

        with patch.object(module_build_service.config.Config, 'yaml_submit_allowed',
                          new_callable=PropertyMock, return_value=False):
            rv = self.client.post('/module-build-service/1/module-builds/',
                                  content_type='multipart/form-data',
                                  data={'yaml': (testmodule, yaml)})
            data = json.loads(rv.data)
            self.assertEqual(data['status'], 403)
            self.assertEqual(data['message'], 'YAML submission is not enabled')

    @timed(30)
    @patch('module_build_service.auth.get_user', return_value=user)
    @patch('module_build_service.scm.SCM')
    def test_submit_build_from_yaml_allowed(self, mocked_scm, mocked_get_user, conf_system, dbg):
        FakeSCM(mocked_scm, "testmodule", "testmodule.yaml")

        testmodule = os.path.join(base_dir, 'staged_data', 'testmodule.yaml')
        with open(testmodule) as f:
            yaml = f.read()

        with patch.object(module_build_service.config.Config, 'yaml_submit_allowed',
                          new_callable=PropertyMock, return_value=True):
            rv = self.client.post('/module-build-service/1/module-builds/',
                                  content_type='multipart/form-data',
                                  data={'yaml': (testmodule, yaml)})
            data = json.loads(rv.data)
            self.assertEqual(data['id'], 1)

        msgs = []
        stop = module_build_service.scheduler.make_simple_stop_condition(db.session)
        module_build_service.scheduler.main(msgs, stop)

    @timed(30)
    @patch('module_build_service.auth.get_user', return_value=user)
    def test_submit_build_with_optional_params(self, mocked_get_user, conf_system, dbg):
        params = {'branch': 'master', 'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                            'testmodule.git?#68932c90de214d9d13feefbd35246a81b6cb8d49'}

        def submit(data):
            rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(data))
            return json.loads(rv.data)

        data = submit(dict(params.items() + {"not_existing_param": "foo"}.items()))
        self.assertIn("The request contains unspecified parameters:", data["message"])
        self.assertIn("not_existing_param", data["message"])
        self.assertEqual(data["status"], 400)

        data = submit(dict(params.items() + {"copr_owner": "foo"}.items()))
        self.assertIn("The request contains parameters specific to Copr builder", data["message"])

    @timed(30)
    @patch('module_build_service.auth.get_user', return_value=user)
    @patch('module_build_service.scm.SCM')
    def test_submit_build_cancel(self, mocked_scm, mocked_get_user, conf_system, dbg):
        """
        Submit all builds for a module and cancel the module build later.
        """
        FakeSCM(mocked_scm, 'testmodule', 'testmodule.yaml',
                '620ec77321b2ea7b0d67d82992dda3e1d67055b4')

        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'branch': 'master', 'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#68932c90de214d9d13feefbd35246a81b6cb8d49'}))

        data = json.loads(rv.data)
        module_build_id = data['id']

        # This callback is called before return of FakeModuleBuilder.build()
        # method. We just cancel the build here using the web API to simulate
        # user cancelling the build in the middle of building.
        def on_build_cb(cls, artifact_name, source):
            self.client.patch('/module-build-service/1/module-builds/' + str(module_build_id),
                              data=json.dumps({'state': 'failed'}))

        cancelled_tasks = []

        def on_cancel_cb(cls, task_id):
            cancelled_tasks.append(task_id)

        # We do not want the builds to COMPLETE, but instead we want them
        # to be in the BULDING state after the FakeModuleBuilder.build().
        FakeModuleBuilder.BUILD_STATE = "BUILDING"
        FakeModuleBuilder.on_build_cb = on_build_cb
        FakeModuleBuilder.on_cancel_cb = on_cancel_cb

        msgs = []
        stop = module_build_service.scheduler.make_simple_stop_condition(db.session)
        module_build_service.scheduler.main(msgs, stop)

        # Because we did not finished single component build and canceled the
        # module build, all components and even the module itself should be in
        # failed state with state_reason se to cancellation message.
        for build in models.ComponentBuild.query.filter_by(module_id=module_build_id).all():
            self.assertEqual(build.state, koji.BUILD_STATES['FAILED'])
            self.assertEqual(build.state_reason, "Canceled by Homer J. Simpson.")
            self.assertEqual(build.module_build.state, models.BUILD_STATES["failed"])
            self.assertEqual(build.module_build.state_reason, "Canceled by Homer J. Simpson.")

            # Check that cancel_build has been called for this build
            if build.task_id:
                self.assertTrue(build.task_id in cancelled_tasks)

    @timed(30)
    @patch('module_build_service.auth.get_user', return_value=user)
    @patch('module_build_service.scm.SCM')
    def test_submit_build_instant_complete(self, mocked_scm, mocked_get_user, conf_system, dbg):
        """
        Tests the build of testmodule.yaml using FakeModuleBuilder which
        succeeds everytime.
        """
        FakeSCM(mocked_scm, 'testmodule', 'testmodule.yaml',
                '620ec77321b2ea7b0d67d82992dda3e1d67055b4')

        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'branch': 'master', 'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#68932c90de214d9d13feefbd35246a81b6cb8d49'}))

        data = json.loads(rv.data)
        module_build_id = data['id']

        FakeModuleBuilder.BUILD_STATE = "BUILDING"
        FakeModuleBuilder.INSTANT_COMPLETE = True

        msgs = []
        stop = module_build_service.scheduler.make_simple_stop_condition(db.session)
        module_build_service.scheduler.main(msgs, stop)

        # All components should be built and module itself should be in "done"
        # or "ready" state.
        for build in models.ComponentBuild.query.filter_by(module_id=module_build_id).all():
            self.assertEqual(build.state, koji.BUILD_STATES['COMPLETE'])
            self.assertTrue(build.module_build.state in [models.BUILD_STATES["done"],
                                                         models.BUILD_STATES["ready"]])

    @timed(30)
    @patch('module_build_service.auth.get_user', return_value=user)
    @patch('module_build_service.scm.SCM')
    @patch("module_build_service.config.Config.num_concurrent_builds",
           new_callable=PropertyMock, return_value=1)
    def test_submit_build_concurrent_threshold(self, conf_num_concurrent_builds,
                                               mocked_scm, mocked_get_user,
                                               conf_system, dbg):
        """
        Tests the build of testmodule.yaml using FakeModuleBuilder with
        num_concurrent_builds set to 1.
        """
        FakeSCM(mocked_scm, 'testmodule', 'testmodule.yaml',
                '620ec77321b2ea7b0d67d82992dda3e1d67055b4')

        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'branch': 'master', 'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#68932c90de214d9d13feefbd35246a81b6cb8d49'}))

        data = json.loads(rv.data)
        module_build_id = data['id']

        def stop(message):
            """
            Stop the scheduler when the module is built or when we try to build
            more components than the num_concurrent_builds.
            """
            main_stop = module_build_service.scheduler.make_simple_stop_condition(db.session)
            over_threshold = conf.num_concurrent_builds < \
                db.session.query(models.ComponentBuild).filter_by(
                    state=koji.BUILD_STATES['BUILDING']).count()
            return main_stop(message) or over_threshold

        msgs = []
        module_build_service.scheduler.main(msgs, stop)

        # All components should be built and module itself should be in "done"
        # or "ready" state.
        for build in models.ComponentBuild.query.filter_by(module_id=module_build_id).all():
            self.assertEqual(build.state, koji.BUILD_STATES['COMPLETE'])
            # When this fails, it can mean that num_concurrent_builds
            # threshold has been met.
            self.assertTrue(build.module_build.state in [models.BUILD_STATES["done"],
                                                         models.BUILD_STATES["ready"]])

    @timed(30)
    @patch('module_build_service.auth.get_user', return_value=user)
    @patch('module_build_service.scm.SCM')
    @patch("module_build_service.config.Config.num_concurrent_builds",
           new_callable=PropertyMock, return_value=2)
    def test_try_to_reach_concurrent_threshold(self, conf_num_concurrent_builds,
                                               mocked_scm, mocked_get_user,
                                               conf_system, dbg):
        """
        Tests that we try to submit new component build right after
        the previous one finished without waiting for all
        the num_concurrent_builds to finish.
        """
        FakeSCM(mocked_scm, 'testmodule-more-components', 'testmodule-more-components.yaml',
                '620ec77321b2ea7b0d67d82992dda3e1d67055b4')

        self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'branch': 'master', 'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#68932c90de214d9d13feefbd35246a81b6cb8d49'}))

        # Holds the number of concurrent component builds during
        # the module build.
        TestBuild._global_var = []

        def stop(message):
            """
            Stop the scheduler when the module is built or when we try to build
            more components than the num_concurrent_builds.
            """
            main_stop = module_build_service.scheduler.make_simple_stop_condition(db.session)
            num_building = db.session.query(models.ComponentBuild).filter_by(
                state=koji.BUILD_STATES['BUILDING']).count()
            over_threshold = conf.num_concurrent_builds < num_building
            TestBuild._global_var.append(num_building)
            return main_stop(message) or over_threshold

        msgs = []
        module_build_service.scheduler.main(msgs, stop)

        # _global_var looks similar to this: [0, 1, 0, 0, 2, 2, 1, 0, 0, 0]
        # It shows the number of concurrent builds in the time. At first we
        # want to remove adjacent duplicate entries, because we only care
        # about changes.
        # We are building two batches, so there should be just two situations
        # when we should be building just single component:
        #   1) module-base-macros in first batch.
        #   2) The last component of second batch.
        # If we are building single component more often, num_concurrent_builds
        # does not work correctly.
        num_builds = [k for k, g in itertools.groupby(TestBuild._global_var)]
        self.assertEqual(num_builds.count(1), 2)

    @timed(30)
    @patch('module_build_service.auth.get_user', return_value=user)
    @patch('module_build_service.scm.SCM')
    @patch("module_build_service.config.Config.num_concurrent_builds",
           new_callable=PropertyMock, return_value=1)
    def test_build_in_batch_fails(self, conf_num_concurrent_builds, mocked_scm,
                                  mocked_get_user, conf_system, dbg):
        """
        Tests that if the build in batch fails, other components in a batch
        are still build, but next batch is not started.
        """
        FakeSCM(mocked_scm, 'testmodule', 'testmodule.yaml',
                '620ec77321b2ea7b0d67d82992dda3e1d67055b4')

        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'branch': 'master', 'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#68932c90de214d9d13feefbd35246a81b6cb8d49'}))

        data = json.loads(rv.data)
        module_build_id = data['id']

        def on_build_cb(cls, artifact_name, source):
            # fail perl-Tangerine build
            if artifact_name.startswith("perl-Tangerine"):
                FakeModuleBuilder.BUILD_STATE = "FAILED"
            else:
                FakeModuleBuilder.BUILD_STATE = "COMPLETE"
                # Tag the build in the -build tag
                cls._send_tag(artifact_name)
                if not artifact_name.startswith("module-build-macros"):
                    # Tag the build in the final tag
                    cls._send_tag(artifact_name, build=False)

        FakeModuleBuilder.on_build_cb = on_build_cb

        # Check that no components are tagged when single component fails
        # in batch.
        def on_tag_artifacts_cb(cls, artifacts):
            raise ValueError("No component should be tagged.")
        FakeModuleBuilder.on_tag_artifacts_cb = on_tag_artifacts_cb

        msgs = []
        stop = module_build_service.scheduler.make_simple_stop_condition(db.session)
        module_build_service.scheduler.main(msgs, stop)

        for c in models.ComponentBuild.query.filter_by(module_id=module_build_id).all():
            # perl-Tangerine is expected to fail as configured in on_build_cb.
            if c.package == "perl-Tangerine":
                self.assertEqual(c.state, koji.BUILD_STATES['FAILED'])
            # tangerine is expected to fail, because it is in batch 3, but
            # we had a failing component in batch 2.
            elif c.package == "tangerine":
                self.assertEqual(c.state, koji.BUILD_STATES['FAILED'])
                self.assertEqual(c.state_reason, "Some components failed to build.")
            else:
                self.assertEqual(c.state, koji.BUILD_STATES['COMPLETE'])

            # Whole module should be failed.
            self.assertEqual(c.module_build.state, models.BUILD_STATES['failed'])
            self.assertEqual(c.module_build.state_reason, "Some components failed to build.")

            # We should end up with batch 2 and never start batch 3, because
            # there were failed components in batch 2.
            self.assertEqual(c.module_build.batch, 2)

    @timed(30)
    @patch('module_build_service.auth.get_user', return_value=user)
    @patch('module_build_service.scm.SCM')
    @patch("module_build_service.config.Config.num_concurrent_builds",
           new_callable=PropertyMock, return_value=1)
    def test_all_builds_in_batch_fail(self, conf_num_concurrent_builds, mocked_scm,
                                      mocked_get_user, conf_system, dbg):
        """
        Tests that if the build in batch fails, other components in a batch
        are still build, but next batch is not started.
        """
        FakeSCM(mocked_scm, 'testmodule', 'testmodule.yaml',
                '620ec77321b2ea7b0d67d82992dda3e1d67055b4')

        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'branch': 'master', 'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#68932c90de214d9d13feefbd35246a81b6cb8d49'}))

        data = json.loads(rv.data)
        module_build_id = data['id']

        def on_build_cb(cls, artifact_name, source):
            # Next components *after* the module-build-macros will fail
            # to build.
            if artifact_name.startswith("module-build-macros"):
                cls._send_tag(artifact_name)
            else:
                FakeModuleBuilder.BUILD_STATE = "FAILED"

        FakeModuleBuilder.on_build_cb = on_build_cb

        msgs = []
        stop = module_build_service.scheduler.make_simple_stop_condition(db.session)
        module_build_service.scheduler.main(msgs, stop)

        for c in models.ComponentBuild.query.filter_by(module_id=module_build_id).all():
            # perl-Tangerine is expected to fail as configured in on_build_cb.
            if c.package == "module-build-macros":
                self.assertEqual(c.state, koji.BUILD_STATES['COMPLETE'])
            else:
                self.assertEqual(c.state, koji.BUILD_STATES['FAILED'])

            # Whole module should be failed.
            self.assertEqual(c.module_build.state, models.BUILD_STATES['failed'])
            self.assertEqual(c.module_build.state_reason, "Some components failed to build.")

            # We should end up with batch 2 and never start batch 3, because
            # there were failed components in batch 2.
            self.assertEqual(c.module_build.batch, 2)

    @timed(30)
    @patch('module_build_service.auth.get_user', return_value=user)
    @patch('module_build_service.scm.SCM')
    def test_submit_build_reuse_all(self, mocked_scm, mocked_get_user,
                                    conf_system, dbg):
        """
        Tests that we do not try building module-build-macros when reusing all
        components in a module build.
        """
        test_reuse_component_init_data()

        def on_build_cb(cls, artifact_name, source):
            raise ValueError("All components should be reused, not build.")
        FakeModuleBuilder.on_build_cb = on_build_cb

        # Check that components are tagged after the batch is built.
        tag_groups = []
        tag_groups.append(set(
            ['perl-Tangerine-0.23-1.module_testmodule_master_20170109091357',
             'perl-List-Compare-0.53-5.module_testmodule_master_20170109091357',
             'tangerine-0.22-3.module_testmodule_master_20170109091357']))

        def on_tag_artifacts_cb(cls, artifacts):
            self.assertEqual(tag_groups.pop(0), set(artifacts))
        FakeModuleBuilder.on_tag_artifacts_cb = on_tag_artifacts_cb

        buildtag_groups = []
        buildtag_groups.append(set(
            ['perl-Tangerine-0.23-1.module_testmodule_master_20170109091357',
             'perl-List-Compare-0.53-5.module_testmodule_master_20170109091357',
             'tangerine-0.22-3.module_testmodule_master_20170109091357']))

        def on_buildroot_add_artifacts_cb(cls, artifacts, install):
            self.assertEqual(buildtag_groups.pop(0), set(artifacts))
        FakeModuleBuilder.on_buildroot_add_artifacts_cb = on_buildroot_add_artifacts_cb

        msgs = [MBSModule("local module build", 2, 1)]
        stop = module_build_service.scheduler.make_simple_stop_condition(db.session)
        module_build_service.scheduler.main(msgs, stop)

        reused_component_ids = {"module-build-macros": None, "tangerine": 3,
                                "perl-Tangerine": 1, "perl-List-Compare": 2}

        # All components should be built and module itself should be in "done"
        # or "ready" state.
        for build in models.ComponentBuild.query.filter_by(module_id=2).all():
            self.assertEqual(build.state, koji.BUILD_STATES['COMPLETE'])
            self.assertTrue(build.module_build.state in [models.BUILD_STATES["done"],
                                                         models.BUILD_STATES["ready"]])

            self.assertEqual(build.reused_component_id,
                             reused_component_ids[build.package])

    @timed(30)
    @patch('module_build_service.auth.get_user', return_value=user)
    @patch('module_build_service.scm.SCM')
    def test_submit_build_reuse_all_without_build_macros(self, mocked_scm, mocked_get_user,
                                                         conf_system, dbg):
        """
        Tests that we can reuse components even when the reused module does
        not have module-build-macros component.
        """
        test_reuse_component_init_data()

        models.ComponentBuild.query.filter_by(package="module-build-macros").delete()
        self.assertEqual(len(models.ComponentBuild.query.filter_by(
            package="module-build-macros").all()), 0)

        db.session.commit()

        def on_build_cb(cls, artifact_name, source):
            raise ValueError("All components should be reused, not build.")
        FakeModuleBuilder.on_build_cb = on_build_cb

        # Check that components are tagged after the batch is built.
        tag_groups = []
        tag_groups.append(set(
            ['perl-Tangerine-0.23-1.module_testmodule_master_20170109091357',
             'perl-List-Compare-0.53-5.module_testmodule_master_20170109091357',
             'tangerine-0.22-3.module_testmodule_master_20170109091357']))

        def on_tag_artifacts_cb(cls, artifacts):
            self.assertEqual(tag_groups.pop(0), set(artifacts))
        FakeModuleBuilder.on_tag_artifacts_cb = on_tag_artifacts_cb

        buildtag_groups = []
        buildtag_groups.append(set(
            ['perl-Tangerine-0.23-1.module_testmodule_master_20170109091357',
             'perl-List-Compare-0.53-5.module_testmodule_master_20170109091357',
             'tangerine-0.22-3.module_testmodule_master_20170109091357']))

        def on_buildroot_add_artifacts_cb(cls, artifacts, install):
            self.assertEqual(buildtag_groups.pop(0), set(artifacts))
        FakeModuleBuilder.on_buildroot_add_artifacts_cb = on_buildroot_add_artifacts_cb

        msgs = [MBSModule("local module build", 2, 1)]
        stop = module_build_service.scheduler.make_simple_stop_condition(db.session)
        module_build_service.scheduler.main(msgs, stop)

        # All components should be built and module itself should be in "done"
        # or "ready" state.
        for build in models.ComponentBuild.query.filter_by(module_id=2).all():
            self.assertEqual(build.state, koji.BUILD_STATES['COMPLETE'])
            self.assertTrue(build.module_build.state in [models.BUILD_STATES["done"],
                                                         models.BUILD_STATES["ready"]])
            self.assertNotEqual(build.package, "module-build-macros")

    @timed(60)
    @patch('module_build_service.auth.get_user', return_value=user)
    @patch('module_build_service.scm.SCM')
    def test_submit_build_resume(self, mocked_scm, mocked_get_user, conf_system, dbg):
        """
        Tests that resuming the build works even when previous batches
        are already built.
        """
        now = datetime.utcnow()
        submitted_time = now - timedelta(minutes=3)
        # Create a module in the failed state
        build_one = models.ModuleBuild()
        build_one.name = 'testmodule'
        build_one.stream = 'master'
        build_one.version = 1
        build_one.state = models.BUILD_STATES['failed']
        current_dir = os.path.dirname(__file__)
        formatted_testmodule_yml_path = os.path.join(
            current_dir, '..', 'staged_data', 'formatted_testmodule.yaml')
        with open(formatted_testmodule_yml_path, 'r') as f:
            build_one.modulemd = f.read()
        build_one.koji_tag = 'module-testmodule-master-1'
        build_one.scmurl = 'git://pkgs.stg.fedoraproject.org/modules/testmodule.git?#7fea453'
        build_one.batch = models.BUILD_STATES['failed']
        build_one.owner = 'Homer J. Simpson'
        build_one.time_submitted = submitted_time
        build_one.time_modified = now
        build_one.rebuild_strategy = 'changed-and-after'
        # It went from init, to wait, to build, and then failed
        mbt_one = models.ModuleBuildTrace(
            state_time=submitted_time, state=models.BUILD_STATES['init'])
        mbt_two = models.ModuleBuildTrace(
            state_time=now - timedelta(minutes=2), state=models.BUILD_STATES['wait'])
        mbt_three = models.ModuleBuildTrace(
            state_time=now - timedelta(minutes=1), state=models.BUILD_STATES['build'])
        mbt_four = models.ModuleBuildTrace(state_time=now, state=build_one.state)
        build_one.module_builds_trace.append(mbt_one)
        build_one.module_builds_trace.append(mbt_two)
        build_one.module_builds_trace.append(mbt_three)
        build_one.module_builds_trace.append(mbt_four)
        # Successful component
        component_one = models.ComponentBuild()
        component_one.package = 'perl-Tangerine'
        component_one.format = 'rpms'
        component_one.scmurl = 'git://pkgs.stg.fedoraproject.org/rpms/perl-Tangerine.git?#f24'
        component_one.state = koji.BUILD_STATES['COMPLETE']
        component_one.nvr = 'perl-Tangerine-0.23-1.module_testmodule_master_1'
        component_one.batch = 2
        component_one.module_id = 1
        component_one.ref = '4ceea43add2366d8b8c5a622a2fb563b625b9abf'
        component_one.tagged = True
        component_one.tagged_in_final = True
        # Failed component
        component_two = models.ComponentBuild()
        component_two.package = 'perl-List-Compare'
        component_two.format = 'rpms'
        component_two.scmurl = 'git://pkgs.stg.fedoraproject.org/rpms/perl-List-Compare.git?#f24'
        component_two.state = koji.BUILD_STATES['FAILED']
        component_two.batch = 2
        component_two.module_id = 1
        # Component that isn't started yet
        component_three = models.ComponentBuild()
        component_three.package = 'tangerine'
        component_three.format = 'rpms'
        component_three.scmurl = 'git://pkgs.stg.fedoraproject.org/rpms/tangerine.git?#f24'
        component_three.batch = 3
        component_three.module_id = 1

        db.session.add(build_one)
        db.session.add(component_one)
        db.session.add(component_two)
        db.session.add(component_three)
        db.session.commit()
        db.session.expire_all()

        FakeSCM(mocked_scm, 'testmodule', 'testmodule.yaml', '7fea453')
        # Resubmit the failed module
        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'branch': 'master', 'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#7fea453'}))

        data = json.loads(rv.data)
        module_build_id = data['id']

        FakeModuleBuilder.BUILD_STATE = 'BUILDING'
        FakeModuleBuilder.INSTANT_COMPLETE = True

        module_build = models.ModuleBuild.query.filter_by(id=module_build_id).one()
        components = models.ComponentBuild.query.filter_by(
            module_id=module_build_id, batch=2).order_by(models.ComponentBuild.id).all()
        # Make sure the build went from failed to wait
        self.assertEqual(module_build.state, models.BUILD_STATES['wait'])
        self.assertEqual(module_build.state_reason, 'Resubmitted by Homer J. Simpson')
        # Make sure the state was reset on the failed component
        self.assertIsNone(components[1].state)
        db.session.expire_all()

        # Run the backend
        msgs = []
        stop = module_build_service.scheduler.make_simple_stop_condition(db.session)
        module_build_service.scheduler.main(msgs, stop)

        # All components should be built and module itself should be in "done"
        # or "ready" state.
        for build in models.ComponentBuild.query.filter_by(module_id=module_build_id).all():
            self.assertEqual(build.state, koji.BUILD_STATES['COMPLETE'])
            self.assertTrue(build.module_build.state in [models.BUILD_STATES['done'],
                                                         models.BUILD_STATES['ready']])

    @timed(60)
    @patch('module_build_service.auth.get_user', return_value=user)
    @patch('module_build_service.scm.SCM')
    def test_submit_build_resume_failed_init(self, mocked_scm, mocked_get_user, conf_system, dbg):
        """
        Tests that resuming the build works when the build failed during the init step
        """
        FakeSCM(mocked_scm, 'testmodule', 'testmodule.yaml', '7fea453')
        stop = module_build_service.scheduler.make_simple_stop_condition(db.session)

        with patch('module_build_service.utils.format_mmd') as mock_format_mmd:
            mock_format_mmd.side_effect = Forbidden(
                'Custom component repositories aren\'t allowed.')
            rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
                {'branch': 'master', 'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                    'testmodule.git?#7fea453'}))
            # Run the backend so that it fails in the "init" handler
            module_build_service.scheduler.main([], stop)
            cleanup_moksha()

        module_build_id = json.loads(rv.data)['id']
        module_build = models.ModuleBuild.query.filter_by(id=module_build_id).one()
        self.assertEqual(module_build.state, models.BUILD_STATES['failed'])
        self.assertEqual(
            module_build.state_reason, 'Custom component repositories aren\'t allowed.')
        self.assertEqual(len(module_build.module_builds_trace), 2)
        self.assertEqual(module_build.module_builds_trace[0].state, models.BUILD_STATES['init'])
        self.assertEqual(module_build.module_builds_trace[1].state, models.BUILD_STATES['failed'])

        # Resubmit the failed module
        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'branch': 'master', 'scmurl': ('git://pkgs.stg.fedoraproject.org/modules/'
                                            'testmodule.git?#7fea453')}))

        FakeModuleBuilder.BUILD_STATE = 'BUILDING'
        FakeModuleBuilder.INSTANT_COMPLETE = True

        module_build = models.ModuleBuild.query.filter_by(id=module_build_id).one()
        components = models.ComponentBuild.query.filter_by(
            module_id=module_build_id, batch=2).order_by(models.ComponentBuild.id).all()
        # Make sure the build went from failed to init
        self.assertEqual(module_build.state, models.BUILD_STATES['init'])
        self.assertEqual(module_build.state_reason, 'Resubmitted by Homer J. Simpson')
        # Make sure there are no components
        self.assertEqual(components, [])
        db.session.expire_all()

        # Run the backend again
        module_build_service.scheduler.main([], stop)

        # All components should be built and module itself should be in "done"
        # or "ready" state.
        for build in models.ComponentBuild.query.filter_by(module_id=module_build_id).all():
            self.assertEqual(build.state, koji.BUILD_STATES['COMPLETE'])
            self.assertTrue(build.module_build.state in [models.BUILD_STATES['done'],
                                                         models.BUILD_STATES['ready']])

    @patch('module_build_service.auth.get_user', return_value=user)
    @patch('module_build_service.scm.SCM')
    def test_submit_build_resume_init_fail(self, mocked_scm, mocked_get_user, conf_system, dbg):
        """
        Tests that resuming the build fails when the build is in init state
        """
        FakeSCM(mocked_scm, 'testmodule', 'testmodule.yaml',
                '620ec77321b2ea7b0d67d82992dda3e1d67055b4')
        # Post so a module is in the init phase
        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'branch': 'master', 'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#68932c90de214d9d13feefbd35246a81b6cb8d49'}))
        self.assertEqual(rv.status_code, 201)
        # Post again and make sure it fails
        rv2 = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'branch': 'master', 'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#68932c90de214d9d13feefbd35246a81b6cb8d49'}))
        data = json.loads(rv2.data)
        expected = {
            'error': 'Conflict',
            'message': ('Module (state=0) already exists. Only a new build or resubmission of a '
                        'failed build is allowed.'),
            'status': 409
        }
        self.assertEqual(data, expected)


@patch("module_build_service.config.Config.system",
       new_callable=PropertyMock, return_value="testlocal")
class TestLocalBuild(unittest.TestCase):

    def setUp(self):
        FakeModuleBuilder.on_build_cb = None
        FakeModuleBuilder.backend = 'testlocal'
        GenericBuilder.register_backend_class(FakeModuleBuilder)
        self.client = app.test_client()
        clean_database()

        filename = cassette_dir + self.id()
        self.vcr = vcr.use_cassette(filename)
        self.vcr.__enter__()

    def tearDown(self):
        FakeModuleBuilder.reset()
        cleanup_moksha()
        self.vcr.__exit__()
        for i in range(20):
            try:
                os.remove(build_logs.path(i))
            except Exception:
                pass

    @timed(30)
    @patch('module_build_service.auth.get_user', return_value=user)
    @patch('module_build_service.scm.SCM')
    @patch("module_build_service.config.Config.mock_resultsdir",
           new_callable=PropertyMock,
           return_value=path.join(base_dir, 'staged_data', "local_builds"))
    def test_submit_build_local_dependency(
            self, resultsdir, mocked_scm, mocked_get_user, conf_system):
        """
        Tests local module build dependency.
        """
        with app.app_context():
            module_build_service.utils.load_local_builds(["base-runtime"])
            FakeSCM(mocked_scm, 'testmodule', 'testmodule.yaml',
                    '620ec77321b2ea7b0d67d82992dda3e1d67055b4')

            rv = self.client.post(
                '/module-build-service/1/module-builds/', data=json.dumps(
                    {'branch': 'master',
                     'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                     'testmodule.git?#68932c90de214d9d13feefbd35246a81b6cb8d49'}))

            data = json.loads(rv.data)
            module_build_id = data['id']

            # Local base-runtime has changed profiles, so we can detect we use
            # the local one and not the main one.
            FakeModuleBuilder.DEFAULT_GROUPS = {
                'srpm-build':
                    set(['bar']),
                'build':
                    set(['foo'])}

            msgs = []
            stop = module_build_service.scheduler.make_simple_stop_condition(
                db.session)
            module_build_service.scheduler.main(msgs, stop)

            # All components should be built and module itself should be in "done"
            # or "ready" state.
            for build in models.ComponentBuild.query.filter_by(
                    module_id=module_build_id).all():
                self.assertEqual(build.state, koji.BUILD_STATES['COMPLETE'])
                self.assertTrue(build.module_build.state in [
                    models.BUILD_STATES["done"], models.BUILD_STATES["ready"]])
