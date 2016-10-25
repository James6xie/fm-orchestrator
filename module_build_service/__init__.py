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
#            Matt Prahl <mprahl@redhat.com>

"""The module build orchestrator for Modularity.

The orchestrator coordinates module builds and is responsible
for a number of tasks:

- Providing an interface for module client-side tooling via
  which module build submission and build state queries are
  possible.
- Verifying the input data (modulemd, RPM SPEC files and others)
  is available and correct.
- Preparing the build environment in the supported build systems,
  such as koji.
- Scheduling and building of the module components and tracking
  the build state.
- Emitting bus messages about all state changes so that other
  infrastructure services can pick up the work.
"""
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from os import sys
import module_build_service.logger
from logging import getLogger
from module_build_service.errors import (
    ValidationError, Unauthorized, UnprocessableEntity, Conflict, NotFound,
    Forbidden, json_error)

app = Flask(__name__)
app.config.from_envvar("RIDA_SETTINGS", silent=True)

here = sys.path[0]
if here not in ('/usr/bin', '/bin', '/usr/local/bin'):
    app.config.from_object('config.DevConfiguration')
else:
    app.config.from_object('config.ProdConfiguration')

db = SQLAlchemy(app)


@app.errorhandler(ValidationError)
def validationerror_error(e):
    """Flask error handler for ValidationError exceptions"""
    return json_error(400, 'Bad Request', e.args[0])


@app.errorhandler(Unauthorized)
def unauthorized_error(e):
    """Flask error handler for NotAuthorized exceptions"""
    return json_error(401, 'Unauthorized', e.args[0])


@app.errorhandler(Forbidden)
def forbidden_error(e):
    """Flask error handler for Forbidden exceptions"""
    return json_error(403, 'Forbidden', e.args[0])


@app.errorhandler(RuntimeError)
def runtimeerror_error(e):
    """Flask error handler for RuntimeError exceptions"""
    return json_error(500, 'Internal Server Error', e.args[0])


@app.errorhandler(UnprocessableEntity)
def unprocessableentity_error(e):
    """Flask error handler for UnprocessableEntity exceptions"""
    return json_error(422, 'Unprocessable Entity', e.args[0])


@app.errorhandler(Conflict)
def conflict_error(e):
    """Flask error handler for Conflict exceptions"""
    return json_error(409, 'Conflict', e.args[0])


@app.errorhandler(NotFound)
def notfound_error(e):
    """Flask error handler for Conflict exceptions"""
    return json_error(404, 'Not Found', e.args[0])

import module_build_service.config
conf = module_build_service.config.from_app_config()
module_build_service.logger.init_logging(conf)
log = getLogger(__name__)

from module_build_service import views