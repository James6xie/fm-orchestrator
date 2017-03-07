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
#
# Written by Ralph Bean <rbean@redhat.com>

import os
import shutil
import tempfile

import unittest
from nose.tools import raises

import module_build_service.scm
from module_build_service.errors import ValidationError

repo_path = 'file://' + os.path.dirname(__file__) + "/scm_data/testrepo"


class TestSCMModule(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.repodir = self.tempdir + '/testrepo'

    def tearDown(self):
        if os.path.exists(self.tempdir):
            shutil.rmtree(self.tempdir)

    def test_simple_local_checkout(self):
        """ See if we can clone a local git repo. """
        scm = module_build_service.scm.SCM(repo_path)
        scm.checkout(self.tempdir)
        files = os.listdir(self.repodir)
        assert 'foo' in files, "foo not in %r" % files

    def test_local_get_latest_is_sane(self):
        """ See that a hash is returned by scm.get_latest. """
        scm = module_build_service.scm.SCM(repo_path)
        latest = scm.get_latest(branch='master')
        target = '5481faa232d66589e660cc301179867fb00842c9'
        assert latest == target, "%r != %r" % (latest, target)

    def test_local_get_latest_unclean_input(self):
        """ Ensure that shell characters aren't handled poorly.

        https://pagure.io/fm-orchestrator/issue/329
        """
        scm = module_build_service.scm.SCM(repo_path)
        assert scm.scheme == 'git', scm.scheme
        fname = tempfile.mktemp(suffix='mbs-scm-test')
        scm.get_latest(branch='master; touch %s' % fname)
        assert not os.path.exists(fname), "%r exists!  Vulnerable." % fname

    def test_local_extract_name(self):
        scm = module_build_service.scm.SCM(repo_path)
        target = 'testrepo'
        assert scm.name == target, '%r != %r' % (scm.name, target)

    def test_local_extract_name_trailing_slash(self):
        scm = module_build_service.scm.SCM(repo_path + '/')
        target = 'testrepo'
        assert scm.name == target, '%r != %r' % (scm.name, target)

    def test_verify(self):
        scm = module_build_service.scm.SCM(repo_path)
        sourcedir = scm.checkout(self.tempdir)
        scm.verify(sourcedir)

    @raises(RuntimeError)
    def test_verify_unknown_branch(self):
        scm = module_build_service.scm.SCM(repo_path, "unknown")
        sourcedir = scm.checkout(self.tempdir)
        scm.verify(sourcedir)

    def test_verify_commit_in_branch(self):
        target = '7035bd33614972ac66559ac1fdd019ff6027ad21'
        scm = module_build_service.scm.SCM(repo_path + "?#" + target, "dev")
        sourcedir = scm.checkout(self.tempdir)
        scm.verify(sourcedir)

    @raises(ValidationError)
    def test_verify_commit_not_in_branch(self):
        target = '7035bd33614972ac66559ac1fdd019ff6027ad21'
        scm = module_build_service.scm.SCM(repo_path + "?#" + target, "master")
        sourcedir = scm.checkout(self.tempdir)
        scm.verify(sourcedir)

    @raises(RuntimeError)
    def test_verify_unknown_hash(self):
        target = '7035bd33614972ac66559ac1fdd019ff6027ad22'
        scm = module_build_service.scm.SCM(repo_path + "?#" + target, "master")
        sourcedir = scm.checkout(self.tempdir)
        scm.verify(sourcedir)
