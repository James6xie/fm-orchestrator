# some functions kindly copied and then heavily modified from the koji sources: koji/daemon.py
#
# Copyright (c) 2010-2016 Red Hat, Inc.
#
#    This is free software; you can redistribute it and/or
#    modify it under the terms of the GNU Lesser General Public
#    License as published by the Free Software Foundation;
#    version 2.1 of the License.
#
#    This software is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#    Lesser General Public License for more details.
#
#    You should have received a copy of the GNU Lesser General Public
#    License along with this software; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA

# Original Authors of the koji source:
#       Mike McLean <mikem@redhat.com>
#       Mike Bonnet <mikeb@redhat.com>
# Modified by:
#       Karsten Hopp <karsten@redhat.com>


import os
import sys
import time
import traceback
import subprocess
import re

class SCM(object):
    "SCM abstraction class"

    types = {'GIT': ('git://', 'git+http://', 'git+https://', 'git+rsync://'),
             'GIT+SSH': ('git+ssh://',)}

    @staticmethod
    def is_scm_url(url):
        """
        Return True if the url appears to be a valid, accessible source location, False otherwise
        """
        for schemes in SCM.types.values():
            for scheme in schemes:
                if url.startswith(scheme):
                    return True
        else:
            return False

    def __init__(self, url, allowed_scm=None):
        """
        Initialize the SCM object using the specified url.
        If url is not in the list of allowed_scm, an error will be raised.
        NOTE: only git URLs in the following formats are supported atm:
            git://
            git+http://
            git+https://
            git+rsync://
            git+ssh://

        The initialized SCM object will have the following attributes:
        - url (the unmodified url)
        - allowed_scm (the list of allowed scm, optional)
        """

        if allowed_scm:
            for allowed in allowed_scm:
                if url.startswith(allowed):
                    break
                else:
                    raise RuntimeError('%s is not in the list of allowed SCMs' % url)

        if not SCM.is_scm_url(url):
            raise RuntimeError('Invalid SCM URL: %s' % url)

        self.url = url

        for scmtype, schemes in SCM.types.items():
            if self.url.startswith(schemes):
                self.scheme = scmtype
                break
        else:
            # should never happen
            raise RuntimeError('Invalid SCM URL: %s' % url)

        if self.scheme.startswith("GIT"):
            match = re.search(r"^(?P<repository>.*/(?P<name>[^?]*))(\?#(?P<commit>.*))?", url)
            self.repository = match.group("repository")
            self.name = match.group("name")
            if self.name.endswith(".git"):
                self.name = self.name[:-4]
            self.commit = match.group("commit")
        else:
            raise RuntimeError("Unhandled SCM scheme: %s" % self.scheme)

    def _run(self, cmd, chdir=None):
        numretry = 0
        path = cmd[0]
        args = cmd
        pid = os.fork()
        if not pid:
            while numretry <= 3:
                numretry += 1
                try:
                    if chdir:
                        os.chdir(chdir)
                    os.execvp(path, args)
                except:   # XXX maybe switch to subprocess (python-3.5) where 
                          # we can check for return codes and timeouts
                    msg = ''.join(traceback.format_exception(*sys.exc_info()))
                    print(msg)
                    if numretry == 3:
                        os._exit(1)
                    time.sleep(10)
        else:
            while True:
                status = os.waitpid(pid, os.WNOHANG)
                time.sleep(1)

                if status[0] != 0:
                    return status[1]

    def checkout(self, scmdir):
        """
        Checkout the module from SCM.  Accepts the following parameters:
         - scmdir: the working directory

        Returns the directory that the module was checked-out into (a subdirectory of scmdir)
        """
        # TODO: sanity check arguments
        sourcedir = '%s/%s' % (scmdir, self.name)
        module_clone_cmd = ['git', 'clone', '-q', self.repository, sourcedir]
        module_checkout_cmd = ['git', 'checkout', '-q', self.commit]

        # perform checkouts
        self._run(module_clone_cmd, chdir=scmdir)
        self._run(module_checkout_cmd, chdir=sourcedir)

        return sourcedir

    def get_git_master_head_giturl(self):
        """
        Return the git hash of this git object's master HEAD
        """
        # drop git hash if url contains it:
        gitrepo = self.url.split('?')[0]
        (status , output) = subprocess.getstatusoutput('git ls-remote %s' % gitrepo)
        if status != 0:
            raise RuntimeError('can\'t get git hash of master HEAD in %s' % self.url)
        b = output.split(os.linesep)
        ret = ''
        for line in b:
            if 'refs/heads/master' in line:
                ret = gitrepo + '?#' + line.split('\t')[0]
                break
        return ret

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
        
def get_fedpkg_url_git_master_head_pkgname(pkgname=None):
    """
    Return the complete git URL to master HEAD of the given package.
    Accepts the following parameters:
    - pkgname: the package name
    """
    pkghash = get_hash_of_git_master_head_pkgname(pkgname)
    if pkghash is not '':
        return 'git://pkgs.fedoraproject.org/rpms/' + pkgname + '?#' + pkghash
    else:
        return ''

def get_hash_of_git_master_head_pkgname(pkgname=None):
    """
    Return the git hash of master HEAD
    Accepts the following parameters:
         - pkgname: the package name
    """
    if not isinstance(pkgname, str):
        raise RuntimeError('pkgname needs to be a string')
    gitrepo = 'git://pkgs.fedoraproject.org/rpms/' + pkgname
    (status , output) = subprocess.getstatusoutput('git ls-remote %s' % gitrepo)
    if status != 0:
        raise RuntimeError('can\'t get git hash of master HEAD in %s' % gitrepo)
    b = output.split(os.linesep)
    ret = ''
    for line in b:
        if 'refs/heads/master' in line:
            ret = line.split('\t')[0]
            break
    return ret

def check_giturl_syntax(giturl=None):
    """
    dist-pkg giturls are of the form 
    git://pkgs.fedoraproject.org/rpms/ed?#abc0235d4923930745ef05d873646f361a365457
    Returns True if giturl has this format, False otherwise.
    """
    if not isinstance(giturl, str):
        return False
    if giturl[:6] != 'git://':
        return False
    if giturl[6:34] != 'pkgs.fedoraproject.org/rpms/' and giturl[6:38] != 'pkgs.stg.fedoraproject.org/rpms/':
        return False
    if not '?#' in giturl.split('/')[-1]:
        return False
    return True

def convert_giturl_to_cgiturl(giturl=None):
    """
    dist-pkg giturls are of the form 
    git://pkgs.fedoraproject.org/rpms/ed?#abc0235d4923930745ef05d873646f361a365457
    cgit urls look like this:
     http://pkgs.fedoraproject.org/cgit/rpms/ed.git/commit/?id=abc0235d4923930745ef05d873646f361a365457
    This function takes a string with a dist-git url as parameter and returns a cgit url
    Accepts the following parameters:
         - giturl - dist-git url ('fedpkg giturl')
    """
    try:
        url = giturl[giturl.index('://')+3:]
    except:
        raise RuntimeError('%s is not a dist-git URL' % giturl)
    url = url.replace('/rpms/','/cgit/rpms/')
    url = url.replace('?#','.git/commit/?id=')
    return 'http://' + url
    
def check_if_remote_gitcommit_exists(giturl=None):
    """
    Instead of checking out a git repo and then looking through all the 
    git hashes, this function uses http to connect to cgit and checks
    for availability of p.e. 
    http://pkgs.fedoraproject.org/cgit/rpms/ed.git/commit/?id=abc0235d4923930745ef05d873646f361a365457
    Accepts the following parameters:
         - giturl - dist-git url ('fedpkg giturl')
    """
    if not check_giturl_syntax(giturl):
        return False
    import http.client
    import os
    cgiturl = convert_giturl_to_cgiturl(giturl)
    urlpath = cgiturl[cgiturl.index('://')+3:]
    urlpath = urlpath[urlpath.index('/'):]
    http_obj = http.client.HTTPConnection('pkgs.fedoraproject.org')
    http_obj.request('HEAD',urlpath)
    res = http_obj.getresponse()
    if res.status == 200:
        return True
    else:
        return False
