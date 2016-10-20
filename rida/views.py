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
from flask.views import MethodView
import json
import modulemd
import os
import rida.auth
import rida.scm
import shutil
import tempfile
import re
from rida import app, conf, db, log
from rida import models
from rida.utils import pagination_metadata, filter_module_builds
from rida.errors import (
    ValidationError, Unauthorized, UnprocessableEntity, Conflict, NotFound)
from multiprocessing.dummy import Pool as ThreadPool


class ModuleBuildAPI(MethodView):

    def get(self, id):
        if id is None:
            # Lists all tracked module builds
            p_query = filter_module_builds(request)

            json_data = {
                'meta': pagination_metadata(p_query)
            }

            verbose_flag = request.args.get('verbose', 'false')

            if verbose_flag.lower() == 'true' or verbose_flag == '1':
                json_data['items'] = [item.api_json() for item in p_query.items]
            else:
                json_data['items'] = [{'id': item.id, 'state': item.state} for
                                      item in p_query.items]

            return jsonify(json_data), 200
        else:
            # Lists details for the specified module builds
            module = models.ModuleBuild.query.filter_by(id=id).first()

            if module:
                return jsonify(module.api_json()), 200
            else:
                raise NotFound('No such module found.')

    def post(self):
        username = rida.auth.get_username(request.environ)
        rida.auth.assert_is_packager(username, fas_kwargs=dict(
            base_url=conf.fas_url,
            username=conf.fas_username,
            password=conf.fas_password))

        try:
            r = json.loads(request.get_data().decode("utf-8"))
        except:
            log.error('Invalid JSON submitted')
            raise ValidationError('Invalid JSON submitted')

        if "scmurl" not in r:
            log.error('Missing scmurl')
            raise ValidationError('Missing scmurl')

        url = r["scmurl"]
        if not any(url.startswith(prefix) for prefix in conf.scmurls):
            log.error("The submitted scmurl %r is not allowed" % url)
            raise Unauthorized("The submitted scmurl %s is not allowed" % url)

        scmurl_re = re.compile(
            r"(?P<giturl>(?:(?P<scheme>git)://(?P<host>[^/]+))?"
            r"(?P<repopath>/[^\?]+))\?(?P<modpath>[^#]*)#(?P<revision>.+)")
        if not scmurl_re.match(url):
            log.error("The submitted scmurl %r is not valid" % url)
            raise Unauthorized("The submitted scmurl %s is not valid" % url)

        yaml = ""
        td = None
        try:
            log.debug('Verifying modulemd')
            td = tempfile.mkdtemp()
            scm = rida.scm.SCM(url, conf.scmurls)
            cod = scm.checkout(td)
            cofn = os.path.join(cod, (scm.name + ".yaml"))

            with open(cofn, "r") as mmdfile:
                yaml = mmdfile.read()
        finally:
            try:
                if td is not None:
                    shutil.rmtree(td)
            except Exception as e:
                log.warning(
                    "Failed to remove temporary directory {!r}: {}".format(
                        td, str(e)))

        mmd = modulemd.ModuleMetadata()
        try:
            mmd.loads(yaml)
        except:
            log.error('Invalid modulemd')
            raise UnprocessableEntity('Invalid modulemd')

        module = models.ModuleBuild.query.filter_by(name=mmd.name,
                                              version=mmd.version,
                                              release=mmd.release).first()
        if module:
            log.debug('Checking whether module build already exist.')
             # TODO: make this configurable, we might want to allow
             # resubmitting any stuck build on DEV no matter the state
            if module.state not in (models.BUILD_STATES['failed']):
                log.error('Module (state=%s) already exists. '
                          'Only new or failed builds are allowed.'
                          % module.state)
                raise Conflict('Module (state=%s) already exists. '
                               'Only new or failed builds are allowed.'
                               % module.state)
            log.debug('Resuming existing module build %r' % module)
            module.username = username
            module.transition(conf, models.BUILD_STATES["init"])
            log.info("Resumed existing module build in previous state %s"
                     % module.state)
        else:
            log.debug('Creating new module build')
            module = models.ModuleBuild.create(
                db.session,
                conf,
                name=mmd.name,
                version=mmd.version,
                release=mmd.release,
                modulemd=yaml,
                scmurl=url,
                username=username
            )

        # List of (pkg_name, git_url) tuples to be used to check
        # the availability of git URLs paralelly later.
        full_urls = []

        for pkgname, pkg in mmd.components.rpms.packages.items():
            try:
                if pkg.get("repository") and not conf.rpms_allow_repository:
                    raise Unauthorized(
                        "Custom component repositories aren't allowed")
                if pkg.get("cache") and not conf.rpms_allow_cache:
                    raise Unauthorized("Custom component caches aren't allowed")
                if not pkg.get("repository"):
                    pkg["repository"] = conf.rpms_default_repository + pkgname
                if not pkg.get("cache"):
                    pkg["cache"] = conf.rpms_default_cache + pkgname
                if not pkg.get("commit"):
                    try:
                        pkg["commit"] = rida.scm.SCM(
                            pkg["repository"]).get_latest()
                    except Exception as e:
                        raise UnprocessableEntity(
                            "Failed to get the latest commit: %s" % pkgname)
            except Exception:
                module.transition(conf, models.BUILD_STATES["failed"])
                db.session.add(module)
                db.session.commit()
                raise

            full_url = pkg["repository"] + "?#" + pkg["commit"]
            full_urls.append((pkgname, full_url))

        log.debug("Checking scm urls")
        # Checks the availability of SCM urls.
        pool = ThreadPool(10)
        err_msgs = pool.map(lambda data: "Cannot checkout {}".format(data[0])
                            if not rida.scm.SCM(data[1]).is_available()
                            else None, full_urls)
        for err_msg in err_msgs:
            if err_msg:
                raise UnprocessableEntity(err_msg)

        for pkgname, pkg in mmd.components.rpms.packages.items():
            full_url = pkg["repository"] + "?#" + pkg["commit"]

            existing_build = models.ComponentBuild.query.filter_by(
                module_id=module.id, package=pkgname).first()
            if (existing_build
                    and existing_build.state != models.BUILD_STATES['done']):
                existing_build.state = models.BUILD_STATES['init']
                db.session.add(existing_build)
            else:
                # XXX: what about components that were present in previous
                # builds but are gone now (component reduction)?
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
        log.info("%s submitted build of %s-%s-%s", username, mmd.name,
                 mmd.version, mmd.release)
        return jsonify(module.json()), 201


def register_v1_api():
    """ Registers version 1 of Rida API. """
    module_view = ModuleBuildAPI.as_view('module_builds')
    app.add_url_rule('/rida/1/module-builds/', defaults={'id': None},
                     view_func=module_view, methods=['GET'])
    app.add_url_rule('/rida/1/module-builds/', view_func=module_view,
                     methods=['POST'])
    app.add_url_rule('/rida/1/module-builds/<int:id>', view_func=module_view,
                     methods=['GET'])

register_v1_api()
