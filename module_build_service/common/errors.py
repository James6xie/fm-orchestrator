# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
""" Defines custom exceptions and error handling functions """

from __future__ import absolute_import

from flask import jsonify


class ValidationError(ValueError):
    pass


class Unauthorized(ValueError):
    pass


class Forbidden(ValueError):
    pass


class UnprocessableEntity(ValueError):
    pass


class Conflict(ValueError):
    pass


class NotFound(ValueError):
    pass


class ProgrammingError(ValueError):
    pass


class StreamAmbigous(ValueError):
    pass


class GreenwaveError(RuntimeError):
    pass


def json_error(status, error, message):
    response = jsonify({"status": status, "error": error, "message": message})
    response.status_code = status
    return response


class IgnoreMessage(Exception):
    """Raise if message received from message bus should be ignored"""
