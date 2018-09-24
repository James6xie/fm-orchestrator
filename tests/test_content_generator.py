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
# Written by Stanislav Ochotnicky <sochotnicky@redhat.com>
#            Jan Kaluza <jkaluza@redhat.com>

import pytest
import json

import os
from os import path

import module_build_service.messaging
import module_build_service.scheduler.handlers.repos # noqa
from module_build_service import models, conf, build_logs, Modulemd

from mock import patch, Mock, MagicMock, call, mock_open
import kobo.rpmlib

from tests import init_data

from module_build_service.builder.KojiContentGenerator import KojiContentGenerator

GET_USER_RV = {
    "id": 3686,
    "krb_principal": "mszyslak@FEDORAPROJECT.ORG",
    "name": "Moe Szyslak",
    "status": 0,
    "usertype": 0
}


class TestBuild:

    def setup_method(self, test_method):
        init_data(1, contexts=True)
        module = models.ModuleBuild.query.filter_by(id=2).one()
        module.cg_build_koji_tag = "f27-module-candidate"
        self.cg = KojiContentGenerator(module, conf)

        # Ensure that there is no build log from other tests
        try:
            file_path = build_logs.path(self.cg.module)
            os.remove(file_path)
        except OSError:
            pass

    def teardown_method(self, test_method):
        # Necessary to restart the twisted reactor for the next test.
        import sys
        del sys.modules['twisted.internet.reactor']
        del sys.modules['moksha.hub.reactor']
        del sys.modules['moksha.hub']
        import moksha.hub.reactor # noqa
        try:
            file_path = build_logs.path(self.cg.module)
            os.remove(file_path)
        except OSError:
            pass

    @patch("module_build_service.builder.KojiContentGenerator.get_session")
    @patch("subprocess.Popen")
    @patch("subprocess.check_output", return_value='1.4')
    @patch("pkg_resources.get_distribution")
    @patch("platform.linux_distribution")
    @patch("platform.machine")
    @patch(("module_build_service.builder.KojiContentGenerator.KojiContentGenerator."
           "_koji_rpms_in_tag"))
    def test_get_generator_json(self, rpms_in_tag, machine, distro, pkg_res, coutput, popen,
                                get_session):
        """ Test generation of content generator json """
        koji_session = MagicMock()
        koji_session.getUser.return_value = GET_USER_RV
        koji_session.getTag.return_value = {"arches": ""}
        get_session.return_value = koji_session
        distro.return_value = ("Fedora", "25", "Twenty Five")
        machine.return_value = "i686"
        pkg_res.return_value = Mock()
        pkg_res.return_value.version = "current-tested-version"
        rpm_mock = Mock()
        rpm_out = "rpm-name;1.0;r1;x86_64;(none);sigmd5:1;sigpgp:p;siggpg:g\n" \
                  "rpm-name-2;2.0;r2;i686;1;sigmd5:2;sigpgp:p2;siggpg:g2"
        attrs = {'communicate.return_value': (rpm_out, 'error'),
                 'wait.return_value': 0}
        rpm_mock.configure_mock(**attrs)
        popen.return_value = rpm_mock

        tests_dir = path.abspath(path.dirname(__file__))
        rpm_in_tag_path = path.join(tests_dir,
                                    "test_get_generator_json_rpms_in_tag.json")
        with open(rpm_in_tag_path) as rpms_in_tag_file:
            rpms_in_tag.return_value = json.load(rpms_in_tag_file)

        expected_output_path = path.join(tests_dir,
                                         "test_get_generator_json_expected_output_with_log.json")
        with open(expected_output_path) as expected_output_file:
            expected_output = json.load(expected_output_file)

        # create the build.log
        build_logs.start(self.cg.module)
        build_logs.stop(self.cg.module)

        self.cg._load_koji_tag(koji_session)
        file_dir = self.cg._prepare_file_directory()
        ret = self.cg._get_content_generator_metadata(file_dir)
        rpms_in_tag.assert_called_once()
        assert expected_output == ret

    @patch("module_build_service.builder.KojiContentGenerator.get_session")
    @patch("subprocess.Popen")
    @patch("subprocess.check_output", return_value='1.4')
    @patch("pkg_resources.get_distribution")
    @patch("platform.linux_distribution")
    @patch("platform.machine")
    @patch(("module_build_service.builder.KojiContentGenerator.KojiContentGenerator."
           "_koji_rpms_in_tag"))
    def test_get_generator_json_no_log(self, rpms_in_tag, machine, distro, pkg_res, coutput, popen,
                                       get_session):
        """ Test generation of content generator json """
        koji_session = MagicMock()
        koji_session.getUser.return_value = GET_USER_RV
        koji_session.getTag.return_value = {"arches": ""}
        get_session.return_value = koji_session
        distro.return_value = ("Fedora", "25", "Twenty Five")
        machine.return_value = "i686"
        pkg_res.return_value = Mock()
        pkg_res.return_value.version = "current-tested-version"
        rpm_mock = Mock()
        rpm_out = "rpm-name;1.0;r1;x86_64;(none);sigmd5:1;sigpgp:p;siggpg:g\n" \
                  "rpm-name-2;2.0;r2;i686;1;sigmd5:2;sigpgp:p2;siggpg:g2"
        attrs = {'communicate.return_value': (rpm_out, 'error'),
                 'wait.return_value': 0}
        rpm_mock.configure_mock(**attrs)
        popen.return_value = rpm_mock

        tests_dir = path.abspath(path.dirname(__file__))
        rpm_in_tag_path = path.join(tests_dir,
                                    "test_get_generator_json_rpms_in_tag.json")
        with open(rpm_in_tag_path) as rpms_in_tag_file:
            rpms_in_tag.return_value = json.load(rpms_in_tag_file)

        expected_output_path = path.join(tests_dir,
                                         "test_get_generator_json_expected_output.json")
        with open(expected_output_path) as expected_output_file:
            expected_output = json.load(expected_output_file)
        self.cg._load_koji_tag(koji_session)
        file_dir = self.cg._prepare_file_directory()
        ret = self.cg._get_content_generator_metadata(file_dir)
        rpms_in_tag.assert_called_once()
        assert expected_output == ret

    def test_prepare_file_directory(self):
        """ Test preparation of directory with output files """
        dir_path = self.cg._prepare_file_directory()
        with open(path.join(dir_path, "modulemd.txt")) as mmd:
            assert len(mmd.read()) == 1134

    def test_prepare_file_directory_per_arch_mmds(self):
        """ Test preparation of directory with output files """
        self.cg.arches = ["x86_64", "i686"]
        dir_path = self.cg._prepare_file_directory()
        with open(path.join(dir_path, "modulemd.txt")) as mmd:
            assert len(mmd.read()) == 1134

        with open(path.join(dir_path, "modulemd.x86_64.txt")) as mmd:
            assert len(mmd.read()) == 257

        with open(path.join(dir_path, "modulemd.i686.txt")) as mmd:
            assert len(mmd.read()) == 255

    @patch("module_build_service.builder.KojiContentGenerator.get_session")
    def test_tag_cg_build(self, get_session):
        """ Test that the CG build is tagged. """
        koji_session = MagicMock()
        koji_session.getUser.return_value = GET_USER_RV
        koji_session.getTag.return_value = {'id': 123}
        get_session.return_value = koji_session

        self.cg._tag_cg_build()

        koji_session.getTag.assert_called_once_with(self.cg.module.cg_build_koji_tag)
        koji_session.tagBuild.assert_called_once_with(123, "nginx-0-2.10e50d06")

    @patch("module_build_service.builder.KojiContentGenerator.get_session")
    def test_tag_cg_build_fallback_to_default_tag(self, get_session):
        """ Test that the CG build is tagged to default tag. """
        koji_session = MagicMock()
        koji_session.getUser.return_value = GET_USER_RV
        koji_session.getTag.side_effect = [{}, {'id': 123}]
        get_session.return_value = koji_session

        self.cg._tag_cg_build()

        assert koji_session.getTag.mock_calls == [
            call(self.cg.module.cg_build_koji_tag),
            call(conf.koji_cg_default_build_tag)]
        koji_session.tagBuild.assert_called_once_with(123, "nginx-0-2.10e50d06")

    @patch("module_build_service.builder.KojiContentGenerator.get_session")
    def test_tag_cg_build_no_tag_set(self, get_session):
        """ Test that the CG build is not tagged when no tag set. """
        koji_session = MagicMock()
        koji_session.getUser.return_value = GET_USER_RV
        koji_session.getTag.side_effect = [{}, {'id': 123}]
        get_session.return_value = koji_session

        self.cg.module.cg_build_koji_tag = None
        self.cg._tag_cg_build()

        koji_session.tagBuild.assert_not_called()

    @patch("module_build_service.builder.KojiContentGenerator.get_session")
    def test_tag_cg_build_no_tag_available(self, get_session):
        """ Test that the CG build is not tagged when no tag available. """
        koji_session = MagicMock()
        koji_session.getUser.return_value = GET_USER_RV
        koji_session.getTag.side_effect = [{}, {}]
        get_session.return_value = koji_session

        self.cg._tag_cg_build()

        koji_session.tagBuild.assert_not_called()

    @patch("module_build_service.builder.KojiContentGenerator.open", create=True)
    def test_get_arch_mmd_output(self, patched_open):
        patched_open.return_value = mock_open(
            read_data=self.cg.mmd).return_value
        ret = self.cg._get_arch_mmd_output("./fake-dir", "x86_64")
        assert ret == {
            'arch': 'x86_64',
            'buildroot_id': 1,
            'checksum': 'bf1615b15f6a0fee485abe94af6b56b6',
            'checksum_type': 'md5',
            'components': [],
            'extra': {'typeinfo': {'module': {}}},
            'filename': 'modulemd.x86_64.txt',
            'filesize': 1134,
            'type': 'file'
        }

    @patch("module_build_service.builder.KojiContentGenerator.open", create=True)
    def test_get_arch_mmd_output_components(self, patched_open):
        mmd = self.cg.module.mmd()
        rpm_artifacts = mmd.get_rpm_artifacts()
        rpm_artifacts.add("dhcp-libs-12:4.3.5-5.module_2118aef6.x86_64")
        mmd.set_rpm_artifacts(rpm_artifacts)
        mmd_data = mmd.dumps()

        patched_open.return_value = mock_open(
            read_data=mmd_data).return_value

        self.cg.rpms = [{
            "name": "dhcp",
            "version": "4.3.5",
            "release": "5.module_2118aef6",
            "arch": "x86_64",
            "epoch": "12",
            "payloadhash": "hash",
        }]

        self.cg.rpms_dict = {
            "dhcp-libs-12:4.3.5-5.module_2118aef6.x86_64": {
                "name": "dhcp",
                "version": "4.3.5",
                "release": "5.module_2118aef6",
                "arch": "x86_64",
                "epoch": "12",
                "payloadhash": "hash",
            }
        }

        ret = self.cg._get_arch_mmd_output("./fake-dir", "x86_64")
        assert ret == {
            'arch': 'x86_64',
            'buildroot_id': 1,
            'checksum': '1bcc38b6f19285b3656b84a0443f46d2',
            'checksum_type': 'md5',
            'components': [{u'arch': 'x86_64',
                            u'epoch': '12',
                            u'name': 'dhcp',
                            u'release': '5.module_2118aef6',
                            u'sigmd5': 'hash',
                            u'type': u'rpm',
                            u'version': '4.3.5'}],
            'extra': {'typeinfo': {'module': {}}},
            'filename': 'modulemd.x86_64.txt',
            'filesize': 315,
            'type': 'file'
        }

    @patch("module_build_service.builder.KojiContentGenerator.get_session")
    def test_koji_rpms_in_tag(self, get_session):
        koji_session = MagicMock()
        koji_session.getUser.return_value = GET_USER_RV
        koji_session.getTag.return_value = {"arches": "x86_64"}

        rpms = [
            {
                'id': 1,
                'arch': 'src',
                'build_id': 875991,
                'name': 'module-build-macros',
                'release': '1.module_92011fe6',
                'version': '0.1'
            },
            {
                'id': 2,
                'arch': 'noarch',
                'build_id': 875991,
                'name': 'module-build-macros',
                'release': '1.module_92011fe6',
                'version': '0.1'
            },
            {
                'id': 3,
                'arch': 'src',
                'build_id': 875636,
                'name': 'ed',
                'release': '2.module_bd6e0eb1',
                'version': '1.14.1'
            },
            {
                'id': 4,
                'arch': 'x86_64',
                'build_id': 875636,
                'name': 'ed',
                'release': '2.module_bd6e0eb1',
                'version': '1.14.1'
            },
        ]

        builds = [
            {
                'build_id': 875636,
                'name': 'ed',
                'release': '2.module_bd6e0eb1',
                'version': '1.14.1',
                'nvr': 'ed-2.module_bd6e0eb1-1.14.1',
            },
            {
                'build_id': 875991,
                'name': 'module-build-macros',
                'release': '1.module_92011fe6',
                'version': '0.1',
                'nvr': 'module-build-macros-0.1-1.module_92011fe6',
            }
        ]

        koji_session.listTaggedRPMS.return_value = (rpms, builds)
        koji_session.multiCall.side_effect = [
            # getRPMHeaders response
            [[{'excludearch': ["x86_64"], 'exclusivearch': [], 'license': 'MIT'}],
             [{'excludearch': [], 'exclusivearch': ["x86_64"], 'license': 'GPL'}],
             [{'license': 'MIT'}],
             [{'license': 'GPL'}]]
        ]
        get_session.return_value = koji_session

        rpms = self.cg._koji_rpms_in_tag("tag")
        for rpm in rpms:
            # We want to mainly check the excludearch and exclusivearch code.
            if rpm["name"] == "module-build-macros":
                assert rpm["excludearch"] == ["x86_64"]
                assert rpm["license"] == "MIT"
            else:
                assert rpm["exclusivearch"] == ["x86_64"]
                assert rpm["license"] == "GPL"

    def _add_test_rpm(self, nevra, srpm_name=None, multilib=None,
                      koji_srpm_name=None, excludearch=None, exclusivearch=None,
                      license=None):
        """
        Helper method to add test RPM to ModuleBuild used by KojiContentGenerator
        and also to Koji tag used to generate the Content Generator build.

        :param str nevra: NEVRA of the RPM to add.
        :param str srpm_name: Name of SRPM the added RPM is built from.
        :param list multilib: List of architecture for which the multilib should be turned on.
        :param str koji_srpm_name: If set, overrides the `srpm_name` in Koji tag. This is
            needed to test the case when the built "src" package has different name than
            the package in Koji. This is for example case of software collections where
            `srpm_name` is "httpd" but `koji_srpm_name` would be "httpd24-httpd".
        :param list excludearch: List of architectures this package is excluded from.
        :param list exclusivearch: List of architectures this package is exclusive for.
        :param str license: License of this RPM.
        """
        parsed_nevra = kobo.rpmlib.parse_nvra(nevra)
        parsed_nevra["payloadhash"] = "hash"
        if koji_srpm_name:
            parsed_nevra["srpm_name"] = koji_srpm_name
        else:
            parsed_nevra["srpm_name"] = srpm_name
        parsed_nevra["excludearch"] = excludearch or []
        parsed_nevra["exclusivearch"] = exclusivearch or []
        parsed_nevra["license"] = license or ""
        self.cg.rpms.append(parsed_nevra)
        self.cg.rpms_dict[nevra] = parsed_nevra

        mmd = self.cg.module.mmd()
        if srpm_name not in mmd.get_rpm_components().keys():
            component = Modulemd.ComponentRpm()
            component.set_name(srpm_name)
            component.set_rationale("foo")

            if multilib:
                multilib_set = Modulemd.SimpleSet()
                for arch in multilib:
                    multilib_set.add(arch)
                component.set_multilib(multilib_set)

            mmd.add_rpm_component(component)
            self.cg.module.modulemd = mmd.dumps()
            self.cg.modulemd = mmd.dumps()

    def test_fill_in_rpms_list(self):
        self._add_test_rpm("dhcp-libs-12:4.3.5-5.module_2118aef6.x86_64", "dhcp")
        self._add_test_rpm("dhcp-libs-12:4.3.5-5.module_2118aef6.i686", "dhcp")
        self._add_test_rpm("perl-Tangerine-12:4.3.5-5.module_2118aef6.x86_64", "perl-Tangerine")
        self._add_test_rpm("perl-Tangerine-12:4.3.5-5.module_2118aef6.i686", "perl-Tangerine")

        mmd = self.cg.module.mmd()
        mmd = self.cg._fill_in_rpms_list(mmd, "x86_64")

        # Only x86_64 packages should be filled in, because we requested x86_64 arch.
        assert set(mmd.get_rpm_artifacts().get()) == set([
            "dhcp-libs-12:4.3.5-5.module_2118aef6.x86_64",
            "perl-Tangerine-12:4.3.5-5.module_2118aef6.x86_64"])

    def test_fill_in_rpms_exclusivearch(self):
        self._add_test_rpm("dhcp-libs-12:4.3.5-5.module_2118aef6.noarch", "dhcp",
                           exclusivearch=["x86_64"])
        self._add_test_rpm("perl-Tangerine-12:4.3.5-5.module_2118aef6.noarch", "perl-Tangerine",
                           exclusivearch=["ppc64le"])

        mmd = self.cg.module.mmd()
        mmd = self.cg._fill_in_rpms_list(mmd, "x86_64")

        # Only dhcp-libs should be filled in, because perl-Tangerine has different
        # exclusivearch.
        assert set(mmd.get_rpm_artifacts().get()) == set([
            "dhcp-libs-12:4.3.5-5.module_2118aef6.noarch"])

    def test_fill_in_rpms_excludearch(self):
        self._add_test_rpm("dhcp-libs-12:4.3.5-5.module_2118aef6.noarch", "dhcp",
                           excludearch=["x86_64"])
        self._add_test_rpm("perl-Tangerine-12:4.3.5-5.module_2118aef6.noarch", "perl-Tangerine",
                           excludearch=["ppc64le"])

        mmd = self.cg.module.mmd()
        mmd = self.cg._fill_in_rpms_list(mmd, "x86_64")

        # Only perl-Tangerine should be filled in, because dhcp-libs is excluded from x86_64.
        assert set(mmd.get_rpm_artifacts().get()) == set([
            "perl-Tangerine-12:4.3.5-5.module_2118aef6.noarch"])

    def test_fill_in_rpms_rpm_whitelist(self):
        self._add_test_rpm("dhcp-libs-12:4.3.5-5.module_2118aef6.x86_64", "dhcp",
                           koji_srpm_name="python27-dhcp")
        self._add_test_rpm("dhcp-libs-12:4.3.5-5.module_2118aef6.i686", "dhcp",
                           koji_srpm_name="python27-dhcp")
        self._add_test_rpm("perl-Tangerine-12:4.3.5-5.module_2118aef6.x86_64", "perl-Tangerine",
                           koji_srpm_name="foo-perl-Tangerine")
        self._add_test_rpm("perl-Tangerine-12:4.3.5-5.module_2118aef6.i686", "perl-Tangerine",
                           koji_srpm_name="foo-perl-Tangerine")

        mmd = self.cg.module.mmd()
        opts = mmd.get_buildopts()
        opts.set_rpm_whitelist(["python27-dhcp"])
        mmd.set_buildopts(opts)

        mmd = self.cg._fill_in_rpms_list(mmd, "x86_64")

        # Only x86_64 dhcp-libs should be filled in, because only python27-dhcp is whitelisted
        # srpm name.
        assert set(mmd.get_rpm_artifacts().get()) == set([
            "dhcp-libs-12:4.3.5-5.module_2118aef6.x86_64"])

    def test_fill_in_rpms_list_filters(self):
        self._add_test_rpm("dhcp-libs-12:4.3.5-5.module_2118aef6.x86_64", "dhcp")
        self._add_test_rpm("dhcp-libs-12:4.3.5-5.module_2118aef6.i686", "dhcp")
        self._add_test_rpm("perl-Tangerine-12:4.3.5-5.module_2118aef6.x86_64", "perl-Tangerine")
        self._add_test_rpm("perl-Tangerine-12:4.3.5-5.module_2118aef6.i686", "perl-Tangerine")

        mmd = self.cg.module.mmd()
        filter_list = Modulemd.SimpleSet()
        filter_list.add("dhcp-libs")
        mmd.set_rpm_filter(filter_list)

        mmd = self.cg._fill_in_rpms_list(mmd, "x86_64")

        # Only x86_64 perl-Tangerine should be filled in, because dhcp-libs is filtered out.
        assert set(mmd.get_rpm_artifacts().get()) == set([
            "perl-Tangerine-12:4.3.5-5.module_2118aef6.x86_64"])

    def test_fill_in_rpms_list_multilib(self):
        self._add_test_rpm("dhcp-libs-12:4.3.5-5.module_2118aef6.x86_64", "dhcp",
                           multilib=["x86_64"])
        self._add_test_rpm("dhcp-libs-12:4.3.5-5.module_2118aef6.i686", "dhcp",
                           multilib=["x86_64"])
        self._add_test_rpm("perl-Tangerine-12:4.3.5-5.module_2118aef6.x86_64", "perl-Tangerine",
                           multilib=["ppc64le"])
        self._add_test_rpm("perl-Tangerine-12:4.3.5-5.module_2118aef6.i686", "perl-Tangerine",
                           multilib=["ppc64le"])

        mmd = self.cg.module.mmd()
        mmd = self.cg._fill_in_rpms_list(mmd, "x86_64")

        # Only i686 package for dhcp-libs should be added, because perl-Tangerine does not have
        # multilib set.
        assert set(mmd.get_rpm_artifacts().get()) == set([
            "dhcp-libs-12:4.3.5-5.module_2118aef6.x86_64",
            "dhcp-libs-12:4.3.5-5.module_2118aef6.i686",
            "perl-Tangerine-12:4.3.5-5.module_2118aef6.x86_64"])

    @pytest.mark.parametrize(
        "licenses, expected", (
            (["GPL", "MIT"], ["GPL", "MIT"]),
            (["GPL", ""], ["GPL"]),
            (["GPL", "GPL"], ["GPL"]),
        )
    )
    def test_fill_in_rpms_list_license(self, licenses, expected):
        self._add_test_rpm("dhcp-libs-12:4.3.5-5.module_2118aef6.x86_64", "dhcp",
                           license=licenses[0])
        self._add_test_rpm("dhcp-libs-12:4.3.5-5.module_2118aef6.i686", "dhcp")
        self._add_test_rpm("perl-Tangerine-12:4.3.5-5.module_2118aef6.x86_64", "perl-Tangerine",
                           license=licenses[1])
        self._add_test_rpm("perl-Tangerine-12:4.3.5-5.module_2118aef6.i686", "perl-Tangerine")

        mmd = self.cg.module.mmd()
        mmd = self.cg._fill_in_rpms_list(mmd, "x86_64")

        # Only x86_64 packages should be filled in, because we requested x86_64 arch.
        assert set(mmd.get_content_licenses().get()) == set(expected)
