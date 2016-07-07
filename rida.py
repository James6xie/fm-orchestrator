#!/usr/bin/python3
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

# TODO; Validate the input modulemd & spec inputs.
#       This requires SCM classes to be ready.
# TODO: Update the PDC dependency graph.
#       This is done via messaging and is closely related to the next point.
# TODO: Emit messages about module submission.

from flask import Flask, request
from rida import config, database, messaging, auth
import json
import modulemd
import ssl

app = Flask(__name__)
app.config.from_envvar("RIDA_SETTINGS", silent=True)

# TODO: Load the config file from environment
conf = config.from_file("rida.conf")
db = database.Database()

@app.route("/rida/module-builds/", methods=["POST"])
def submit_build():
    """Handles new module build submissions."""

    username = auth.is_packager(conf.pkgdb_api_url)
    if not username:
        return ("You must use your Fedora certificate when submitting"
               " new build", 403)

    try:
        r = json.loads(request.data.decode('utf-8'))
    except:
        return "Invalid JSON submitted", 400
    if "scmurl" not in r:
        return "Missing scmurl", 400
    url = r["scmurl"]
    urlallowed = False
    for prefix in conf.scmurls:
        if url.startswith(prefix):
            urlallowed = True
            break
    if not urlallowed:
        return "The submitted scmurl isn't allowed", 403
    # FIXME: Use the scm class to obtain modulemd
    # for the next step we're pretending "yaml" contains
    # the contents of the modulemd yaml file
    yaml = str()
    mmd = modulemd.ModuleMetadata()
    try:
        mmd.loads(yaml)
    except:
        return "Invalid modulemd", 422
    module = database.Module(name=mmd.name, version=mmd.version,
            release=mmd.release, state="init", modulemd=yaml)
    db.session.add(module)
    db.session.commit()
    # FIXME: Use the validation class to determine whether
    # all the components are available and we're allowed to
    # process them.  We will assume it all passed for now.
    for rpm in mmd.components.rpms.packages.keys():
        build = database.Build(module_id=module.id, package=rpm, format="rpms")
        db.session.add(build)
    module.state = "wait"
    db.session.add(module)
    db.session.commit()

    # Publish to whatever bus we're configured to connect to.
    # This should notify ridad to start doing the work we just scheduled.
    messaging.publish(
        modname='rida',
        topic='module.state.change',
        msg=module.json(),
        backend=conf.messaging,
    )

    # XXX: Okay, we're pretending here...
    return json.dumps(module.json()), 201


@app.route("/rida/module-builds/", methods=["GET"])
def query_builds():
    """Lists all tracked module builds."""
    return json.dumps([{"id": x.id, "state": x.state}
        for x in db.session.query(database.Module).all()]), 200


@app.route("/rida/module-builds/<int:id>", methods=["GET"])
def query_build(id):
    """Lists details for the specified module builds."""
    module = db.session.query(database.Module).filter_by(id=id).first()
    if module:
        tasks = dict()
        if module.state != "init":
            for build in db.session.query(database.Build).filter_by(module_id=id).all():
                tasks[build.format + "/" + build.package] = \
                    str(build.task) + "/" + build.state
        return json.dumps({
            "id": module.id,
            "state": module.state,
            "tasks": tasks
            }), 200
    else:
        return "No such module found.", 404

if __name__ == "__main__":
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
    ssl_ctx.load_cert_chain(conf.ssl_certificate_file,
                            conf.ssl_certificate_key_file)
    ssl_ctx.verify_mode = ssl.CERT_OPTIONAL
    ssl_ctx.load_verify_locations(cafile=conf.ssl_ca_certificate_file)

    app.run(request_handler=auth.ClientCertRequestHandler, ssl_context=ssl_ctx)
