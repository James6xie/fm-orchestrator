# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
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

import pkg_resources
from flask import Flask, has_app_context, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.pool import StaticPool
from logging import getLogger
import gi  # noqa
gi.require_version("Modulemd", "2.0")  # noqa
from gi.repository import Modulemd  # noqa

from module_build_service.logger import init_logging, ModuleBuildLogs, level_flags, MBSLogger

from module_build_service.errors import (
    ValidationError, Unauthorized, UnprocessableEntity, Conflict, NotFound,
    Forbidden, json_error)
from module_build_service.config import init_config
from module_build_service.proxy import ReverseProxy

try:
    version = pkg_resources.get_distribution("module-build-service").version
except pkg_resources.DistributionNotFound:
    version = "unknown"
api_version = 2

app = Flask(__name__)
app.wsgi_app = ReverseProxy(app.wsgi_app)

conf = init_config(app)


class MBSSQLAlchemy(SQLAlchemy):
    """
    Inherits from SQLAlchemy and if SQLite in-memory database is used,
    sets the driver options so multiple threads can share the same database.

    This is used *only* during tests to make them faster.
    """

    def apply_driver_hacks(self, app, info, options):
        if info.drivername == "sqlite" and info.database in (None, "", ":memory:"):
            options["poolclass"] = StaticPool
            options["connect_args"] = {"check_same_thread": False}
            try:
                del options["pool_size"]
            except KeyError:
                pass

        super(MBSSQLAlchemy, self).apply_driver_hacks(app, info, options)


db = MBSSQLAlchemy(app)


def create_app(debug=False, verbose=False, quiet=False):
    # logging (intended for flask-script, see manage.py)
    log = getLogger(__name__)
    if debug:
        log.setLevel(level_flags["debug"])
    elif verbose:
        log.setLevel(level_flags["verbose"])
    elif quiet:
        log.setLevel(level_flags["quiet"])

    return app


def load_views():
    from module_build_service import views

    assert views


@app.errorhandler(ValidationError)
def validationerror_error(e):
    """Flask error handler for ValidationError exceptions"""
    return json_error(400, "Bad Request", str(e))


@app.errorhandler(Unauthorized)
def unauthorized_error(e):
    """Flask error handler for NotAuthorized exceptions"""
    return json_error(401, "Unauthorized", str(e))


@app.errorhandler(Forbidden)
def forbidden_error(e):
    """Flask error handler for Forbidden exceptions"""
    return json_error(403, "Forbidden", str(e))


@app.errorhandler(RuntimeError)
def runtimeerror_error(e):
    """Flask error handler for RuntimeError exceptions"""
    log.exception("RuntimeError exception raised")
    return json_error(500, "Internal Server Error", str(e))


@app.errorhandler(UnprocessableEntity)
def unprocessableentity_error(e):
    """Flask error handler for UnprocessableEntity exceptions"""
    return json_error(422, "Unprocessable Entity", str(e))


@app.errorhandler(Conflict)
def conflict_error(e):
    """Flask error handler for Conflict exceptions"""
    return json_error(409, "Conflict", str(e))


@app.errorhandler(NotFound)
def notfound_error(e):
    """Flask error handler for Conflict exceptions"""
    return json_error(404, "Not Found", str(e))


init_logging(conf)
log = MBSLogger()
build_logs = ModuleBuildLogs(conf.build_logs_dir, conf.build_logs_name_format, conf.log_level)


def get_url_for(*args, **kwargs):
    """
    flask.url_for wrapper which creates the app_context on-the-fly.
    """
    if has_app_context():
        return url_for(*args, **kwargs)

    # Localhost is right URL only when the scheduler runs on the same
    # system as the web views.
    app.config["SERVER_NAME"] = "localhost"
    with app.app_context():
        log.debug(
            "WARNING: get_url_for() has been called without the Flask "
            "app_context. That can lead to SQLAlchemy errors caused by "
            "multiple session being used in the same time."
        )
        return url_for(*args, **kwargs)


load_views()
