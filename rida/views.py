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
#            Matt Prahl <mprahl@redhat.com>

""" The module build orchestrator for Modularity, API.
This is the implementation of the orchestrator's public RESTful API.
"""

from flask import request, jsonify
import json
import logging
import modulemd
import os
import rida.auth
import rida.logger
import rida.scm
import shutil
import tempfile
from rida import app, conf, db, log
from rida import models
from rida.utils import pagination_metadata


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
        td = tempfile.mkdtemp()
        scm = rida.scm.SCM(url, conf.scmurls)
        cod = scm.checkout(td)
        cofn = os.path.join(cod, (scm.name + ".yaml"))
        with open(cofn, "r") as mmdfile:
            yaml = mmdfile.read()
    except Exception as e:
        if "is not in the list of allowed SCMs" in str(e):
            rc = 403
        elif "Invalid SCM URL" in str(e):
            rc = 400
        else:
            rc = 500
        return str(e), rc
    finally:
        shutil.rmtree(td)
    mmd = modulemd.ModuleMetadata()
    try:
        mmd.loads(yaml)
    except:
        return "Invalid modulemd", 422
    if models.ModuleBuild.query.filter_by(name=mmd.name, version=mmd.version, release=mmd.release).first():
        return "Module already exists", 409

    module = models.ModuleBuild.create(
        db.session,
        conf,
        name=mmd.name,
        version=mmd.version,
        release=mmd.release,
        modulemd=yaml,
        scmurl=url,
    )

    def failure(message, code):
        # TODO, we should make some note of why it failed in the db..
        log.exception(message)
        module.transition(conf, models.BUILD_STATES["failed"])
        db.session.add(module)
        db.session.commit()
        return message, code

    for pkgname, pkg in mmd.components.rpms.packages.items():
        if pkg.get("repository") and not conf.rpms_allow_repository:
            return failure("Custom component repositories aren't allowed", 403)
        if pkg.get("cache") and not conf.rpms_allow_cache:
            return failure("Custom component caches aren't allowed", 403)
        if not pkg.get("repository"):
            pkg["repository"] = conf.rpms_default_repository + pkgname
        if not pkg.get("cache"):
            pkg["cache"] = conf.rpms_default_cache + pkgname
        if not pkg.get("commit"):
            try:
                pkg["commit"] = rida.scm.SCM(pkg["repository"]).get_latest()
            except Exception as e:
                return failure("Failed to get the latest commit: %s" % pkgname, 422)
        full_url = pkg["repository"] + "?#" + pkg["commit"]
        if not rida.scm.SCM(full_url).is_available():
            return failure("Cannot checkout %s" % pkgname, 422)
        build = models.ComponentBuild(
            module_id=module.id,
            package=pkgname,
            format="rpms",
            scmurl=full_url,
        )
        db.session.add(build)
    module.modulemd = mmd.dumps()
    module.transition(conf, models.BUILD_STATES["wait"])
    db.session.add(module)
    db.session.commit()
    logging.info("%s submitted build of %s-%s-%s", username, mmd.name,
            mmd.version, mmd.release)
    return jsonify(module.json()), 201


@app.route("/rida/module-builds/", methods=["GET"])
def query_builds():
    """Lists all tracked module builds."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    p_query = models.ModuleBuild.query.paginate(page, per_page, False)
    verbose_flag = request.args.get('verbose', 'false')

    json_data = {
        'meta': pagination_metadata(p_query)
    }

    if verbose_flag.lower() == 'true' or verbose_flag == '1':
        json_data['items'] = [{'id': item.id, 'state': item.state, 'tasks': item.tasks()}
                              for item in p_query.items]
    else:
        json_data['items'] = [{'id': item.id, 'state': item.state} for item in p_query.items]

    return jsonify(json_data), 200


@app.route("/rida/module-builds/<int:id>", methods=["GET"])
def query_build(id):
    """Lists details for the specified module builds."""
    module = models.ModuleBuild.query.filter_by(id=id).first()

    if module:

        return jsonify({
            "id": module.id,
            "state": module.state,
            "tasks": module.tasks()
        }), 200
    else:
        return "No such module found.", 404
