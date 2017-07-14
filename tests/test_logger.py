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
# Written by Jan Kaluza <jkaluza@redhat.com>


import os
import shutil
import tempfile
import unittest

from module_build_service import log
from module_build_service.logger import ModuleBuildLogs
from module_build_service.scheduler.consumer import MBSConsumer
from mock import patch, PropertyMock


class TestLogger(unittest.TestCase):

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix='mbs-', suffix='-%s' % self.id())
        print("Storing build logs in %r" % self.base)
        self.build_log = ModuleBuildLogs(self.base)

    def tearDown(self):
        MBSConsumer.current_module_build_id = None
        shutil.rmtree(self.base)

    def test_module_build_logs(self):
        """
        Tests that ModuleBuildLogs is logging properly to build log file.
        """
        # Initialize logging, get the build log path and remove it to
        # ensure we are not using some garbage from previous failed test.
        self.build_log.start(1)
        path = self.build_log.path(1)
        self.assertEqual(path[len(self.base):], "/build-1.log")
        if os.path.exists(path):
            os.unlink(path)

        # Try logging without the MBSConsumer.current_module_build_id set.
        # No log file should be created.
        log.debug("ignore this test msg")
        log.info("ignore this test msg")
        log.warn("ignore this test msg")
        log.error("ignore this test msg")
        self.build_log.stop(1)
        self.assertTrue(not os.path.exists(path))

        # Try logging with current_module_build_id set to 1 and then to 2.
        # Only messages with current_module_build_id set to 1 should appear in
        # the log.
        self.build_log.start(1)
        MBSConsumer.current_module_build_id = 1
        log.debug("ignore this test msg1")
        log.info("ignore this test msg1")
        log.warn("ignore this test msg1")
        log.error("ignore this test msg1")

        MBSConsumer.current_module_build_id = 2
        log.debug("ignore this test msg2")
        log.info("ignore this test msg2")
        log.warn("ignore this test msg2")
        log.error("ignore this test msg2")

        self.build_log.stop(1)
        self.assertTrue(os.path.exists(path))
        with open(path, "r") as f:
            data = f.read()
            for level in ["DEBUG", "INFO", "WARNING", "ERROR"]:
                self.assertTrue(data.find("%s - ignore this test msg1" % level) != -1)

        # Try to log more messages when build_log for module 1 is stopped.
        # New messages should not appear in a log.
        MBSConsumer.current_module_build_id = 1
        log.debug("ignore this test msg3")
        log.info("ignore this test msg3")
        log.warn("ignore this test msg3")
        log.error("ignore this test msg3")
        self.build_log.stop(1)
        with open(path, "r") as f:
            data = f.read()
            self.assertTrue(data.find("ignore this test msg3") == -1)