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
# THE SOFTWARE IS PROVIDED 'AS IS', WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# Written by Matt Prahl <mprahl@redhat.com>
from __future__ import unicode_literals
import unittest
from datetime import datetime


class TestUtilFunctions(unittest.TestCase):

    module_build_service_msg = msg = {
        'component_builds': [1, 2],
        'id': 1,
        'name': 'testmodule',
        'owner': 'some_user',
        'release': '16',
        'scmurl': 'git://domain.local/modules/testmodule.git?#c23acdc',
        'state': 3,
        'state_name': 'done',
        'time_completed': datetime(2016, 9, 1, 2, 30),
        'time_modified': datetime(2016, 9, 1, 2, 30),
        'time_submitted': datetime(2016, 9, 1, 2, 28),
        'version': '4.3.43'
    }
