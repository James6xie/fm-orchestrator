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

"""The module build orchestrator for Modularity, API.

This is the implementation of the orchestrator's public RESTful API.
"""

# TODO: Load configuration.
# TODO: Handle GET and POST requests.
# TODO; Validate the input modulemd & spec inputs.
# TODO: Update the PDC dependency graph.
# TODO: Emit messages about module submission.
# TODO: Set the build state to init once the module NVR is known.
# TODO: Set the build state to wait once we're done.

from flask import Flask
from rida import config

app = Flask(__name__)
app.config.from_envvar("RIDA_SETTINGS", silent=True)

conf = config.from_file()

@app.teardown_appcontext
def close_db(error):
    """Closes the database connection at the end of the request."""

@app.route("/rida/module-builds/", methods=["POST"])
def submit_build():
    """Handles new module build submissions."""
    return "submit_build()", 501

@app.route("/rida/module-builds/", methods=["GET"])
def query_builds():
    """Lists all tracked module builds."""
    return "query_builds()", 501

@app.route("/rida/module-builds/<int:id>")
def query_build(id):
    """Lists details for the specified module builds."""
    return "query_build(id)", 501

if __name__ == "__main__":
    app.run()
