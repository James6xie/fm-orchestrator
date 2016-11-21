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
# Written by Ralph Bean <rbean@redhat.com>

from nose.tools import eq_

import unittest

from tests.test_models import init_data, db

from module_build_service import models


class TestModels(unittest.TestCase):
    def setUp(self):
        init_data()

    def test_resolve_refs(self):
        expected = set([
            'shadow-utils',
            'fedora-release',
            'redhat-rpm-config',
            'rpm-build',
            'fedpkg-minimal',
            'gnupg2',
            'bash',
        ])
        build = db.session.query(models.ModuleBuild).filter_by(name='testmodule').one()
        result = build.resolve_profiles(db.session, 'srpm-buildroot')
        eq_(result,  expected)