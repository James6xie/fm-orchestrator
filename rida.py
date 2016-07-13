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

from flask import Flask, request
import json
import logging
import modulemd
import os.path
import rida.auth
import rida.config
import rida.database
import rida.logger
import rida.messaging
import rida.scm
import ssl
import tempfile

app = Flask(__name__)
app.config.from_envvar("RIDA_SETTINGS", silent=True)

# TODO: Load the config file from environment
conf = rida.config.from_file("rida.conf")
rida.logger.init_logging(conf)

db = rida.database.Database()

@app.route("/rida/module-builds/", methods=["POST"])
def submit_build():
    """Handles new module build submissions."""

    username = rida.auth.is_packager(conf.pkgdb_api_url)
    if not username:
        return ("You must use your Fedora certificate when submitting"
               " new build", 403)

    try:
        r = json.loads(request.get_data().decode("utf-8"))
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
    yaml = str()
    try:
        scm = rida.scm.SCM(url, conf.scmurls)
        td = tempfile.TemporaryDirectory()
        cod = scm.checkout(td.name)
        cofn = os.path.join(cod, (scm.name + ".yaml"))
        with open(cofn, "r") as mmdfile:
            yaml = mmdfile.read()
        td.cleanup()
    except Exception as e:
        if "is not in the list of allowed SCMs" in str(e):
            rc = 403
        elif "Invalid SCM URL" in str(e):
            rc = 400
        else:
            rc = 500
        return str(e), rc
    mmd = modulemd.ModuleMetadata()
    try:
        mmd.loads(yaml)
    except:
        return "Invalid modulemd", 422
    if db.session.query(rida.database.Module).filter_by(name=mmd.name,
        version=mmd.version, release=mmd.release).first():
        return "Module already exists", 409
    module = rida.database.Module(name=mmd.name, version=mmd.version,
            release=mmd.release, state="init", modulemd=yaml)
    db.session.add(module)
    db.session.commit()
    for pkgname, pkg in mmd.components.rpms.packages.items():
        if pkg.get("repository") and not conf.rpms_allow_repository:
            return "Custom component repositories aren't allowed", 403
        if pkg.get("cache") and not conf.rpms_allow_cache:
            return "Custom component caches aren't allowed", 403
        if not pkg.get("repository"):
            pkg["repository"] = conf.rpms_default_repository + pkgname
        if not pkg.get("cache"):
            pkg["cache"] = conf.rpms_default_cache + pkgname
        if not pkg.get("commit"):
            try:
                pkg["commit"] = rida.scm.SCM(pkg["repository"]).get_latest()
            except Exception as e:
                return "Failed to get the latest commit: %s" % pkgname, 422
        if not rida.scm.SCM(pkg["repository"] + "?#" + pkg["commit"]).is_available():
            return "Cannot checkout %s" % pkgname, 422
        build = rida.database.Build(module_id=module.id, package=pkgname, format="rpms")
        db.session.add(build)
    module.modulemd = mmd.dumps()
    module.state = "wait"
    db.session.add(module)
    db.session.commit()
    # Publish to whatever bus we're configured to connect to.
    # This should notify ridad to start doing the work we just scheduled.
    rida.messaging.publish(
        modname='rida',
        topic='module.state.change',
        msg=module.json(),
        backend=conf.messaging,
    )
    logging.info("%s submitted build of %s-%s-%s", username, mmd.name,
            mmd.version, mmd.release)
    return json.dumps(module.json()), 201


@app.route("/rida/module-builds/", methods=["GET"])
def query_builds():
    """Lists all tracked module builds."""
    return json.dumps([{"id": x.id, "state": x.state}
        for x in db.session.query(rida.database.Module).all()]), 200


@app.route("/rida/module-builds/<int:id>", methods=["GET"])
def query_build(id):
    """Lists details for the specified module builds."""
    module = db.session.query(rida.database.Module).filter_by(id=id).first()
    if module:
        tasks = dict()
        if module.state != "init":
            for build in db.session.query(rida.database.Build).filter_by(module_id=id).all():
                tasks[build.format + "/" + build.package] = \
                    str(build.task) + "/" + build.state
        return json.dumps({
            "id": module.id,
            "state": module.state,
            "tasks": tasks
            }), 200
    else:
        return "No such module found.", 404

def _establish_ssl_context(conf):
    # First, do some validation of the configuration
    attributes = (
        'ssl_certificate_file',
        'ssl_certificate_key_file',
        'ssl_ca_ceritifcate_file',
    )
    for attribute in attributes:
        value = getattr(conf, attribute, None)
        if not value:
            raise ValueError("%r could not be found" % attribute)
        if not os.path.exists(value):
            raise OSError("%s: %s file not found." % (attribute, value))

    # Then, establish the ssl context and return it
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
    ssl_ctx.load_cert_chain(conf.ssl_certificate_file,
                            conf.ssl_certificate_key_file)
    ssl_ctx.verify_mode = ssl.CERT_OPTIONAL
    ssl_ctx.load_verify_locations(cafile=conf.ssl_ca_certificate_file)
    return ssl_ctx


if __name__ == "__main__":
    logging.info("Starting Rida")
    ssl_ctx = _establish_ssl_context(conf)
    app.run(
        host=conf.host,
        port=conf.port,
        request_handler=rida.auth.ClientCertRequestHandler,
        ssl_context=ssl_ctx,
    )
