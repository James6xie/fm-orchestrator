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
import subprocess as sp

import unittest
from mock import patch
from nose.tools import raises

import module_build_service.scm
from module_build_service.errors import ValidationError, UnprocessableEntity

repo_path = 'file://' + os.path.dirname(__file__) + "/scm_data/testrepo"


class TestSCMModule(unittest.TestCase):

    def setUp(self):
        # this var holds path to a cloned repo. For some tests we need a working
        # tree not only a bare repo
        self.temp_cloned_repo = None
        self.tempdir = tempfile.mkdtemp()
        self.repodir = self.tempdir + '/testrepo'

    def tearDown(self):
        if os.path.exists(self.tempdir):
            shutil.rmtree(self.tempdir)
        if self.temp_cloned_repo and os.path.exists(self.temp_cloned_repo):
            shutil.rmtree(self.temp_cloned_repo)

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
        scm.checkout(self.tempdir)
        scm.verify()

    @raises(UnprocessableEntity)
    def test_verify_unknown_branch(self):
        scm = module_build_service.scm.SCM(repo_path, "unknown")
        scm.checkout(self.tempdir)
        scm.verify()

    def test_verify_commit_in_branch(self):
        target = '7035bd33614972ac66559ac1fdd019ff6027ad21'
        scm = module_build_service.scm.SCM(repo_path + "?#" + target, "dev")
        scm.checkout(self.tempdir)
        scm.verify()

    @raises(ValidationError)
    def test_verify_commit_not_in_branch(self):
        target = '7035bd33614972ac66559ac1fdd019ff6027ad21'
        scm = module_build_service.scm.SCM(repo_path + "?#" + target, "master")
        scm.checkout(self.tempdir)
        scm.verify()

    @raises(UnprocessableEntity)
    def test_verify_unknown_hash(self):
        target = '7035bd33614972ac66559ac1fdd019ff6027ad22'
        scm = module_build_service.scm.SCM(repo_path + "?#" + target, "master")
        scm.checkout(self.tempdir)
        scm.verify()

    @raises(UnprocessableEntity)
    def test_get_module_yaml(self):
        scm = module_build_service.scm.SCM(repo_path)
        scm.checkout(self.tempdir)
        scm.verify()
        scm.get_module_yaml()

    @raises(UnprocessableEntity)
    def test_get_latest_incorect_component_branch(self):
        scm = module_build_service.scm.SCM(repo_path)
        scm.get_latest(branch='foobar')

    def test_patch_with_uncommited_changes(self):
        cloned_repo, repo_link = self._clone_from_bare_repo()
        with open(cloned_repo + "/foo", "a") as fd:
            fd.write("Winter is comming!")
        scm = module_build_service.scm.SCM(repo_link, allow_local=True)
        scm.checkout(self.tempdir)
        with open(self.repodir + "/foo", "r") as fd:
            foo = fd.read()

        assert "Winter is comming!" in foo

    def test_dont_patch_if_commit_ref(self):
        target = '7035bd33614972ac66559ac1fdd019ff6027ad21'
        cloned_repo, repo_link = self._clone_from_bare_repo()
        scm = module_build_service.scm.SCM(repo_link + "?#" + target, "dev", allow_local=True)
        with open(cloned_repo + "/foo", "a") as fd:
            fd.write("Winter is comming!")
        scm.checkout(self.tempdir)
        with open(self.repodir + "/foo", "r") as fd:
            foo = fd.read()

        assert "Winter is comming!" not in foo

    @patch("module_build_service.scm.open")
    @patch("module_build_service.scm.log")
    def test_patch_with_exception(self, mock_log, mock_open):
        cloned_repo, repo_link = self._clone_from_bare_repo()
        with open(cloned_repo + "/foo", "a") as fd:
            fd.write("Winter is comming!")
        mock_open.side_effect = Exception("Can't write to patch file!")
        scm = module_build_service.scm.SCM(repo_link, allow_local=True)
        with self.assertRaises(Exception) as ex:
            scm.checkout(self.tempdir)
            mock_open.assert_called_once_with(self.repodir + "/patch", "w+")
            err_msg = "Failed to update repo %s with uncommited changes." % self.repodir
            mock_log.assert_called_once_with(err_msg)
            assert ex is mock_open.side_effect
            assert 0

    def test_is_bare_repo(self):
        scm = module_build_service.scm.SCM(repo_path)
        assert scm.bare_repo

    def _clone_from_bare_repo(self):
        """
        Helper method which will clone the bare test repo. Also it will create
        a dev branch and track it to the remote bare repo.

        Returns:
            str: returns the path to the cloned repo
            str: returns the file link (file://) to the repo
        """
        self.temp_cloned_repo = tempfile.mkdtemp()
        cloned_repo = self.temp_cloned_repo + "/testrepo"
        clone_cmd = ["git", "clone", "-q", repo_path]
        get_dev_branch_cmd = ["git", "branch", "--track", "dev", "origin/dev"]
        proc = sp.Popen(clone_cmd, stdout=sp.PIPE, stderr=sp.PIPE,
                        cwd=self.temp_cloned_repo)
        stdout, stderr = proc.communicate()
        if stderr:
            raise Exception("Failed to clone repo: %s, err code: %s"
                            % (stderr, proc.returncode))
        proc = sp.Popen(get_dev_branch_cmd, stdout=sp.PIPE, stderr=sp.PIPE,
                        cwd=cloned_repo)
        stdout, stderr = proc.communicate()
        if stderr:
            raise Exception("Failed to create and track dev branch: %s, err code: %s"
                            % (stderr, proc.returncode))
        repo_link = "".join(["file://", cloned_repo])

        return cloned_repo, repo_link
