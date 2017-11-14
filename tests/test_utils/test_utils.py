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
from datetime import datetime
import vcr
import modulemd
from mock import patch
import module_build_service.utils
import module_build_service.scm
from module_build_service import models, conf
from module_build_service.errors import ProgrammingError, ValidationError, UnprocessableEntity
from tests import (test_reuse_component_init_data, init_data, db,
                   test_reuse_shared_userspace_init_data)
import mock
import koji
import module_build_service.scheduler.handlers.components
from module_build_service.builder.base import GenericBuilder
from module_build_service.builder.KojiModuleBuilder import KojiModuleBuilder
from tests import app

BASE_DIR = path.abspath(path.dirname(__file__))
CASSETTES_DIR = path.join(
    path.abspath(path.dirname(__file__)), '..', 'vcr-request-data')


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
        return self.commit if self.commit else ref

    def get_module_yaml(self):
        return path.join(self.sourcedir, self.name + ".yaml")


class TestUtils(unittest.TestCase):

    def setUp(self):
        self.filtered_rpms = [
            u'glibc-utils-0:2.25-4.module_5ccf9229',
            u'glibc-benchtests-0:2.25-4.module_5ccf9229',
            u'systemd-journal-remote-0:233-3.module_5ccf9229',
            u'openldap-servers-0:2.4.44-8.module_5ccf9229',
            u'kernel-debug-devel-0:4.11.0-0.rc7.git0.1.module_5ccf9229',
            u'python-perf-0:4.11.0-0.rc7.git0.1.module_5ccf9229',
            u'kernel-tools-0:4.11.0-0.rc7.git0.1.module_5ccf9229',
            u'perf-0:4.11.0-0.rc7.git0.1.module_5ccf9229',
            u'kernel-tools-libs-devel-0:4.11.0-0.rc7.git0.1.module_5ccf9229',
            u'kernel-devel-0:4.11.0-0.rc7.git0.1.module_5ccf9229',
            u'kernel-PAE-devel-0:4.11.0-0.rc7.git0.1.module_5ccf9229',
            u'kernel-PAEdebug-devel-0:4.11.0-0.rc7.git0.1.module_5ccf9229',
            u'kernel-lpae-devel-0:4.11.0-0.rc7.git0.1.module_5ccf9229',
            u'libcroco-devel-0:0.6.11-3.module_5ccf9229',
            u'dbus-x11-1:1.11.10-2.module_5ccf9229',
            u'qgpgme-0:1.9.0-1.module_5ccf9229',
            u'qgpgme-devel-0:1.9.0-1.module_5ccf9229',
            u'python2-gpg-0:1.9.0-1.module_5ccf9229',
            u'libssh2-devel-0:1.8.0-2.module_5ccf9229',
            u'python3-test-0:3.6.0-21.module_5ccf9229',
            u'python3-debug-0:3.6.0-21.module_5ccf9229',
            u'python3-tkinter-0:3.6.0-21.module_5ccf9229',
            u'python3-tools-0:3.6.0-21.module_5ccf9229',
            u'grub2-starfield-theme-1:2.02-0.38.module_5ccf9229',
            u'libbabeltrace-devel-0:1.5.2-2.module_5ccf9229',
            u'libidn-javadoc-0:1.33-2.module_5ccf9229',
            u'libidn-java-0:1.33-2.module_5ccf9229',
            u'cyrus-sasl-sql-0:2.1.26-30.module_5ccf9229',
            u'python2-solv-0:0.6.26-1.module_5ccf9229',
            u'perl-solv-0:0.6.26-1.module_5ccf9229',
            u'python2-packaging-0:16.8-4.module_5ccf9229',
            u'freetype-demos-0:2.7.1-2.module_5ccf9229',
            u'util-linux-user-0:2.29.1-2.module_5ccf9229',
            u'syslinux-perl-0:6.04-0.2.module_5ccf9229',
            u'gnutls-utils-0:3.5.10-1.module_5ccf9229',
            u'gnutls-guile-0:3.5.10-1.module_5ccf9229',
            u'gnutls-devel-0:3.5.10-1.module_5ccf9229',
            u'gnutls-dane-0:3.5.10-1.module_5ccf9229',
            u'python-pwquality-0:1.3.0-8.module_5ccf9229',
            u'openssl-perl-1:1.1.0e-1.module_5ccf9229',
            u'glib2-fam-0:2.52.0-1.module_5ccf9229',
            u'glib2-static-0:2.52.0-1.module_5ccf9229',
            u'glib2-devel-0:2.52.0-1.module_5ccf9229',
            u'libselinux-ruby-0:2.6-2.module_5ccf9229',
            u'libselinux-python-0:2.6-2.module_5ccf9229',
            u'cmirror-0:2.02.168-4.module_5ccf9229',
            u'lvm2-cluster-standalone-0:2.02.168-4.module_5ccf9229',
            u'lvm2-dbusd-0:2.02.168-4.module_5ccf9229',
            u'lvm2-python-libs-0:2.02.168-4.module_5ccf9229',
            u'lvm2-cluster-0:2.02.168-4.module_5ccf9229',
            u'cmirror-standalone-0:2.02.168-4.module_5ccf9229',
            u'lvm2-lockd-0:2.02.168-4.module_5ccf9229',
            u'python2-pip-0:9.0.1-7.module_5ccf9229',
            u'python-magic-0:5.30-5.module_5ccf9229',
            u'cracklib-python-0:2.9.6-5.module_5ccf9229',
            u'hfsutils-x11-0:3.2.6-31.module_5ccf9229',
            u'kernel-rpm-macros-0:63-1.module_5ccf9229',
            u'cryptsetup-python-0:1.7.3-3.module_5ccf9229',
            u'python2-rpm-0:4.13.0.1-3.module_5ccf9229',
            u'rpm-cron-0:4.13.0.1-3.module_5ccf9229',
            u'texinfo-0:6.3-2.module_5ccf9229',
            u'texinfo-tex-0:6.3-2.module_5ccf9229',
            u'qt5-0:5.8.0-2.module_5ccf9229',
            u'qt5-devel-0:5.8.0-2.module_5ccf9229',
            u'qt5-rpm-macros-0:5.8.0-2.module_5ccf9229',
            u'gnupg2-smime-0:2.1.18-2.module_5ccf9229',
            u'emacs-nox-1:25.2-0.1.rc2.module_5ccf9229',
            u'emacs-terminal-1:25.2-0.1.rc2.module_5ccf9229',
            u'emacs-common-1:25.2-0.1.rc2.module_5ccf9229',
            u'emacs-1:25.2-0.1.rc2.module_5ccf9229',
            u'libverto-libevent-devel-0:0.2.6-7.module_5ccf9229',
            u'libverto-tevent-devel-0:0.2.6-7.module_5ccf9229',
            u'libverto-libevent-0:0.2.6-7.module_5ccf9229',
            u'libverto-tevent-0:0.2.6-7.module_5ccf9229',
            u'libtool-0:2.4.6-17.module_5ccf9229',
            u'libpeas-loader-python3-0:1.20.0-5.module_5ccf9229',
            u'libpeas-devel-0:1.20.0-5.module_5ccf9229',
            u'libpeas-gtk-0:1.20.0-5.module_5ccf9229',
            u'libpeas-loader-python-0:1.20.0-5.module_5ccf9229',
            u'python2-setuptools-0:34.3.0-1.module_5ccf9229',
            u'libsemanage-python-0:2.6-2.module_5ccf9229',
            u'python-libxml2-0:2.9.4-2.module_5ccf9229',
            u'krb5-server-ldap-0:1.15-9.module_5ccf9229',
            u'krb5-server-0:1.15-9.module_5ccf9229',
            u'python2-six-0:1.10.0-8.module_5ccf9229',
            u'python2-appdirs-0:1.4.0-10.module_5ccf9229',
            u'pyparsing-0:2.1.10-3.module_5ccf9229',
            u'python2-pyparsing-0:2.1.10-3.module_5ccf9229',
            u'ntsysv-0:1.9-1.module_5ccf9229',
            u'audit-0:2.7.3-1.module_5ccf9229',
            u'audit-libs-python-0:2.7.3-1.module_5ccf9229',
            u'audispd-plugins-0:2.7.3-1.module_5ccf9229',
            u'audispd-plugins-zos-0:2.7.3-1.module_5ccf9229',
            u'audit-libs-python3-0:2.7.3-1.module_5ccf9229',
            u'modeline2fb-0:2.1-40.module_5ccf9229',
            u'msghack-0:0.19.8.1-8.module_5ccf9229',
            u'emacs-gettext-0:0.19.8.1-8.module_5ccf9229',
            u'python2-hawkey-0:0.8.2-1.module_987f08f4',
            u'libdnf-devel-0:0.8.2-1.module_987f08f4',
            u'sqlite-tcl-0:3.17.0-2.module_5ccf9229',
            u'sqlite-analyzer-0:3.17.0-2.module_5ccf9229',
            u'sssd-0:1.15.2-4.module_47fecbcd',
            u'sssd-nfs-idmap-0:1.15.2-4.module_47fecbcd',
            u'sssd-winbind-idmap-0:1.15.2-4.module_47fecbcd',
            u'sssd-krb5-0:1.15.2-4.module_47fecbcd',
            u'libsss_sudo-0:1.15.2-4.module_47fecbcd',
            u'sssd-libwbclient-devel-0:1.15.2-4.module_47fecbcd',
            u'sssd-common-pac-0:1.15.2-4.module_47fecbcd',
            u'sssd-ipa-0:1.15.2-4.module_47fecbcd',
            u'python3-sss-murmur-0:1.15.2-4.module_47fecbcd',
            u'libsss_simpleifp-devel-0:1.15.2-4.module_47fecbcd',
            u'sssd-common-0:1.15.2-4.module_47fecbcd',
            u'sssd-dbus-0:1.15.2-4.module_47fecbcd',
            u'libipa_hbac-0:1.15.2-4.module_47fecbcd',
            u'sssd-proxy-0:1.15.2-4.module_47fecbcd',
            u'python2-sss-murmur-0:1.15.2-4.module_47fecbcd',
            u'python3-sss-0:1.15.2-4.module_47fecbcd',
            u'libsss_autofs-0:1.15.2-4.module_47fecbcd',
            u'python2-libipa_hbac-0:1.15.2-4.module_47fecbcd',
            u'libsss_simpleifp-0:1.15.2-4.module_47fecbcd',
            u'libsss_idmap-devel-0:1.15.2-4.module_47fecbcd',
            u'sssd-libwbclient-0:1.15.2-4.module_47fecbcd',
            u'python2-libsss_nss_idmap-0:1.15.2-4.module_47fecbcd',
            u'python3-libipa_hbac-0:1.15.2-4.module_47fecbcd',
            u'python2-sssdconfig-0:1.15.2-4.module_47fecbcd',
            u'libipa_hbac-devel-0:1.15.2-4.module_47fecbcd',
            u'libsss_nss_idmap-devel-0:1.15.2-4.module_47fecbcd',
            u'python2-sss-0:1.15.2-4.module_47fecbcd',
            u'sssd-ldap-0:1.15.2-4.module_47fecbcd',
            u'sssd-ad-0:1.15.2-4.module_47fecbcd',
            u'sssd-tools-0:1.15.2-4.module_47fecbcd',
            u'sssd-krb5-common-0:1.15.2-4.module_47fecbcd',
            u'librepo-devel-0:1.7.20-3.module_5ccf9229',
            u'python2-librepo-0:1.7.20-3.module_5ccf9229',
            u'iproute-tc-0:4.11.0-1.module_d6de39f1',
            u'dracut-live-0:044-182.module_bd7491c8',
            u'dracut-fips-aesni-0:044-182.module_bd7491c8',
            u'dracut-fips-0:044-182.module_bd7491c8',
            u'dracut-network-0:044-182.module_bd7491c8',
            u'gobject-introspection-devel-0:1.52.0-1.module_5ccf9229',
            u'iptables-compat-0:1.6.1-2.module_5ccf9229',
            u'libcap-ng-python-0:0.7.8-3.module_5ccf9229',
            u'python3-sssdconfig-0:1.15.2-4.module_47fecbcd'
        ]

    def tearDown(self):
        init_data()

    @vcr.use_cassette(
        path.join(CASSETTES_DIR, 'tests.test_utils.TestUtils.test_format_mmd'))
    @patch('module_build_service.scm.SCM')
    def test_format_mmd(self, mocked_scm):
        mocked_scm.return_value.commit = \
            '620ec77321b2ea7b0d67d82992dda3e1d67055b4'
        # For all the RPMs in testmodule, get_latest is called
        hashes_returned = {
            'f24': '4ceea43add2366d8b8c5a622a2fb563b625b9abf',
            'f23': 'fbed359411a1baa08d4a88e0d12d426fbf8f602c',
            'f25': '76f9d8c8e87eed0aab91034b01d3d5ff6bd5b4cb'}
        original_refs = ["f23", "f24", "f25"]

        def mocked_get_latest(ref="master"):
            return hashes_returned[ref]

        mocked_scm.return_value.get_latest = mocked_get_latest
        mmd = modulemd.ModuleMetadata()
        with open(path.join(BASE_DIR, '..', 'staged_data', 'testmodule.yaml')) \
                as mmd_file:
            mmd.loads(mmd_file)
        scmurl = \
            ('git://pkgs.stg.fedoraproject.org/modules/testmodule.git'
             '?#620ec77321b2ea7b0d67d82992dda3e1d67055b4')
        module_build_service.utils.format_mmd(mmd, scmurl)

        # Make sure that original refs are not changed.
        mmd_pkg_refs = [pkg.ref for pkg in mmd.components.rpms.values()]
        self.assertEqual(set(mmd_pkg_refs), set(original_refs))

        self.assertEqual(mmd.buildrequires, {'base-runtime': 'master'})
        xmd = {
            'mbs': {
                'commit': '620ec77321b2ea7b0d67d82992dda3e1d67055b4',
                'buildrequires': {
                    'base-runtime': {
                        'ref': '147dca4ca65aa9a1ac51f71b7e687f9178ffa5df',
                        'stream': 'master',
                        'version': '20170616125652',
                        'filtered_rpms': self.filtered_rpms}},
                'requires': {
                    'base-runtime': {
                        'version': '20170616125652',
                        'ref': '147dca4ca65aa9a1ac51f71b7e687f9178ffa5df',
                        'stream': 'master',
                        'filtered_rpms': self.filtered_rpms}},
                'rpms': {'perl-List-Compare': {'ref': '76f9d8c8e87eed0aab91034b01d3d5ff6bd5b4cb'},
                         'perl-Tangerine': {'ref': '4ceea43add2366d8b8c5a622a2fb563b625b9abf'},
                         'tangerine': {'ref': 'fbed359411a1baa08d4a88e0d12d426fbf8f602c'}},
                'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/testmodule'
                          '.git?#620ec77321b2ea7b0d67d82992dda3e1d67055b4',
            }
        }

        self.assertEqual(mmd.xmd, xmd)

    @vcr.use_cassette(
        path.join(CASSETTES_DIR, 'tests.test_utils.TestUtils.test_format_mmd'))
    @patch('module_build_service.scm.SCM')
    def test_format_mmd_empty_scmurl(self, mocked_scm):
        # For all the RPMs in testmodule, get_latest is called
        hashes_returned = {
            'f24': '4ceea43add2366d8b8c5a622a2fb563b625b9abf',
            'f23': 'fbed359411a1baa08d4a88e0d12d426fbf8f602c',
            'f25': '76f9d8c8e87eed0aab91034b01d3d5ff6bd5b4cb'}

        def mocked_get_latest(branch="master"):
            return hashes_returned[branch]
        mocked_scm.return_value.get_latest = mocked_get_latest

        mmd = modulemd.ModuleMetadata()
        with open(path.join(BASE_DIR, '..', 'staged_data', 'testmodule.yaml')) \
                as mmd_file:
            mmd.loads(mmd_file)

        module_build_service.utils.format_mmd(mmd, scmurl=None)
        xmd = {
            'mbs': {
                'commit': None,
                'buildrequires': {
                    'base-runtime': {
                        'ref': '147dca4ca65aa9a1ac51f71b7e687f9178ffa5df',
                        'stream': 'master',
                        'version': '20170616125652',
                        'filtered_rpms': self.filtered_rpms}},
                'requires': {
                    'base-runtime': {
                        'version': '20170616125652',
                        'ref': '147dca4ca65aa9a1ac51f71b7e687f9178ffa5df',
                        'stream': 'master',
                        'filtered_rpms': self.filtered_rpms}},
                'rpms': {'perl-List-Compare': {'ref': '76f9d8c8e87eed0aab91034b01d3d5ff6bd5b4cb'},
                         'perl-Tangerine': {'ref': '4ceea43add2366d8b8c5a622a2fb563b625b9abf'},
                         'tangerine': {'ref': 'fbed359411a1baa08d4a88e0d12d426fbf8f602c'}},
                'scmurl': None,
            }
        }
        self.assertEqual(mmd.xmd, xmd)

    def test_get_reusable_component_same(self):
        test_reuse_component_init_data()
        new_module = models.ModuleBuild.query.filter_by(id=2).one()
        rv = module_build_service.utils.get_reusable_component(
            db.session, new_module, 'tangerine')
        self.assertEqual(rv.package, 'tangerine')

    def test_get_reusable_component_empty_scmurl(self):
        test_reuse_component_init_data()

        new_module = models.ModuleBuild.query.filter_by(id=2).one()
        mmd = new_module.mmd()
        mmd.xmd['mbs']['buildrequires'] = {'base-runtime': {}}
        new_module.modulemd = mmd.dumps()
        db.session.commit()

        rv = module_build_service.utils.get_reusable_component(
            db.session, new_module, 'tangerine')
        self.assertEqual(rv, None)

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

    def test_get_reusable_component_different_rpm_macros(self):
        test_reuse_component_init_data()
        second_module_build = models.ModuleBuild.query.filter_by(id=2).one()
        mmd = second_module_build.mmd()
        mmd.buildopts.rpms.macros = "%my_macro 1"
        second_module_build.modulemd = mmd.dumps()
        db.session.commit()

        plc_rv = module_build_service.utils.get_reusable_component(
            db.session, second_module_build, 'perl-List-Compare')
        self.assertEqual(plc_rv, None)

        # perl-Tangerine has a different commit hash
        pt_rv = module_build_service.utils.get_reusable_component(
            db.session, second_module_build, 'perl-Tangerine')
        self.assertEqual(pt_rv, None)

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

    def test_get_reusable_component_shared_userspace_ordering(self):
        """
        For modules with lot of components per batch, there is big chance that
        the database will return them in different order than what we have for
        current `new_module`. In this case, reuse code should still be able to
        reuse the components.
        """
        test_reuse_shared_userspace_init_data()
        new_module = models.ModuleBuild.query.filter_by(id=2).one()
        rv = module_build_service.utils.get_reusable_component(
            db.session, new_module, 'llvm')
        self.assertEqual(rv.package, 'llvm')

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

    @vcr.use_cassette(
        path.join(CASSETTES_DIR, 'tests.test_utils.TestUtils.test_format_mmd'))
    @patch('module_build_service.scm.SCM')
    def test_resubmit(self, mocked_scm):
        """
        Tests that the module resubmit reintializes the module state and
        component states properly.
        """
        FakeSCM(mocked_scm, 'testmodule', 'testmodule.yaml',
                '620ec77321b2ea7b0d67d82992dda3e1d67055b4')
        with app.app_context():
            test_reuse_component_init_data()
            # Mark the module build as failed, so we can resubmit it.
            module_build = models.ModuleBuild.query.filter_by(id=2).one()
            module_build.batch = 2
            module_build.state = models.BUILD_STATES['failed']
            module_build.state_reason = "Cancelled"
            module_build.version = 1
            now = datetime.utcnow()
            mbt_one = models.ModuleBuildTrace(
                state_time=now, state=models.BUILD_STATES['init'])
            mbt_two = models.ModuleBuildTrace(
                state_time=now, state=models.BUILD_STATES['wait'])
            mbt_three = models.ModuleBuildTrace(
                state_time=now, state=models.BUILD_STATES['build'])
            mbt_four = models.ModuleBuildTrace(
                state_time=now, state=models.BUILD_STATES['failed'])
            module_build.module_builds_trace.append(mbt_one)
            module_build.module_builds_trace.append(mbt_two)
            module_build.module_builds_trace.append(mbt_three)
            module_build.module_builds_trace.append(mbt_four)

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
            # The failed/cancelled components are now stateless
            self.assertIsNone(failed_component.state)
            self.assertIsNone(canceled_component.state)

    @vcr.use_cassette(
        path.join(CASSETTES_DIR, ('tests.test_utils.TestUtils.'
                                  'test_record_component_builds_duplicate_components')))
    @patch('module_build_service.scm.SCM')
    def test_record_component_builds_duplicate_components(self, mocked_scm):
        with app.app_context():
            test_reuse_component_init_data()
            mocked_scm.return_value.commit = \
                '620ec77321b2ea7b0d67d82992dda3e1d67055b4'
            # For all the RPMs in testmodule, get_latest is called
            hashes_returned = {
                'f25': '4ceea43add2366d8b8c5a622a2fb563b625b9abf',
                'f24': 'fbed359411a1baa08d4a88e0d12d426fbf8f602c'}

            def mocked_get_latest(ref="master"):
                return hashes_returned[ref]

            mocked_scm.return_value.get_latest = mocked_get_latest

            testmodule_variant_mmd_path = path.join(
                BASE_DIR, '..', 'staged_data', 'testmodule-variant.yaml')
            testmodule_variant_mmd = modulemd.ModuleMetadata()
            with open(testmodule_variant_mmd_path) as mmd_file:
                testmodule_variant_mmd.loads(mmd_file)

            module_build = \
                db.session.query(models.ModuleBuild).filter_by(id=1).one()
            mmd = module_build.mmd()

            error_msg = (
                'The included module "testmodule-variant" in "testmodule" have '
                'the following conflicting components: perl-List-Compare')
            try:
                module_build_service.utils.record_component_builds(
                    testmodule_variant_mmd, module_build, main_mmd=mmd)
                assert False, 'A UnprocessableEntity was expected but was not raised'
            except UnprocessableEntity as e:
                self.assertEqual(e.message, error_msg)


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
    def get_disttag_srpm(disttag, module_build):
        # @FIXME
        return KojiModuleBuilder.get_disttag_srpm(disttag, module_build)

    def cancel_build(self, task_id):
        pass

    def list_tasks_for_components(self, component_builds=None, state='active'):
        pass


@patch("module_build_service.builder.GenericBuilder.default_buildroot_groups",
       return_value={'build': [], 'srpm-build': []})
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

    @patch('module_build_service.utils.start_build_component')
    def test_start_next_batch_build_reuse_some(self, mock_sbc, default_buildroot_groups):
        """
        Tests that start_next_batch_build:
           1) Increments module.batch.
           2) Can reuse all components in the batch that it can.
           3) Returns proper further_work messages for reused components.
           4) Builds the remaining components
           5) Handling the further_work messages lead to proper tagging of
              reused components.
        """
        module_build = models.ModuleBuild.query.filter_by(id=2).one()
        module_build.batch = 1
        plc_component = models.ComponentBuild.query.filter_by(
            module_id=2, package='perl-List-Compare').one()
        plc_component.ref = '5ceea46add2366d8b8c5a623a2fb563b625b9abd'

        builder = mock.MagicMock()
        further_work = module_build_service.utils.start_next_batch_build(
            conf, module_build, db.session, builder)

        # Batch number should increase.
        self.assertEqual(module_build.batch, 2)

        # Make sure we only have one message returned for the one reused component
        self.assertEqual(len(further_work), 1)
        # The KojiBuildChange message in further_work should have build_new_state
        # set to COMPLETE, but the current component build state in the DB should be set
        # to BUILDING, so KojiBuildChange message handler handles the change
        # properly.
        self.assertEqual(further_work[0].build_new_state, koji.BUILD_STATES['COMPLETE'])
        component_build = models.ComponentBuild.from_component_event(db.session, further_work[0])
        self.assertEqual(component_build.state, koji.BUILD_STATES['BUILDING'])
        self.assertEqual(component_build.package, 'perl-Tangerine')
        self.assertIsNotNone(component_build.reused_component_id)
        # Make sure perl-List-Compare is set to the build state as well but not reused
        self.assertEqual(plc_component.state, koji.BUILD_STATES['BUILDING'])
        self.assertIsNone(plc_component.reused_component_id)
        mock_sbc.assert_called_once()

    @patch('module_build_service.utils.start_build_component')
    @patch('module_build_service.config.Config.rebuild_strategy',
           new_callable=mock.PropertyMock, return_value='all')
    def test_start_next_batch_build_rebuild_strategy_all(
            self, mock_rm, mock_sbc, default_buildroot_groups):
        """
        Tests that start_next_batch_build can't reuse any components in the batch because the
        rebuild method is set to "all".
        """
        module_build = models.ModuleBuild.query.filter_by(id=2).one()
        module_build.rebuild_strategy = 'all'
        module_build.batch = 1

        builder = mock.MagicMock()
        further_work = module_build_service.utils.start_next_batch_build(
            conf, module_build, db.session, builder)

        # Batch number should increase.
        self.assertEqual(module_build.batch, 2)
        # No component reuse messages should be returned
        self.assertEqual(len(further_work), 0)
        # Make sure that both components in the batch were submitted
        self.assertEqual(len(mock_sbc.mock_calls), 2)

    @patch('module_build_service.utils.start_build_component')
    @patch('module_build_service.config.Config.rebuild_strategy',
           new_callable=mock.PropertyMock, return_value='only-changed')
    def test_start_next_batch_build_rebuild_strategy_only_changed(
            self, mock_rm, mock_sbc, default_buildroot_groups):
        """
        Tests that start_next_batch_build reuses all unchanged components in the batch because the
        rebuild method is set to "only-changed". This means that one component is reused in batch
        2, and even though the other component in batch 2 changed and was rebuilt, the component
        in batch 3 can be reused.
        """
        module_build = models.ModuleBuild.query.filter_by(id=2).one()
        module_build.rebuild_strategy = 'only-changed'
        module_build.batch = 1
        # perl-List-Compare changed
        plc_component = models.ComponentBuild.query.filter_by(
            module_id=2, package='perl-List-Compare').one()
        plc_component.ref = '5ceea46add2366d8b8c5a623a2fb563b625b9abd'

        builder = mock.MagicMock()
        further_work = module_build_service.utils.start_next_batch_build(
            conf, module_build, db.session, builder)

        # Batch number should increase
        self.assertEqual(module_build.batch, 2)

        # Make sure we only have one message returned for the one reused component
        self.assertEqual(len(further_work), 1)
        # The KojiBuildChange message in further_work should have build_new_state
        # set to COMPLETE, but the current component build state in the DB should be set
        # to BUILDING, so KojiBuildChange message handler handles the change
        # properly.
        self.assertEqual(further_work[0].build_new_state, koji.BUILD_STATES['COMPLETE'])
        component_build = models.ComponentBuild.from_component_event(db.session, further_work[0])
        self.assertEqual(component_build.state, koji.BUILD_STATES['BUILDING'])
        self.assertEqual(component_build.package, 'perl-Tangerine')
        self.assertIsNotNone(component_build.reused_component_id)
        # Make sure perl-List-Compare is set to the build state as well but not reused
        self.assertEqual(plc_component.state, koji.BUILD_STATES['BUILDING'])
        self.assertIsNone(plc_component.reused_component_id)
        mock_sbc.assert_called_once()
        mock_sbc.reset_mock()

        # Complete the build
        plc_component.state = koji.BUILD_STATES['COMPLETE']
        pt_component = models.ComponentBuild.query.filter_by(
            module_id=2, package='perl-Tangerine').one()
        pt_component.state = koji.BUILD_STATES['COMPLETE']

        # Start the next build batch
        further_work = module_build_service.utils.start_next_batch_build(
            conf, module_build, db.session, builder)
        # Batch number should increase
        self.assertEqual(module_build.batch, 3)
        # Verify that tangerine was reused even though perl-Tangerine was rebuilt in the previous
        # batch
        self.assertEqual(further_work[0].build_new_state, koji.BUILD_STATES['COMPLETE'])
        component_build = models.ComponentBuild.from_component_event(db.session, further_work[0])
        self.assertEqual(component_build.state, koji.BUILD_STATES['BUILDING'])
        self.assertEqual(component_build.package, 'tangerine')
        self.assertIsNotNone(component_build.reused_component_id)
        mock_sbc.assert_not_called()

    @patch('module_build_service.utils.start_build_component')
    def test_start_next_batch_build_smart_scheduling(self, mock_sbc, default_buildroot_groups):
        """
        Tests that components with the longest build time will be scheduled first
        """
        module_build = models.ModuleBuild.query.filter_by(id=2).one()
        module_build.batch = 1
        pt_component = models.ComponentBuild.query.filter_by(
            module_id=2, package='perl-Tangerine').one()
        pt_component.ref = '6ceea46add2366d8b8c5a623b2fb563b625bfabe'
        plc_component = models.ComponentBuild.query.filter_by(
            module_id=2, package='perl-List-Compare').one()
        plc_component.ref = '5ceea46add2366d8b8c5a623a2fb563b625b9abd'

        builder = mock.MagicMock()
        # The call order of get_average_build_time should be by the component's ID. Having this
        # side_effect tells continue_batch_build to build the second component in the build batch
        # first and the first component in the build batch second.
        builder.get_average_build_time.side_effect = [1234.56, 2345.67]
        further_work = module_build_service.utils.start_next_batch_build(
            conf, module_build, db.session, builder)

        # Batch number should increase.
        self.assertEqual(module_build.batch, 2)

        # Make sure we don't have any messages returned since no components should be reused
        self.assertEqual(len(further_work), 0)
        # Make sure both components are set to the build state but not reused
        self.assertEqual(pt_component.state, koji.BUILD_STATES['BUILDING'])
        self.assertIsNone(pt_component.reused_component_id)
        self.assertEqual(plc_component.state, koji.BUILD_STATES['BUILDING'])
        self.assertIsNone(plc_component.reused_component_id)
        # Test the order of the scheduling
        expected_calls = [mock.call(builder, plc_component), mock.call(builder, pt_component)]
        self.assertEqual(mock_sbc.mock_calls, expected_calls)

    @patch('module_build_service.utils.start_build_component')
    def test_start_next_batch_continue(self, mock_sbc, default_buildroot_groups):
        """
        Tests that start_next_batch_build does not start new batch when
        there are unbuilt components in the current one.
        """
        module_build = models.ModuleBuild.query.filter_by(id=2).one()
        module_build.batch = 2

        # The component was reused when the batch first started
        building_component = module_build.current_batch()[0]
        building_component.state = koji.BUILD_STATES['BUILDING']
        building_component.reused_component_id = 123
        db.session.commit()

        builder = mock.MagicMock()
        further_work = module_build_service.utils.start_next_batch_build(
            conf, module_build, db.session, builder)

        # Batch number should not increase.
        self.assertEqual(module_build.batch, 2)
        # Make sure start build was called for the second component which wasn't reused
        mock_sbc.assert_called_once()
        # No further work should be returned
        self.assertEqual(len(further_work), 0)

    def test_start_next_batch_build_repo_building(self, default_buildroot_groups):
        """
        Test that start_next_batch_build does not start new batch when
        builder.buildroot_ready() returns False.
        """
        module_build = models.ModuleBuild.query.filter_by(id=2).one()
        module_build.batch = 1

        builder = mock.MagicMock()
        builder.buildroot_ready.return_value = False

        # Batch number should not increase.
        self.assertEqual(module_build.batch, 1)


@patch("module_build_service.config.Config.mock_resultsdir",
       new_callable=mock.PropertyMock,
       return_value=path.join(
           BASE_DIR, '..', 'staged_data', "local_builds"))
@patch("module_build_service.config.Config.system",
       new_callable=mock.PropertyMock, return_value="mock")
class TestLocalBuilds(unittest.TestCase):

    def setUp(self):
        init_data()

    def tearDown(self):
        init_data()

    def test_load_local_builds_name(self, conf_system, conf_resultsdir):
        with app.app_context():
            module_build_service.utils.load_local_builds("testmodule")
            local_modules = models.ModuleBuild.local_modules(db.session)

            self.assertEqual(len(local_modules), 1)
            self.assertTrue(local_modules[0].koji_tag.endswith(
                "/module-testmodule-master-20170816080816/results"))

    def test_load_local_builds_name_stream(
            self, conf_system, conf_resultsdir):
        with app.app_context():
            module_build_service.utils.load_local_builds("testmodule:master")
            local_modules = models.ModuleBuild.local_modules(db.session)

            self.assertEqual(len(local_modules), 1)
            self.assertTrue(local_modules[0].koji_tag.endswith(
                "/module-testmodule-master-20170816080816/results"))

    def test_load_local_builds_name_stream_non_existing(
            self, conf_system, conf_resultsdir):
        with app.app_context():
            with self.assertRaises(RuntimeError):
                module_build_service.utils.load_local_builds("testmodule:x")
                models.ModuleBuild.local_modules(db.session)

    def test_load_local_builds_name_stream_version(
            self, conf_system, conf_resultsdir):
        with app.app_context():
            module_build_service.utils.load_local_builds("testmodule:master:20170816080815")
            local_modules = models.ModuleBuild.local_modules(db.session)

            self.assertEqual(len(local_modules), 1)
            self.assertTrue(local_modules[0].koji_tag.endswith(
                "/module-testmodule-master-20170816080815/results"))

    def test_load_local_builds_name_stream_version_non_existing(
            self, conf_system, conf_resultsdir):
        with app.app_context():
            with self.assertRaises(RuntimeError):
                module_build_service.utils.load_local_builds("testmodule:master:123")
                models.ModuleBuild.local_modules(db.session)

    def test_load_local_builds_base_runtime(
            self, conf_system, conf_resultsdir):
        with app.app_context():
            module_build_service.utils.load_local_builds("base-runtime")
            local_modules = models.ModuleBuild.local_modules(db.session)

            self.assertEqual(len(local_modules), 1)
            self.assertTrue(local_modules[0].koji_tag.endswith(
                "/module-base-runtime-master-20170816080815/results"))

    def test_load_local_builds_base_runtime_master(
            self, conf_system, conf_resultsdir):
        with app.app_context():
            module_build_service.utils.load_local_builds("base-runtime:master")
            local_modules = models.ModuleBuild.local_modules(db.session)

            self.assertEqual(len(local_modules), 1)
            self.assertTrue(local_modules[0].koji_tag.endswith(
                "/module-base-runtime-master-20170816080815/results"))
