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

import unittest
from os import path, mkdir
from shutil import copyfile
import vcr
import modulemd
from mock import patch
import module_build_service.utils
import module_build_service.scm
from module_build_service import models, conf
from module_build_service.errors import ProgrammingError, ValidationError
from tests import test_reuse_component_init_data, init_data, db
import mock
from mock import PropertyMock
import koji
import module_build_service.scheduler.handlers.components
from module_build_service.builder import GenericBuilder, KojiModuleBuilder
from tests import app

BASE_DIR = path.abspath(path.dirname(__file__))
CASSETTES_DIR = path.join(
    path.abspath(path.dirname(__file__)), '..', 'vcr-request-data')

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
                    path.join(scm_dir, self.name + ".yaml"))

        return scm_dir

    def get_latest(self, branch = 'master'):
        return self.commit if self.commit else branch

class TestUtils(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        init_data()

    @vcr.use_cassette(
        path.join(CASSETTES_DIR, 'tests.test_utils.TestUtils.test_format_mmd'))
    @patch('module_build_service.scm.SCM')
    def test_format_mmd(self, mocked_scm):
        mocked_scm.return_value.commit = \
            '620ec77321b2ea7b0d67d82992dda3e1d67055b4'
        # For all the RPMs in testmodule, get_latest is called
        hashes_returned = [
            '4ceea43add2366d8b8c5a622a2fb563b625b9abf',
            'fbed359411a1baa08d4a88e0d12d426fbf8f602c',
            '76f9d8c8e87eed0aab91034b01d3d5ff6bd5b4cb']
        mocked_scm.return_value.get_latest.side_effect = hashes_returned
        mmd = modulemd.ModuleMetadata()
        with open(path.join(BASE_DIR, '..', 'staged_data', 'testmodule.yaml')) \
                as mmd_file:
            mmd.loads(mmd_file)
        scmurl = \
            ('git://pkgs.stg.fedoraproject.org/modules/testmodule.git'
             '?#620ec77321b2ea7b0d67d82992dda3e1d67055b4')
        module_build_service.utils.format_mmd(mmd, scmurl)

        # Make sure all the commit hashes were properly set on the RPMs
        for i, pkg in enumerate(mmd.components.rpms.values()):
            self.assertEqual(
                pkg.ref, hashes_returned[i])

        self.assertEqual(mmd.buildrequires, {'base-runtime': 'master'})
        xmd = {
            'mbs': {
                'commit': '620ec77321b2ea7b0d67d82992dda3e1d67055b4',
                'buildrequires': {
                    'base-runtime': {
                        'ref': 'abffed45ca33d7fe94fff8253b5bfe1d87e786b2',
                        'stream': 'master',
                        'version': '20170315134803'}},
                'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/testmodule'
                          '.git?#620ec77321b2ea7b0d67d82992dda3e1d67055b4',
            }
        }
        self.assertEqual(mmd.xmd, xmd)

    def test_get_reusable_component_same(self):
        test_reuse_component_init_data()
        new_module = models.ModuleBuild.query.filter_by(id=2).one()
        rv = module_build_service.utils.get_reusable_component(
            db.session, new_module, 'tangerine')
        self.assertEqual(rv.package, 'tangerine')

    def test_get_reusable_component_different_perl_tangerine(self):
        test_reuse_component_init_data()
        second_module_build = models.ModuleBuild.query.filter_by(id=2).one()
        mmd = second_module_build.mmd()
        mmd.components.rpms['perl-Tangerine'].ref = \
            '00ea1da4192a2030f9ae023de3b3143ed647bbab'
        second_module_build.modulemd = mmd.dumps()
        second_module_perl_tangerine = models.ComponentBuild.query.filter_by(
            package='perl-Tangerine', module_id=2).one()
        second_module_perl_tangerine.ref = \
            '00ea1da4192a2030f9ae023de3b3143ed647bbab'
        db.session.commit()
        # Shares the same build order as the changed perl-Tangerine, but none
        # of the build orders before it are different (in this case there are
        # none)
        plc_rv = module_build_service.utils.get_reusable_component(
            db.session, second_module_build, 'perl-List-Compare')
        self.assertEqual(plc_rv.package, 'perl-List-Compare')

        # perl-Tangerine has a different commit hash
        pt_rv = module_build_service.utils.get_reusable_component(
            db.session, second_module_build, 'perl-Tangerine')
        self.assertEqual(pt_rv, None)

        # tangerine is the same but its in a build order that is after the
        # different perl-Tangerine, so it can't be reused
        tangerine_rv = module_build_service.utils.get_reusable_component(
            db.session, second_module_build, 'tangerine')
        self.assertEqual(tangerine_rv, None)

    def test_get_reusable_component_different_buildrequires_hash(self):
        test_reuse_component_init_data()
        second_module_build = models.ModuleBuild.query.filter_by(id=2).one()
        mmd = second_module_build.mmd()
        mmd.xmd['mbs']['buildrequires']['base-runtime']['ref'] = \
            'da39a3ee5e6b4b0d3255bfef95601890afd80709'
        second_module_build.modulemd = mmd.dumps()
        db.session.commit()

        plc_rv = module_build_service.utils.get_reusable_component(
            db.session, second_module_build, 'perl-List-Compare')
        self.assertEqual(plc_rv, None)

        # perl-Tangerine has a different commit hash
        pt_rv = module_build_service.utils.get_reusable_component(
            db.session, second_module_build, 'perl-Tangerine')
        self.assertEqual(pt_rv, None)

        # tangerine is the same but its in a build order that is after the
        # different perl-Tangerine, so it can't be reused
        tangerine_rv = module_build_service.utils.get_reusable_component(
            db.session, second_module_build, 'tangerine')
        self.assertEqual(tangerine_rv, None)

    def test_get_reusable_component_different_buildrequires(self):
        test_reuse_component_init_data()
        second_module_build = models.ModuleBuild.query.filter_by(id=2).one()
        mmd = second_module_build.mmd()
        mmd.buildrequires = {'some_module': 'master'}
        mmd.xmd['mbs']['buildrequires'] = {
            'some_module': {
                'ref': 'da39a3ee5e6b4b0d3255bfef95601890afd80709',
                'stream': 'master',
                'version': '20170123140147'
            }
        }
        second_module_build.modulemd = mmd.dumps()
        db.session.commit()

        plc_rv = module_build_service.utils.get_reusable_component(
            db.session, second_module_build, 'perl-List-Compare')
        self.assertEqual(plc_rv, None)

        # perl-Tangerine has a different commit hash
        pt_rv = module_build_service.utils.get_reusable_component(
            db.session, second_module_build, 'perl-Tangerine')
        self.assertEqual(pt_rv, None)

        # tangerine is the same but its in a build order that is after the
        # different perl-Tangerine, so it can't be reused
        tangerine_rv = module_build_service.utils.get_reusable_component(
            db.session, second_module_build, 'tangerine')
        self.assertEqual(tangerine_rv, None)

    def test_validate_koji_tag_wrong_tag_arg_during_programming(self):
        """ Test that we fail on a wrong param name (non-existing one) due to
        programming error. """

        @module_build_service.utils.validate_koji_tag('wrong_tag_arg')
        def validate_koji_tag_programming_error(good_tag_arg, other_arg):
            pass

        with self.assertRaises(ProgrammingError):
            validate_koji_tag_programming_error('dummy', 'other_val')

    def test_validate_koji_tag_bad_tag_value(self):
        """ Test that we fail on a bad tag value. """

        @module_build_service.utils.validate_koji_tag('tag_arg')
        def validate_koji_tag_bad_tag_value(tag_arg):
            pass

        with self.assertRaises(ValidationError):
            validate_koji_tag_bad_tag_value('forbiddentagprefix-foo')

    def test_validate_koji_tag_bad_tag_value_in_list(self):
        """ Test that we fail on a list containing bad tag value. """

        @module_build_service.utils.validate_koji_tag('tag_arg')
        def validate_koji_tag_bad_tag_value_in_list(tag_arg):
            pass

        with self.assertRaises(ValidationError):
            validate_koji_tag_bad_tag_value_in_list([
                'module-foo', 'forbiddentagprefix-bar'])

    def test_validate_koji_tag_good_tag_value(self):
        """ Test that we pass on a good tag value. """

        @module_build_service.utils.validate_koji_tag('tag_arg')
        def validate_koji_tag_good_tag_value(tag_arg):
            return True

        self.assertEquals(
            validate_koji_tag_good_tag_value('module-foo'), True)

    def test_validate_koji_tag_good_tag_values_in_list(self):
        """ Test that we pass on a list of good tag values. """

        @module_build_service.utils.validate_koji_tag('tag_arg')
        def validate_koji_tag_good_tag_values_in_list(tag_arg):
            return True

        self.assertEquals(
            validate_koji_tag_good_tag_values_in_list(['module-foo',
                                                       'module-bar']), True)

    def test_validate_koji_tag_good_tag_value_in_dict(self):
        """ Test that we pass on a dict arg with default key
        and a good value. """

        @module_build_service.utils.validate_koji_tag('tag_arg')
        def validate_koji_tag_good_tag_value_in_dict(tag_arg):
            return True

        self.assertEquals(
            validate_koji_tag_good_tag_value_in_dict({'name': 'module-foo'}), True)

    def test_validate_koji_tag_good_tag_value_in_dict_nondefault_key(self):
        """ Test that we pass on a dict arg with non-default key
        and a good value. """

        @module_build_service.utils.validate_koji_tag('tag_arg',
                                                      dict_key='nondefault')
        def validate_koji_tag_good_tag_value_in_dict_nondefault_key(tag_arg):
            return True

        self.assertEquals(
            validate_koji_tag_good_tag_value_in_dict_nondefault_key(
               {'nondefault': 'module-foo'}), True)

    def test_validate_koji_tag_double_trouble_good(self):
        """ Test that we pass on a list of tags that are good. """

        expected = 'foo'

        @module_build_service.utils.validate_koji_tag(['tag_arg1', 'tag_arg2'])
        def validate_koji_tag_double_trouble(tag_arg1, tag_arg2):
            return expected

        actual = validate_koji_tag_double_trouble('module-1', 'module-2')
        self.assertEquals(actual, expected)

    def test_validate_koji_tag_double_trouble_bad(self):
        """ Test that we fail on a list of tags that are bad. """

        @module_build_service.utils.validate_koji_tag(['tag_arg1', 'tag_arg2'])
        def validate_koji_tag_double_trouble(tag_arg1, tag_arg2):
            pass

        with self.assertRaises(ValidationError):
            validate_koji_tag_double_trouble('module-1', 'BADNEWS-2')

    def test_validate_koji_tag_is_None(self):
        """ Test that we fail on a tag which is None. """

        @module_build_service.utils.validate_koji_tag('tag_arg')
        def validate_koji_tag_is_None(tag_arg):
            pass

        with self.assertRaises(ValidationError) as cm:
            validate_koji_tag_is_None(None)

        self.assertTrue(str(cm.exception).endswith(' No value provided.'))

    @patch('module_build_service.scm.SCM')
    def test_resubmit(self, mocked_scm):
        """
        Tests that the module resubmit reintializes the module state and
        component states properly.
        """
        MockedSCM(mocked_scm, 'testmodule', 'testmodule-bootstrap.yaml',
                        '620ec77321b2ea7b0d67d82992dda3e1d67055b4')
        with app.app_context():
            test_reuse_component_init_data()
            # Mark the module build as failed, so we can resubmit it.
            module_build = models.ModuleBuild.query.filter_by(id=2).one()
            module_build.batch = 2
            module_build.state = models.BUILD_STATES['failed']
            module_build.state_reason = "Cancelled"
            module_build.version = 1

            # Mark the components as COMPLETE/FAILED/CANCELED
            components = module_build.component_builds
            complete_component = components[0]
            complete_component.state = koji.BUILD_STATES['COMPLETE']
            failed_component = components[1]
            failed_component.state = koji.BUILD_STATES['FAILED']
            canceled_component = components[2]
            canceled_component.state = koji.BUILD_STATES['CANCELED']
            db.session.commit()

            module_build_service.utils.submit_module_build_from_scm(
                "Tom Brady", 'git://pkgs.stg.fedoraproject.org/modules/testmodule.git?#8fea453',
                'master')

            self.assertEqual(module_build.state, models.BUILD_STATES['wait'])
            self.assertEqual(module_build.batch, 0)
            self.assertEqual(module_build.state_reason, "Resubmitted by Tom Brady")
            self.assertEqual(complete_component.state, koji.BUILD_STATES['COMPLETE'])
            self.assertEqual(failed_component.state, None)
            self.assertEqual(canceled_component.state, None)

class DummyModuleBuilder(GenericBuilder):
    """
    Dummy module builder
    """

    backend = "koji"
    _build_id = 0

    TAGGED_COMPONENTS = []

    @module_build_service.utils.validate_koji_tag('tag_name')
    def __init__(self, owner, module, config, tag_name, components):
        self.module_str = module
        self.tag_name = tag_name
        self.config = config


    def buildroot_connect(self, groups):
        pass

    def buildroot_prep(self):
        pass

    def buildroot_resume(self):
        pass

    def buildroot_ready(self, artifacts=None):
        return True

    def buildroot_add_dependency(self, dependencies):
        pass

    def buildroot_add_artifacts(self, artifacts, install=False):
        DummyModuleBuilder.TAGGED_COMPONENTS += artifacts

    def buildroot_add_repos(self, dependencies):
        pass

    def tag_artifacts(self, artifacts):
        pass

    @property
    def module_build_tag(self):
        return {"name": self.tag_name + "-build"}

    def build(self, artifact_name, source):
        DummyModuleBuilder._build_id += 1
        state = koji.BUILD_STATES['COMPLETE']
        reason = "Submitted %s to Koji" % (artifact_name)
        return DummyModuleBuilder._build_id, state, reason, None

    @staticmethod
    def get_disttag_srpm(disttag):
        # @FIXME
        return KojiModuleBuilder.get_disttag_srpm(disttag)

    def cancel_build(self, task_id):
        pass

    def list_tasks_for_components(self, component_builds=None, state='active'):
        pass

@patch("module_build_service.builder.GenericBuilder.default_buildroot_groups", return_value = {'build': [], 'srpm-build': []})
class TestBatches(unittest.TestCase):

    def setUp(self):
        test_reuse_component_init_data()
        GenericBuilder.register_backend_class(DummyModuleBuilder)

    def tearDown(self):
        init_data()
        DummyModuleBuilder.TAGGED_COMPONENTS = []
        GenericBuilder.register_backend_class(KojiModuleBuilder)

    def test_start_next_batch_build_reuse(self, default_buildroot_groups):
        """
        Tests that start_next_batch_build:
           1) Increments module.batch.
           2) Can reuse all components in batch
           3) Returns proper further_work messages for reused components.
           4) Returns the fake Repo change message
           5) Handling the further_work messages lead to proper tagging of
              reused components.
        """
        module_build = models.ModuleBuild.query.filter_by(id=2).one()
        module_build.batch = 1

        builder = mock.MagicMock()
        further_work = module_build_service.utils.start_next_batch_build(
            conf, module_build, db.session, builder)

        # Batch number should increase.
        self.assertEqual(module_build.batch, 2)

        # KojiBuildChange messages in further_work should have build_new_state
        # set to COMPLETE, but the current component build state should be set
        # to BUILDING, so KojiBuildChange message handler handles the change
        # properly.
        for msg in further_work:
            if type(msg) == module_build_service.messaging.KojiBuildChange:
                self.assertEqual(msg.build_new_state, koji.BUILD_STATES['COMPLETE'])
                component_build = models.ComponentBuild.from_component_event(db.session, msg)
                self.assertEqual(component_build.state, koji.BUILD_STATES['BUILDING'])

        # When we handle these KojiBuildChange messages, MBS should tag all
        # the components just once.
        for msg in further_work:
            if type(msg) == module_build_service.messaging.KojiBuildChange:
                module_build_service.scheduler.handlers.components.complete(
                    conf, db.session, msg)

        # Since we have reused all the components in the batch, there should
        # be fake KojiRepoChange message.
        self.assertEqual(type(further_work[-1]), module_build_service.messaging.KojiRepoChange)

        # Check that packages have been tagged just once.
        self.assertEqual(len(DummyModuleBuilder.TAGGED_COMPONENTS), 2)

    def test_start_next_batch_continue(self, default_buildroot_groups):
        """
        Tests that start_next_batch_build does not start new batch when
        there are unbuilt components in the current one.
        """
        module_build = models.ModuleBuild.query.filter_by(id=2).one()
        module_build.batch = 2

        # Mark the component as BUILDING.
        building_component = module_build.current_batch()[0]
        building_component.state = koji.BUILD_STATES['BUILDING']
        db.session.commit()

        builder = mock.MagicMock()
        further_work = module_build_service.utils.start_next_batch_build(
            conf, module_build, db.session, builder)

        # Batch number should not increase.
        self.assertEqual(module_build.batch, 2)

        # Single component should be reused this time, second message is fake
        # KojiRepoChange.
        self.assertEqual(len(further_work), 2)
        self.assertEqual(further_work[0].build_name, "perl-List-Compare")

    def test_start_next_batch_build_repo_building(self, default_buildroot_groups):
        """
        Test that start_next_batch_build does not start new batch when
        builder.buildroot_ready() returns False.
        """
        module_build = models.ModuleBuild.query.filter_by(id=2).one()
        module_build.batch = 1

        builder = mock.MagicMock()
        builder.buildroot_ready.return_value = False
        further_work = module_build_service.utils.start_next_batch_build(
            conf, module_build, db.session, builder)

        # Batch number should not increase.
        self.assertEqual(module_build.batch, 1)
