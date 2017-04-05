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

from os.path import dirname
import unittest
import mock
import vcr

from mock import patch

import module_build_service.messaging
import module_build_service.scheduler.handlers.repos
import module_build_service.models
from tests import test_reuse_component_init_data
from tests import conf, db, app

import koji

class TestTagTagged(unittest.TestCase):

    def setUp(self):
        test_reuse_component_init_data()

    def tearDown(self):
        pass

    @mock.patch('module_build_service.models.ModuleBuild.from_tag_change_event')
    def test_no_matching_module(self, from_tag_change_event):
        """ Test that when a tag msg hits us and we have no match,
        that we do nothing gracefully.
        """
        from_tag_change_event.return_value = None
        msg = module_build_service.messaging.KojiTagChange(
            'no matches for this...', '2016-some-nonexistent-build', "artifact")
        module_build_service.scheduler.handlers.tags.tagged(
            config=conf, session=db.session, msg=msg)

    def test_no_matching_artifact(self):
        """ Test that when a tag msg hits us and we have no match,
        that we do nothing gracefully.
        """
        msg = module_build_service.messaging.KojiTagChange(
            'id', 'module-testmodule-build', "artifact")
        module_build_service.scheduler.handlers.tags.tagged(
            config=conf, session=db.session, msg=msg)


    @patch("module_build_service.builder.GenericBuilder.default_buildroot_groups",
        return_value = {'build': [], 'srpm-build': []})
    @patch("module_build_service.builder.KojiModuleBuilder.get_session")
    @patch("module_build_service.builder.GenericBuilder.create_from_module")
    def test_newrepo(self, create_builder, koji_get_session, dbg):
        """
        Test that newRepo is called in the expected times.
        """
        koji_session = mock.MagicMock()
        koji_session.getTag = lambda tag_name: {'name': tag_name}
        koji_session.getTaskInfo.return_value = {'state': koji.TASK_STATES['CLOSED']}
        koji_session.newRepo.return_value = 123456
        koji_get_session.return_value = koji_session

        builder = mock.MagicMock()
        builder.koji_session = koji_session
        builder.buildroot_ready.return_value = False
        create_builder.return_value = builder

        module_build = module_build_service.models.ModuleBuild.query.filter_by(id=2).one()
        module_build.batch = 2
        db.session.commit()

        # Tag the first component to the buildroot.
        msg = module_build_service.messaging.KojiTagChange(
            'id', 'module-testmodule-build', "perl-Tangerine")
        module_build_service.scheduler.handlers.tags.tagged(
            config=conf, session=db.session, msg=msg)

        # newRepo should not be called, because there are still components
        # to tag.
        self.assertTrue(not koji_session.newRepo.called)

        # Tag the second component to the buildroot.
        msg = module_build_service.messaging.KojiTagChange(
            'id', 'module-testmodule-build', "perl-List-Compare")
        module_build_service.scheduler.handlers.tags.tagged(
            config=conf, session=db.session, msg=msg)

        # newRepo should be called now - all components have been tagged.
        koji_session.newRepo.assert_called_once_with("module-testmodule-build")

        # Refresh our module_build object.
        db.session.expunge(module_build)
        module_build = module_build_service.models.ModuleBuild.query.filter_by(id=2).one()

        # newRepo task_id should be stored in database, so we can check its
        # status later in poller.
        self.assertEqual(module_build.new_repo_task_id, 123456)
