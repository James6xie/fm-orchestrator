# Code kindly copied and then heavily modified from the koji sources: koji/daemon.py
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
import rida

class SCM(object):
    "SCM abstraction class"

    types = {'GIT': ('git://', 'git+http://', 'git+https://', 'git+rsync://'),
             'GIT+SSH': ('git+ssh://',)}

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
    is_scm_url = staticmethod(is_scm_url)

    def __init__(self, url, allowed_scm):
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
        - allowed_scm (the list of allowed scm)
        """

        for allowed in allowed_scm:
            if url.startswith(allowed):
                break
            else:
                raise RuntimeError, '%s is not in the list of allowed SCMs' % (url)

        if not SCM.is_scm_url(url):
            raise RuntimeError, 'Invalid SCM URL: %s' % url

        self.url = url
        self.allowed_scm = allowed_scm

        for scmtype, schemes in SCM.types.items():
            if self.url.startswith(schemes):
                self.scmtype = scmtype
                break
        else:
            # should never happen
            raise RuntimeError, 'Invalid SCM URL: %s' % url

    def _run(self, cmd, chdir=None, _count=[0]):
        append = (_count[0] > 0)
        _count[0] += 1
        path = cmd[0]
        args = cmd
        pid = os.fork()
        if not pid:
            try:
                if chdir:
                    os.chdir(chdir)
                flags = os.O_CREAT | os.O_WRONLY
                environ = os.environ.copy()
                os.execvpe(path, args, environ)
            except:
                msg = ''.join(traceback.format_exception(*sys.exc_info()))
                print msg
                os._exit(1)
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
        sourcedir = scmdir

        gitrepo = self.url
        commonrepo = os.path.dirname(gitrepo) + '/common'
        checkout_path = os.path.basename(gitrepo)
        if gitrepo.endswith('/.git'):
            # If we're referring to the .git subdirectory of the main module,
            # assume we need to do the same for the common module
            checkout_path = os.path.basename(gitrepo[:-5])
            commonrepo = os.path.dirname(gitrepo[:-5]) + '/common/.git'
        elif gitrepo.endswith('.git'):
            # If we're referring to a bare repository for the main module,
            # assume we need to do the same for the common module
            checkout_path = os.path.basename(gitrepo[:-4])
            commonrepo = os.path.dirname(gitrepo[:-4]) + '/common.git'

        sourcedir = '%s/%s' % (scmdir, checkout_path)
        module_checkout_cmd = ['git', 'clone', gitrepo, sourcedir]
        module_checkout_cmd = ['git', 'clone', '-n', gitrepo, sourcedir]

        # perform checkouts
        self._run(module_checkout_cmd, chdir=scmdir)

        return sourcedir


