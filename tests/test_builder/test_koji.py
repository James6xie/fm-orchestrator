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
import munch
import mock
import koji
import xmlrpclib

import module_build_service.messaging
import module_build_service.scheduler.handlers.repos
import module_build_service.models
import module_build_service.builder

from mock import patch

from tests import conf

from module_build_service.builder import KojiModuleBuilder


class TestKojiBuilder(unittest.TestCase):

    def setUp(self):
        self.config = mock.Mock()
        self.config.koji_profile = conf.koji_profile
        self.config.koji_repository_url = conf.koji_repository_url

    def test_tag_to_repo(self):
        """ Test that when a repo msg hits us and we have no match,
        that we do nothing gracefully.
        """
        repo = module_build_service.builder.GenericBuilder.tag_to_repo(
            "koji", self.config,
            "module-base-runtime-0.25-9",
            "x86_64")
        self.assertEquals(repo, "https://kojipkgs.stg.fedoraproject.org/repos"
                          "/module-base-runtime-0.25-9/latest/x86_64")

    @patch('koji.util')
    def test_buildroot_ready(self, mocked_kojiutil):

        attrs = {'checkForBuilds.return_value': None,
                 'checkForBuilds.side_effect': IOError}
        mocked_kojiutil.configure_mock(**attrs)
        fake_kmb = FakeKojiModuleBuilder(owner='Moe Szyslak',
                                         module='nginx',
                                         config=conf,
                                         tag_name='module-nginx-1.2')
        fake_kmb.module_target = {'build_tag': 'fake_tag'}

        with self.assertRaises(IOError):
            fake_kmb.buildroot_ready()
        self.assertEquals(mocked_kojiutil.checkForBuilds.call_count, 3)


class TestGetKojiClientSession(unittest.TestCase):

    def setUp(self):
        self.config = mock.Mock()
        self.config.koji_profile = conf.koji_profile
        self.config.koji_config = conf.koji_config
        self.owner = 'Matt Jia'
        self.module = 'fool'
        self.tag_name = 'module-fool-1.2'

    @patch.object(koji.ClientSession, 'krb_login')
    def test_proxyuser(self, mocked_krb_login):
        KojiModuleBuilder(owner=self.owner,
                          module=self.module,
                          config=self.config,
                          tag_name=self.tag_name)
        args, kwargs = mocked_krb_login.call_args
        self.assertTrue(set([('proxyuser', self.owner)]).issubset(set(kwargs.items())))


class FakeKojiModuleBuilder(KojiModuleBuilder):

    @module_build_service.utils.retry(wait_on=(xmlrpclib.ProtocolError, koji.GenericError))
    def get_session(self, config, owner):
        koji_config = munch.Munch(koji.read_config(
            profile_name=config.koji_profile,
            user_config=config.koji_config,
        ))

        address = koji_config.server

        koji_session = FakeKojiSession(address, opts=koji_config)

        return koji_session


class FakeKojiSession(koji.ClientSession):

    def _callMethod(self, name, args, kwargs=None):
        pass

    def _setup_connection(self):
        pass

    def getRepo(self, tag):
        return {'create_event': 'fake event'}
