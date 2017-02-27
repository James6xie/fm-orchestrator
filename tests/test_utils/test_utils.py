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
from os import path
import vcr
import modulemd
from mock import patch
import module_build_service.utils
import module_build_service.scm
from module_build_service import models
from module_build_service.errors import ProgrammingError, ValidationError
from tests import test_resuse_component_init_data, db

BASE_DIR = path.abspath(path.dirname(__file__))
CASSETTES_DIR = path.join(
    path.abspath(path.dirname(__file__)), '..', 'vcr-request-data')


class TestUtils(unittest.TestCase):

    @vcr.use_cassette(
        path.join(CASSETTES_DIR, 'tests.test_utils.TestUtils.test_format_mmd'))
    @patch('module_build_service.scm.SCM')
    def test_format_mmd(self, mocked_scm):
        mocked_scm.return_value.commit = \
            '620ec77321b2ea7b0d67d82992dda3e1d67055b4'
        # For all the RPMs in testmodule, get_latest is called
        mocked_scm.return_value.get_latest.side_effect = [
            '4ceea43add2366d8b8c5a622a2fb563b625b9abf',
            'fbed359411a1baa08d4a88e0d12d426fbf8f602c',
            '76f9d8c8e87eed0aab91034b01d3d5ff6bd5b4cb']
        mmd = modulemd.ModuleMetadata()
        with open(path.join(BASE_DIR, '..', 'staged_data', 'testmodule.yaml')) \
                as mmd_file:
            mmd.loads(mmd_file)
        scmurl = \
            ('git://pkgs.stg.fedoraproject.org/modules/testmodule.git'
             '?#620ec77321b2ea7b0d67d82992dda3e1d67055b4')
        module_build_service.utils.format_mmd(mmd, scmurl)
        self.assertEqual(mmd.buildrequires, {'base-runtime': 'master'})
        self.assertEqual(mmd.components.rpms['perl-Tangerine'].ref,
                         '4ceea43add2366d8b8c5a622a2fb563b625b9abf')
        self.assertEqual(mmd.components.rpms['tangerine'].ref,
                         'fbed359411a1baa08d4a88e0d12d426fbf8f602c')
        self.assertEqual(mmd.components.rpms['perl-List-Compare'].ref,
                         '76f9d8c8e87eed0aab91034b01d3d5ff6bd5b4cb')
        xmd = {
            'mbs': {
                'commit': '620ec77321b2ea7b0d67d82992dda3e1d67055b4',
                'buildrequires': {
                    'base-runtime': {
                        'ref': 'ae993ba84f4bce554471382ccba917ef16265f11',
                        'stream': 'master',
                        'version': '3'}},
                'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/testmodule'
                          '.git?#620ec77321b2ea7b0d67d82992dda3e1d67055b4',
            }
        }
        self.assertEqual(mmd.xmd, xmd)

    def test_get_reusable_component_same(self):
        test_resuse_component_init_data()
        new_module = models.ModuleBuild.query.filter_by(id=2).one()
        rv = module_build_service.utils.get_reusable_component(
            db.session, new_module, 'tangerine')
        self.assertEqual(rv.package, 'tangerine')

    def test_get_reusable_component_different_perl_tangerine(self):
        test_resuse_component_init_data()
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
        test_resuse_component_init_data()
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
        test_resuse_component_init_data()
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

        @module_build_service.utils.validate_koji_tag('wrong_tag_arg')
        def validate_koji_tag_programming_error(good_tag_arg, other_arg):
            pass

        with self.assertRaises(ProgrammingError):
            validate_koji_tag_programming_error('dummy', 'other_val')

    def test_validate_koji_tag_bad_tag_value(self):

        @module_build_service.utils.validate_koji_tag('tag_arg')
        def validate_koji_tag_bad_tag_value(tag_arg):
            pass

        with self.assertRaises(ValidationError):
            validate_koji_tag_bad_tag_value('forbiddentagprefix-foo')

    def test_validate_koji_tag_bad_tag_value_in_list(self):

        @module_build_service.utils.validate_koji_tag('tag_arg')
        def validate_koji_tag_bad_tag_value_in_list(tag_arg):
            pass

        with self.assertRaises(ValidationError):
            validate_koji_tag_bad_tag_value_in_list([
                'module-foo', 'forbiddentagprefix-bar'])

    def test_validate_koji_tag_good_tag_value(self):

        @module_build_service.utils.validate_koji_tag('tag_arg')
        def validate_koji_tag_good_tag_value(tag_arg):
            return True

        self.assertEquals(
            validate_koji_tag_good_tag_value('module-foo'), True)

    def test_validate_koji_tag_good_tag_values_in_list(self):

        @module_build_service.utils.validate_koji_tag('tag_arg')
        def validate_koji_tag_good_tag_values_in_list(tag_arg):
            return True

        self.assertEquals(
            validate_koji_tag_good_tag_values_in_list(['module-foo',
                                                       'module-bar']), True)
