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
from os import path, mkdir
from os.path import dirname
from shutil import copyfile

from nose.tools import timed

import module_build_service.messaging
import module_build_service.scheduler.handlers.repos
import module_build_service.utils
from module_build_service import db, models, conf

from mock import patch, PropertyMock

from tests import app, init_data
import os
import json
import itertools

from module_build_service.builder import KojiModuleBuilder, GenericBuilder
import module_build_service.scheduler.consumer

base_dir = dirname(dirname(__file__))
cassette_dir = base_dir + '/vcr-request-data/'

user = ('Homer J. Simpson', set(['packager']))

class MockedSCM(object):
    def __init__(self, mocked_scm, name, mmd_filename, commit=None):
        self.mocked_scm = mocked_scm
        self.name = name
        self.commit = commit
        self.mmd_filename = mmd_filename

        self.mocked_scm.return_value.checkout = self.checkout
        self.mocked_scm.return_value.name = self.name
        self.mocked_scm.return_value.branch = 'master'
        self.mocked_scm.return_value.get_latest = self.get_latest
        self.mocked_scm.return_value.commit = self.commit
        self.mocked_scm.return_value.repository_root = "git://pkgs.stg.fedoraproject.org/modules/"

    def checkout(self, temp_dir):
        scm_dir = path.join(temp_dir, self.name)
        mkdir(scm_dir)
        base_dir = path.abspath(path.dirname(__file__))
        copyfile(path.join(base_dir, '..', 'staged_data', self.mmd_filename),
                    path.join(scm_dir, self.mmd_filename))

        return scm_dir

    def get_latest(self, branch = 'master'):
        return branch

class TestModuleBuilder(GenericBuilder):
    """
    Test module builder which succeeds for every build.
    """

    backend = "mock"
    # Global build_id/task_id we increment when new build is executed.
    _build_id = 1

    BUILD_STATE = "COMPLETE"
    INSTANT_COMPLETE = False

    on_build_cb = None
    on_cancel_cb = None
    on_buildroot_add_artifacts_cb = None
    on_tag_artifacts_cb = None

    @module_build_service.utils.validate_koji_tag('tag_name')
    def __init__(self, owner, module, config, tag_name, components):
        self.module_str = module
        self.tag_name = tag_name
        self.config = config

    @classmethod
    def reset(cls):
        TestModuleBuilder.BUILD_STATE = "COMPLETE"
        TestModuleBuilder.INSTANT_COMPLETE = False
        TestModuleBuilder.on_build_cb = None
        TestModuleBuilder.on_cancel_cb = None
        TestModuleBuilder.on_buildroot_add_artifacts_cb = None
        TestModuleBuilder.on_tag_artifacts_cb = None

    def buildroot_connect(self, groups):
        default_groups = {
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
            raise ValueError("Wrong groups in TestModuleBuilder.buildroot_connect()")

    def buildroot_prep(self):
        pass

    def buildroot_resume(self):
        pass

    def buildroot_ready(self, artifacts=None):
        return True

    def buildroot_add_dependency(self, dependencies):
        pass

    def buildroot_add_artifacts(self, artifacts, install=False):
        if TestModuleBuilder.on_buildroot_add_artifacts_cb:
            TestModuleBuilder.on_buildroot_add_artifacts_cb(self, artifacts, install)
        self._send_repo_done()

    def buildroot_add_repos(self, dependencies):
        pass

    def tag_artifacts(self, artifacts):
        if TestModuleBuilder.on_tag_artifacts_cb:
            TestModuleBuilder.on_tag_artifacts_cb(self, artifacts)

    @property
    def module_build_tag(self):
        return {"name": self.tag_name + "-build"}

    def _send_repo_done(self):
        msg = module_build_service.messaging.KojiRepoChange(
            msg_id='a faked internal message',
            repo_tag=self.tag_name + "-build",
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
        print "Starting building artifact %s: %s" % (artifact_name, source)

        TestModuleBuilder._build_id += 1

        if TestModuleBuilder.BUILD_STATE != "BUILDING":
            self._send_build_change(
                koji.BUILD_STATES[TestModuleBuilder.BUILD_STATE], source,
                TestModuleBuilder._build_id)

        if TestModuleBuilder.on_build_cb:
            TestModuleBuilder.on_build_cb(self, artifact_name, source)

        if TestModuleBuilder.INSTANT_COMPLETE:
            state = koji.BUILD_STATES['COMPLETE']
        else:
            state = koji.BUILD_STATES['BUILDING']

        reason = "Submitted %s to Koji" % (artifact_name)
        return TestModuleBuilder._build_id, state, reason, None

    @staticmethod
    def get_disttag_srpm(disttag):
        # @FIXME
        return KojiModuleBuilder.get_disttag_srpm(disttag)

    def cancel_build(self, task_id):
        if TestModuleBuilder.on_cancel_cb:
            TestModuleBuilder.on_cancel_cb(self, task_id)

    def list_tasks_for_components(self, component_builds=None, state='active'):
        pass


@patch("module_build_service.config.Config.system", 
        new_callable=PropertyMock, return_value = "mock")
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
        GenericBuilder.register_backend_class(TestModuleBuilder)
        self.client = app.test_client()

        init_data()
        models.ModuleBuild.query.delete()
        models.ComponentBuild.query.delete()

        filename = cassette_dir + self.id()
        self.vcr = vcr.use_cassette(filename)
        self.vcr.__enter__()

    def tearDown(self):
        TestModuleBuilder.reset()

        # Necessary to restart the twisted reactor for the next test.
        import sys
        del sys.modules['twisted.internet.reactor']
        del sys.modules['moksha.hub.reactor']
        del sys.modules['moksha.hub']
        import moksha.hub.reactor
        self.vcr.__exit__()

    @timed(30)
    @patch('module_build_service.auth.get_user', return_value=user)
    @patch('module_build_service.scm.SCM')
    def test_submit_build(self, mocked_scm, mocked_get_user, conf_system, dbg):
        """
        Tests the build of testmodule.yaml using TestModuleBuilder which
        succeeds everytime.
        """
        MockedSCM(mocked_scm, 'testmodule', 'testmodule.yaml',
                  '620ec77321b2ea7b0d67d82992dda3e1d67055b4')

        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'branch': 'master', 'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#68932c90de214d9d13feefbd35246a81b6cb8d49'}))

        data = json.loads(rv.data)
        module_build_id = data['id']

        # Check that components are tagged after the batch is built.
        tag_groups = []
        tag_groups.append([u'perl-Tangerine?#f25-1-1', u'perl-List-Compare?#f25-1-1'])
        tag_groups.append([u'tangerine?#f25-1-1'])

        def on_tag_artifacts_cb(cls, artifacts):
            self.assertEqual(tag_groups.pop(0), artifacts)

        TestModuleBuilder.on_tag_artifacts_cb = on_tag_artifacts_cb

        # Check that the components are added to buildroot after the batch
        # is built.
        buildroot_groups = []
        buildroot_groups.append([u'module-build-macros-0.1-1.module_fc4ed5f7.src.rpm-1-1'])
        buildroot_groups.append([u'perl-Tangerine?#f25-1-1', u'perl-List-Compare?#f25-1-1'])
        buildroot_groups.append([u'tangerine?#f25-1-1'])

        def on_buildroot_add_artifacts_cb(cls, artifacts, install):
            self.assertEqual(buildroot_groups.pop(0), artifacts)

        TestModuleBuilder.on_buildroot_add_artifacts_cb = on_buildroot_add_artifacts_cb

        msgs = []
        stop = module_build_service.scheduler.make_simple_stop_condition(db.session)
        module_build_service.scheduler.main(msgs, stop)

        # All components should be built and module itself should be in "done"
        # or "ready" state.
        for build in models.ComponentBuild.query.filter_by(module_id=module_build_id).all():
            self.assertEqual(build.state, koji.BUILD_STATES['COMPLETE'])
            self.assertTrue(build.module_build.state in [models.BUILD_STATES["done"], models.BUILD_STATES["ready"]] )

        # All components has to be tagged, so tag_groups and buildroot_groups are empty...
        self.assertEqual(tag_groups, [])
        self.assertEqual(buildroot_groups, [])

    @timed(30)
    @patch('module_build_service.auth.get_user', return_value=user)
    @patch('module_build_service.scm.SCM')
    def test_submit_build_from_yaml(self, mocked_scm, mocked_get_user, conf_system, dbg):
        MockedSCM(mocked_scm, "testmodule", "testmodule.yaml")

        testmodule = os.path.join(base_dir, 'staged_data', 'testmodule.yaml')
        with open(testmodule) as f:
            yaml = f.read()

        def submit():
            rv = self.client.post('/module-build-service/1/module-builds/',
                                  content_type='multipart/form-data',
                                  data={'yaml': (testmodule, yaml)})
            return json.loads(rv.data)

        with patch("module_build_service.config.Config.yaml_submit_allowed",
                new_callable=PropertyMock, return_value = True):
            conf.set_item("yaml_submit_allowed", True)
            data = submit()
            self.assertEqual(data['id'], 1)

        with patch("module_build_service.config.Config.yaml_submit_allowed",
                new_callable=PropertyMock, return_value = False):
            data = submit()
            self.assertEqual(data['status'], 403)
            self.assertEqual(data['message'], 'YAML submission is not enabled')

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
        MockedSCM(mocked_scm, 'testmodule', 'testmodule.yaml',
                  '620ec77321b2ea7b0d67d82992dda3e1d67055b4')

        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'branch': 'master', 'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#68932c90de214d9d13feefbd35246a81b6cb8d49'}))

        data = json.loads(rv.data)
        module_build_id = data['id']

        # This callback is called before return of TestModuleBuilder.build()
        # method. We just cancel the build here using the web API to simulate
        # user cancelling the build in the middle of building.
        def on_build_cb(cls, artifact_name, source):
            self.client.patch(
                '/module-build-service/1/module-builds/' + str(module_build_id),
                data=json.dumps({'state': 'failed'}))

        cancelled_tasks = []
        def on_cancel_cb(cls, task_id):
            cancelled_tasks.append(task_id)

        # We do not want the builds to COMPLETE, but instead we want them
        # to be in the BULDING state after the TestModuleBuilder.build().
        TestModuleBuilder.BUILD_STATE = "BUILDING"
        TestModuleBuilder.on_build_cb = on_build_cb
        TestModuleBuilder.on_cancel_cb = on_cancel_cb

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
        Tests the build of testmodule.yaml using TestModuleBuilder which
        succeeds everytime.
        """
        MockedSCM(mocked_scm, 'testmodule', 'testmodule.yaml',
                  '620ec77321b2ea7b0d67d82992dda3e1d67055b4')

        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'branch': 'master', 'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#68932c90de214d9d13feefbd35246a81b6cb8d49'}))

        data = json.loads(rv.data)
        module_build_id = data['id']

        TestModuleBuilder.BUILD_STATE = "BUILDING"
        TestModuleBuilder.INSTANT_COMPLETE = True

        msgs = []
        stop = module_build_service.scheduler.make_simple_stop_condition(db.session)
        module_build_service.scheduler.main(msgs, stop)

        # All components should be built and module itself should be in "done"
        # or "ready" state.
        for build in models.ComponentBuild.query.filter_by(module_id=module_build_id).all():
            self.assertEqual(build.state, koji.BUILD_STATES['COMPLETE'])
            self.assertTrue(build.module_build.state in [models.BUILD_STATES["done"], models.BUILD_STATES["ready"]] )

    @timed(30)
    @patch('module_build_service.auth.get_user', return_value=user)
    @patch('module_build_service.scm.SCM')
    @patch("module_build_service.config.Config.num_consecutive_builds", 
           new_callable=PropertyMock, return_value = 1)
    def test_submit_build_concurrent_threshold(self, conf_num_consecutive_builds,
                                               mocked_scm, mocked_get_user,
                                               conf_system, dbg):
        """
        Tests the build of testmodule.yaml using TestModuleBuilder with
        num_consecutive_builds set to 1.
        """
        MockedSCM(mocked_scm, 'testmodule', 'testmodule.yaml',
                  '620ec77321b2ea7b0d67d82992dda3e1d67055b4')

        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'branch': 'master', 'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#68932c90de214d9d13feefbd35246a81b6cb8d49'}))

        data = json.loads(rv.data)
        module_build_id = data['id']

        def stop(message):
            """
            Stop the scheduler when the module is built or when we try to build
            more components than the num_consecutive_builds.
            """
            main_stop = module_build_service.scheduler.make_simple_stop_condition(db.session)
            over_threshold = conf.num_consecutive_builds < \
                db.session.query(models.ComponentBuild).filter_by(
                state=koji.BUILD_STATES['BUILDING']).count()
            return main_stop(message) or over_threshold

        msgs = []
        module_build_service.scheduler.main(msgs, stop)

        # All components should be built and module itself should be in "done"
        # or "ready" state.
        for build in models.ComponentBuild.query.filter_by(module_id=module_build_id).all():
            self.assertEqual(build.state, koji.BUILD_STATES['COMPLETE'])
            # When this fails, it can mean that num_consecutive_builds
            # threshold has been met.
            self.assertTrue(build.module_build.state in [models.BUILD_STATES["done"], models.BUILD_STATES["ready"]] )

    @timed(30)
    @patch('module_build_service.auth.get_user', return_value=user)
    @patch('module_build_service.scm.SCM')
    @patch("module_build_service.config.Config.num_consecutive_builds",
           new_callable=PropertyMock, return_value = 2)
    def test_try_to_reach_concurrent_threshold(self, conf_num_consecutive_builds,
                                               mocked_scm, mocked_get_user,
                                               conf_system, dbg):
        """
        Tests that we try to submit new component build right after
        the previous one finished without waiting for all 
        the num_consecutive_builds to finish.
        """
        MockedSCM(mocked_scm, 'testmodule-more-components', 'testmodule-more-components.yaml',
                  '620ec77321b2ea7b0d67d82992dda3e1d67055b4')

        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'branch': 'master', 'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#68932c90de214d9d13feefbd35246a81b6cb8d49'}))

        data = json.loads(rv.data)
        module_build_id = data['id']

        # Holds the number of concurrent component builds during
        # the module build.
        TestBuild._global_var = []

        def stop(message):
            """
            Stop the scheduler when the module is built or when we try to build
            more components than the num_consecutive_builds.
            """
            main_stop = module_build_service.scheduler.make_simple_stop_condition(db.session)
            num_building = db.session.query(models.ComponentBuild).filter_by(
                state=koji.BUILD_STATES['BUILDING']).count()
            over_threshold = conf.num_consecutive_builds < num_building
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
        # If we are building single component more often, num_consecutive_builds
        # does not work correctly.
        num_builds = [k for k, g in itertools.groupby(TestBuild._global_var)]
        self.assertEqual(num_builds.count(1), 2)

    @timed(30)
    @patch('module_build_service.auth.get_user', return_value=user)
    @patch('module_build_service.scm.SCM')
    @patch("module_build_service.config.Config.num_consecutive_builds",
           new_callable=PropertyMock, return_value = 1)
    def test_build_in_batch_fails(self, conf_num_consecutive_builds, mocked_scm,
                                  mocked_get_user, conf_system, dbg):
        """
        Tests that if the build in batch fails, other components in a batch
        are still build, but next batch is not started.
        """
        MockedSCM(mocked_scm, 'testmodule', 'testmodule.yaml',
                  '620ec77321b2ea7b0d67d82992dda3e1d67055b4')

        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'branch': 'master', 'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#68932c90de214d9d13feefbd35246a81b6cb8d49'}))

        data = json.loads(rv.data)
        module_build_id = data['id']

        def on_build_cb(cls, artifact_name, source):
            # Next component *after* the module-build-macros will fail
            # to build.
            if artifact_name.startswith("module-build-macros"):
                TestModuleBuilder.BUILD_STATE = "FAILED"
            else:
                TestModuleBuilder.BUILD_STATE = "COMPLETE"
            print artifact_name

        TestModuleBuilder.on_build_cb = on_build_cb

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
    @patch("module_build_service.config.Config.num_consecutive_builds",
           new_callable=PropertyMock, return_value = 1)
    def test_all_builds_in_batch_fail(self, conf_num_consecutive_builds, mocked_scm,
                                  mocked_get_user, conf_system, dbg):
        """
        Tests that if the build in batch fails, other components in a batch
        are still build, but next batch is not started.
        """
        MockedSCM(mocked_scm, 'testmodule', 'testmodule.yaml',
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
                TestModuleBuilder.BUILD_STATE = "FAILED"

        TestModuleBuilder.on_build_cb = on_build_cb

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
