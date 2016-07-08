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
# Written by Petr Šabata <contyk@redhat.com>

"""
Logging functions.

At the beginning of the Rida flow, init_logging(conf) must be called.

After that, logging from any module is possible using Python's "logging"
module as showed at
<https://docs.python.org/3/howto/logging.html#logging-basic-tutorial>.

Examples:

import logging

logging.debug("Phasers are set to stun.")
logging.info("%s tried to build something", username)
logging.warn("%s failed to build", build_id)

"""

import logging

levels = {}
levels["debug"] = logging.DEBUG
levels["error"] = logging.ERROR
levels["warning"] = logging.WARNING
levels["info"] = logging.INFO

def str_to_log_level(level):
    """
    Returns internal representation of logging level defined
    by the string `level`.

    Available levels are: debug, info, warning, error
    """
    if not level in levels:
        return logging.NOTSET

    return levels[level]

def init_logging(conf):
    """
    Initializes logging according to configuration file.
    """
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    log_file = conf.log_file
    if not log_file or len(log_file) == 0 or log_file == "console":
        logging.basicConfig(level = conf.log_level, format = log_format)
        log = logging.getLogger()
        log.setLevel(conf.log_level)
    elif log_file == "journal":
        logging.basicConfig(level = conf.log_level, format = log_format)
        try:
            from systemd import journal
        except:
            raise ValueError("systemd.journal module is not installed")

        log = logging.getLogger()
        log.propagate = False
        log.addHandler(journal.JournalHandler())
    else:
        logging.basicConfig(filename = conf.log_file, level = conf.log_level,
                            format = log_format)
        log = logging.getLogger()