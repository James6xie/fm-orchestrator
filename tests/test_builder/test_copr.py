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
# Written by Jakub Kadlcik <jkadlcik@redhat.com>


import os
import unittest
import mock
import module_build_service.models
import module_build_service.builder
from munch import Munch
from tests import conf, init_data
from module_build_service.builder.CoprModuleBuilder import CoprModuleBuilder
from copr import CoprClient
from copr.exceptions import CoprRequestException


@unittest.skip("We need not yet released version of python-copr. Let's skip this for some time")
class TestCoprBuilder(unittest.TestCase):

    def setUp(self):
        self.config = mock.Mock()
        self.config.copr_config = None

    @mock.patch("copr.CoprClient.get_module_repo")
    def test_tag_to_repo(self, get_module_repo):
        # Mock the CoprClient.get_module_repo to return something, without requesting a Copr instance
        def get_module_repo_mock(owner, nvr):
            return ResponseMock({
                "output": "ok",
                "repo": "http://copr-be-instance/results/{}/{}/modules".format(owner, nvr)
            })
        get_module_repo.side_effect = get_module_repo_mock

        repo = module_build_service.builder.GenericBuilder.tag_to_repo(
            "copr", self.config, "foo-module-name-0.25-9", None)
        self.assertEquals(repo, "http://copr-be-instance/results/@copr/foo-module-name-0.25-9/modules")

    @mock.patch("copr.CoprClient.get_module_repo")
    def test_non_existing_tag_to_repo(self, get_module_repo):
        # Let's pretend that CoprClient.get_module_repo couldn't find the project on Copr instance
        get_module_repo.return_value = ResponseMock({"output": "notok", "error": "some error"})
        self.assertRaises(ValueError,
                          lambda: module_build_service.builder.GenericBuilder.tag_to_repo(
                              "copr", self.config, None, None))


class ResponseMock(object):
    def __init__(self, data):
        self._data = data

    @property
    def data(self):
        return self._data


class FakeCoprAPI(object):
    @staticmethod
    def get_project_details():
        return ResponseMock({
            "output": "ok",
            "name": "someproject",
            # ...
        })

    @staticmethod
    def get_chroot():
        return ResponseMock({
            "output": "ok",
            "chroot": {
                "repos": "http://repo1.ex/ http://repo2.ex/",
                "buildroot_pkgs": "pkg1 pkg2 pkg3"
            }
        })


COPR_MODULE_BUILDER = "module_build_service.builder.CoprModuleBuilder.CoprModuleBuilder"


class TestCoprModuleBuilder(unittest.TestCase):

    def setUp(self):
        init_data()
        self.config = mock.Mock()
        self.config.koji_profile = conf.koji_profile
        self.config.koji_repository_url = conf.koji_repository_url
        self.module = module_build_service.models.ModuleBuild.query.filter_by(id=1).one()


    @mock.patch("copr.client.CoprClient.create_from_file_config")
    def create_builder(self, create_from_file_config):
        builder = CoprModuleBuilder(owner=self.module.owner,
                                    module=self.module,
                                    config=conf,
                                    tag_name='module-nginx-1.2',
                                    components=[])
        builder.client = CoprClient(username="myself", login="", token="", copr_url="http://example.com/")
        builder.copr = Munch(projectname="someproject", username="myself")
        return builder

    ####################################################################################################################
    #                                                                                                                  #
    #  ModuleBuilder common operations                                                                                 #
    #  e.g. finalizing the module build process                                                                        #
    #                                                                                                                  #
    ####################################################################################################################

    @mock.patch("copr.client.CoprClient.make_module")
    def test_finalize(self, make_module):
        builder = self.create_builder()
        builder.finalize()
        args, kwargs = make_module.call_args
        make_module.assert_called_with(username="myself", projectname="someproject",
                                       modulemd=mock.ANY, create=False, build=True)
        self.assertIsInstance(kwargs["modulemd"], str)
        self.assertTrue(os.path.isabs(kwargs["modulemd"]))

    ####################################################################################################################
    #                                                                                                                  #
    #  ModuleBuilder operations for connecting to the buildroot                                                        #
    #  e.g. creating copr projects and modules in it                                                                   #
    #                                                                                                                  #
    ####################################################################################################################

    @mock.patch(COPR_MODULE_BUILDER + "._update_chroot")
    @mock.patch(COPR_MODULE_BUILDER + "._get_copr_safe")
    @mock.patch(COPR_MODULE_BUILDER + "._create_module_safe")
    def test_buildroot_connect(self, create_module_safe, get_copr_safe, update_chroot):
        builder = self.create_builder()
        groups = {"build": {"pkgname1", "pkgname2", "pkgname3"}}
        builder.buildroot_connect(groups)
        args, kwargs = update_chroot.call_args
        self.assertEquals(set(kwargs["packages"]), {"pkgname1", "pkgname2", "pkgname3"})
        self.assertEqual(builder._CoprModuleBuilder__prep, True)

    @mock.patch(COPR_MODULE_BUILDER + "._get_copr")
    @mock.patch(COPR_MODULE_BUILDER + "._create_copr")
    @mock.patch("copr.client.CoprClient.create_project")  # So that python-copr-1.79-1 is not required
    def test_get_copr_safe(self, create_project, create_copr, get_copr):
        builder = self.create_builder()

        builder._get_copr_safe()
        get_copr.assert_called_with(ownername=self.module.owner, projectname="module-nginx-1.2")
        create_copr.assert_not_called()

        get_copr.reset_mock()
        create_copr.reset_mock()

        get_copr.side_effect = [CoprRequestException(), mock.DEFAULT]
        builder._get_copr_safe()
        get_copr.assert_called_with(ownername=self.module.owner, projectname="module-nginx-1.2")
        create_copr.assert_called_with(ownername=self.module.owner, projectname="module-nginx-1.2")
        self.assertEqual(get_copr.call_count, 2)

    @mock.patch("copr.client.CoprClient._fetch", return_value=FakeCoprAPI.get_project_details())
    def test_get_copr(self, get_project_details):
        builder = self.create_builder()
        copr = builder._get_copr("myself", "someproject")
        self.assertEqual(copr.username, "myself")
        self.assertEqual(copr.projectname , "someproject")

    @mock.patch("copr.client.CoprClient.create_project")
    def test_create_copr(self, create_project):
        builder = self.create_builder()
        builder._create_copr("myself", "someproject")
        create_project.called_with("myself", "someproject", ["custom-1-x86_64"])

    @mock.patch("copr.client.CoprClient.make_module")
    def test_create_module_safe(self, make_module):
        builder = self.create_builder()
        builder._create_module_safe()
        make_module.assert_called_with(username=self.module.owner, projectname="module-nginx-1.2",
                                       modulemd=mock.ANY, create=True, build=False)
        args, kwargs = make_module.call_args
        self.assertIsInstance(kwargs["modulemd"], str)
        self.assertTrue(os.path.isabs(kwargs["modulemd"]))

    def test_buildroot_ready(self):
        builder = self.create_builder()
        self.assertTrue(builder.buildroot_ready(artifacts=["a1", "a2", "a3"]))

    ####################################################################################################################
    #                                                                                                                  #
    #  ModuleBuilder operations with buildroot                                                                         #
    #  e.g. adding repositories and packages into the buildroot                                                        #
    #                                                                                                                  #
    ####################################################################################################################

    @mock.patch("copr.client.CoprClient.get_chroot", return_value=FakeCoprAPI.get_chroot())
    @mock.patch("copr.client.CoprClient.edit_chroot")
    def test_buildroot_update_chroot(self, edit_chroot, get_chroot):
        builder = self.create_builder()

        # @TODO Have deterministic and reasonable order of values
        # Update buildroot packages
        builder._update_chroot(packages=["pkg4", "pkg5"])
        edit_chroot.assert_called_with("someproject", "custom-1-x86_64", ownername="myself",
                                       repos=mock.ANY, packages=mock.ANY)
        args, kwargs = edit_chroot.call_args
        self.assertEqual(set(kwargs["packages"].split()), {"pkg1", "pkg2", "pkg3", "pkg4", "pkg5"})
        self.assertEqual(set(kwargs["repos"].split()), {"http://repo1.ex/", "http://repo2.ex/"})

        # Update buildroot repos
        builder._update_chroot(repos=["http://repo3.ex/"])
        edit_chroot.assert_called_with("someproject", "custom-1-x86_64", ownername="myself",
                                       repos=mock.ANY, packages=mock.ANY)
        args, kwargs = edit_chroot.call_args
        self.assertEqual(set(kwargs["packages"].split()), {"pkg1", "pkg2", "pkg3"})
        self.assertEqual(set(kwargs["repos"].split()), {"http://repo1.ex/", "http://repo2.ex/", "http://repo3.ex/"})

        # Update multiple buildroot options at the same time
        builder._update_chroot(packages=["pkg4", "pkg5"], repos=["http://repo3.ex/"])
        edit_chroot.assert_called_with("someproject", "custom-1-x86_64", ownername="myself",
                                       repos=mock.ANY, packages=mock.ANY)
        args, kwargs = edit_chroot.call_args
        self.assertEqual(set(kwargs["packages"].split()), {"pkg1", "pkg2", "pkg3", "pkg4", "pkg5"})
        self.assertEqual(set(kwargs["repos"].split()), {"http://repo1.ex/", "http://repo2.ex/", "http://repo3.ex/"})

    def test_buildroot_add_artifacts(self):
        pass

    @mock.patch(COPR_MODULE_BUILDER + "._update_chroot")
    def test_buildroot_add_repos(self, update_chroot):
        builder = self.create_builder()
        builder.buildroot_add_repos(["foo", "bar", "baz"])
        args, kwargs = update_chroot.call_args
        self.assertEquals(set(kwargs["repos"]), {
            conf.koji_repository_url + "/foo/latest/x86_64",
            conf.koji_repository_url + "/bar/latest/x86_64",
            conf.koji_repository_url + "/baz/latest/x86_64",

            # We always add this repo as a workaround, see the code for details
            "https://kojipkgs.fedoraproject.org/compose/latest-Fedora-Modular-26/compose/Server/x86_64/os/",
        })

    ####################################################################################################################
    #                                                                                                                  #
    #  ModuleBuilder package build operations                                                                          #
    #  e.g. building a package from SCM or SRPM                                                                        #
    #                                                                                                                  #
    ####################################################################################################################

    @mock.patch(COPR_MODULE_BUILDER + ".build_srpm")
    @mock.patch(COPR_MODULE_BUILDER + ".build_scm")
    def test_build(self, build_scm, build_srpm):
        builder = self.create_builder()
        builder._CoprModuleBuilder__prep = True

        def reset_mock():
            build_scm.reset_mock()
            build_srpm.reset_mock()

        builder.build("pkgname", "git://repo.ex/pkgname.git")
        build_scm.assert_called_with("git://repo.ex/pkgname.git")
        build_srpm.assert_not_called()
        reset_mock()

        builder.build("pkgname", "http://repo.ex/pkgname.git")
        build_scm.assert_called_with("http://repo.ex/pkgname.git")
        build_srpm.assert_not_called()
        reset_mock()

        builder.build("pkgname", "https://repo.ex/pkgname.git")
        build_scm.assert_called_with("https://repo.ex/pkgname.git")
        build_srpm.assert_not_called()
        reset_mock()

        builder.build("pkgname", "/path/to/pkgname.src.rpm")
        build_scm.assert_not_called()
        build_srpm.assert_called_with("pkgname", "/path/to/pkgname.src.rpm")
        reset_mock()

    @mock.patch("copr.client.CoprClient.create_new_build")
    def test_build_srpm(self, create_new_build):
        builder = self.create_builder()
        builder.build_srpm("pkgname", "git://repo.ex/pkgname.git")
        create_new_build.assert_called_with("someproject", ["git://repo.ex/pkgname.git"],
                                            chroots=["custom-1-x86_64"], username="myself")

    def test_build_scm(self):
        pass
