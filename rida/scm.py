# -*- coding: utf-8 -*-


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
# Modified by:
# Written by Karsten Hopp <karsten@redhat.com>
#            Petr Šabata <contyk@redhat.com>

"""SCM handler functions."""

from six.moves import http_client

import os
import subprocess as sp
import re
import tempfile

import logging
log = logging.getLogger(__name__)

import rida.utils


class SCM(object):
    "SCM abstraction class"

    # Assuming git for HTTP schemas
    types = {
                "git": ("git://", "git+http://", "git+https://",
                    "git+rsync://", "http://", "https://")
            }

    def __init__(self, url, allowed_scm=None):
        """Initialize the SCM object using the specified scmurl.

        If url is not in the list of allowed_scm, an error will be raised.
        NOTE: only git URLs in the following formats are supported atm:
            git://
            git+http://
            git+https://
            git+rsync://
            http://
            https://

        :param str url: The unmodified scmurl
        :param list allowed_scm: The list of allowed SCMs, optional
        :raises: RuntimeError
        """

        if allowed_scm:
            for allowed in allowed_scm:
                if url.startswith(allowed):
                    break
                else:
                    raise RuntimeError('%s is not in the list of allowed SCMs' % url)

        self.url = url

        for scmtype, schemes in SCM.types.items():
            if self.url.startswith(schemes):
                self.scheme = scmtype
                break
        else:
            raise RuntimeError('Invalid SCM URL: %s' % url)

        if self.scheme == "git":
            match = re.search(r"^(?P<repository>.*/(?P<name>[^?]*))(\?#(?P<commit>.*))?", url)
            self.repository = match.group("repository")
            self.name = match.group("name")
            if self.name.endswith(".git"):
                self.name = self.name[:-4]
            self.commit = match.group("commit")
        else:
            raise RuntimeError("Unhandled SCM scheme: %s" % self.scheme)

    @rida.utils.retry(wait_on=RuntimeError)
    @staticmethod
    def _run(cmd, chdir=None):
        proc = sp.Popen(cmd, stdout=sp.PIPE, stderr=sp.PIPE, cwd=chdir)
        stdout, stderr = proc.communicate()
        if stdout:
            log.debug(stdout)
        if stderr:
            log.warning(stderr)
        if proc.returncode != 0:
            raise RuntimeError("Failed on %r, retcode %r, out %r, err %r" % (
                cmd, proc.returncode, stdout, stderr))
        return proc.returncode

    def checkout(self, scmdir):
        """Checkout the module from SCM.

        :param str scmdir: The working directory
        :returns: str -- the directory that the module was checked-out into
        :raises: RuntimeError
        """
        # TODO: sanity check arguments
        if self.scheme == "git":
            sourcedir = '%s/%s' % (scmdir, self.name)

            module_clone_cmd = ['git', 'clone', '-q']
            if self.commit:
                module_checkout_cmd = ['git', 'checkout', '-q', self.commit]
            else:
                module_clone_cmd.extend(['--depth', '1'])
            module_clone_cmd.extend([self.repository, sourcedir])

            # perform checkouts
            SCM._run(module_clone_cmd, chdir=scmdir)
            if self.commit:
                SCM._run(module_checkout_cmd, chdir=sourcedir)
        else:
            raise RuntimeError("checkout: Unhandled SCM scheme.")
        return sourcedir

    def get_latest(self):
        """Get the latest commit ID.

        :returns: str -- the latest commit ID, e.g. the git master HEAD
        :raises: RuntimeError
        """
        if self.scheme == "git":
            (status , output) = sp.getstatusoutput("git ls-remote %s"
                % self.repository)
            if status != 0:
                raise RuntimeError("Cannot get git hash of master HEAD in %s"
                    % self.repository)
            for line in output.split(os.linesep):
                if line.endswith("\trefs/heads/master"):
                    return line.split("\t")[0]
            raise RuntimeError("Couldn't determine the git master HEAD hash in %s"
                % self.repository)
        else:
            raise RuntimeError("get_latest: Unhandled SCM scheme.")

    def is_available(self):
        """Check whether the scmurl is available for checkout.

        :returns: bool -- the scmurl is available for checkout
        """
        # XXX: If implementing special hacks for pagure.io or github.com, don't
        # forget about possible forks -- start with self.repository.
        if self.repository.startswith("-git://pkgs.fedoraproject.org/"):
            hc = http_client.HTTPConnection("pkgs.fedoraproject.org")
            hc.request("HEAD",
                "/cgit/rpms/" + self.name + ".git/commit/?id=" + self.commit)
            rc = hc.getresponse().code
            hc.close()
            return True if rc == 200 else False
        else:
            try:
                td = tempfile.TemporaryDirectory()
                self.checkout(td.name)
                td.cleanup()
                return True
            except:
                return False

    @property
    def url(self):
        """The original scmurl."""
        return self._url

    @url.setter
    def url(self, s):
        self._url = str(s)

    @property
    def scheme(self):
        """The SCM scheme."""
        return self._scheme

    @scheme.setter
    def scheme(self, s):
        self._scheme = str(s)

    @property
    def repository(self):
        """The repository part of the scmurl."""
        return self._repository

    @repository.setter
    def repository(self, s):
        self._repository = str(s)

    @property
    def commit(self):
        """The commit ID, for example the git hash, or None."""
        return self._commit

    @commit.setter
    def commit(self, s):
        self._commit = str(s) if s else None

    @property
    def name(self):
        """The module name."""
        return self._name

    @name.setter
    def name(self, s):
        self._name = str(s)
