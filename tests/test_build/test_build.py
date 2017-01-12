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
from module_build_service import db, models, conf
from module_build_service.messaging import RidaModule

from mock import patch

from tests import app, init_data
import json

from module_build_service.builder import KojiModuleBuilder, GenericBuilder
import module_build_service.scheduler.consumer

base_dir = dirname(dirname(__file__))
cassette_dir = base_dir + '/vcr-request-data/'

class MockedSCM(object):
    def __init__(self, mocked_scm, name, mmd_filename):
        self.mocked_scm = mocked_scm
        self.name = name
        self.mmd_filename = mmd_filename

        self.mocked_scm.return_value.checkout = self.checkout
        self.mocked_scm.return_value.name = self.name
        self.mocked_scm.return_value.get_latest = self.get_latest
        self.mocked_scm.return_value.repository_root = "git://pkgs.stg.fedoraproject.org/modules/"

    def checkout(self, temp_dir):
        scm_dir = path.join(temp_dir, self.name)
        mkdir(scm_dir)
        base_dir = path.abspath(path.dirname(__file__))
        copyfile(path.join(base_dir, self.mmd_filename),
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

    def __init__(self, owner, module, config, tag_name):
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

    def buildroot_add_repos(self, dependencies):
        pass

    def tag_artifacts(self, artifacts):
        if TestModuleBuilder.on_tag_artifacts_cb:
            TestModuleBuilder.on_tag_artifacts_cb(self, artifacts)
        self._send_repo_done()

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


class TestBuild(unittest.TestCase):

    def setUp(self):
        GenericBuilder.register_backend_class(TestModuleBuilder)
        self.client = app.test_client()
        self._prev_system = conf.system
        self._prev_num_consencutive_builds = conf.num_consecutive_builds

        conf.set_item("system", "mock")

        init_data()
        models.ModuleBuild.query.delete()
        models.ComponentBuild.query.delete()

        filename = cassette_dir + self.id()
        self.vcr = vcr.use_cassette(filename)
        self.vcr.__enter__()

    def tearDown(self):
        conf.set_item("system", self._prev_system)
        conf.set_item("num_consecutive_builds", self._prev_num_consencutive_builds)
        TestModuleBuilder.reset()

        # Necessary to restart the twisted reactor for the next test.
        import sys
        del sys.modules['twisted.internet.reactor']
        del sys.modules['moksha.hub.reactor']
        del sys.modules['moksha.hub']
        import moksha.hub.reactor
        self.vcr.__exit__()

    @timed(30)
    @patch('module_build_service.auth.get_username', return_value='Homer J. Simpson')
    @patch('module_build_service.auth.assert_is_packager')
    @patch('module_build_service.scm.SCM')
    def test_submit_build(self, mocked_scm, mocked_assert_is_packager,
                          mocked_get_username):
        """
        Tests the build of testmodule.yaml using TestModuleBuilder which
        succeeds everytime.
        """
        MockedSCM(mocked_scm, "testmodule", "testmodule.yaml")

        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#68932c90de214d9d13feefbd35246a81b6cb8d49'}))

        data = json.loads(rv.data)
        module_build_id = data['id']

        # Check that components are tagged after the batch is built.
        tag_groups = []
        tag_groups.append([u'module-build-macros-0.1-1.module_testmodule_teststream_1.src.rpm-1-1'])
        tag_groups.append([u'perl-Tangerine?#f25-1-1', u'perl-List-Compare?#f25-1-1'])
        tag_groups.append([u'tangerine?#f25-1-1'])

        def on_tag_artifacts_cb(cls, artifacts):
            self.assertEqual(tag_groups.pop(0), artifacts)

        TestModuleBuilder.on_tag_artifacts_cb = on_tag_artifacts_cb

        # Check that the components are added to buildroot after the batch
        # is built.
        buildroot_groups = []
        buildroot_groups.append([u'module-build-macros-0.1-1.module_testmodule_teststream_1.src.rpm-1-1'])
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
    @patch('module_build_service.auth.get_username', return_value='Homer J. Simpson')
    @patch('module_build_service.auth.assert_is_packager')
    @patch('module_build_service.scm.SCM')
    def test_submit_build_cancel(self, mocked_scm, mocked_assert_is_packager,
                          mocked_get_username):
        """
        Submit all builds for a module and cancel the module build later.
        """
        MockedSCM(mocked_scm, "testmodule", "testmodule.yaml")

        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
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
    @patch('module_build_service.auth.get_username', return_value='Homer J. Simpson')
    @patch('module_build_service.auth.assert_is_packager')
    @patch('module_build_service.scm.SCM')
    def test_submit_build_instant_complete(self, mocked_scm, mocked_assert_is_packager,
                          mocked_get_username):
        """
        Tests the build of testmodule.yaml using TestModuleBuilder which
        succeeds everytime.
        """
        MockedSCM(mocked_scm, "testmodule", "testmodule.yaml")

        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
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
    @patch('module_build_service.auth.get_username', return_value='Homer J. Simpson')
    @patch('module_build_service.auth.assert_is_packager')
    @patch('module_build_service.scm.SCM')
    def test_submit_build_concurrent_threshold(
            self, mocked_scm, mocked_assert_is_packager, mocked_get_username):
        """
        Tests the build of testmodule.yaml using TestModuleBuilder with
        num_consecutive_builds set to 1.
        """
        MockedSCM(mocked_scm, "testmodule", "testmodule.yaml")

        conf.set_item("num_consecutive_builds", 1)

        rv = self.client.post('/module-build-service/1/module-builds/', data=json.dumps(
            {'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/'
                'testmodule.git?#68932c90de214d9d13feefbd35246a81b6cb8d49'}))

        data = json.loads(rv.data)
        module_build_id = data['id']

        msgs = []
        stop = module_build_service.scheduler.make_simple_stop_condition(db.session)
        module_build_service.scheduler.main(msgs, stop)

        # All components should be built and module itself should be in "done"
        # or "ready" state.
        for build in models.ComponentBuild.query.filter_by(module_id=module_build_id).all():
            self.assertEqual(build.state, koji.BUILD_STATES['COMPLETE'])
            self.assertTrue(build.module_build.state in [models.BUILD_STATES["done"], models.BUILD_STATES["ready"]] )
