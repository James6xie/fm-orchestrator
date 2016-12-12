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

import json
import module_build_service.auth
import re

from flask import request, jsonify
from flask.views import MethodView

from module_build_service import app, conf, log
from module_build_service import models, db
from module_build_service.utils import pagination_metadata, filter_module_builds, submit_module_build, scm_url_schemes
from module_build_service.errors import (
    ValidationError, Unauthorized, NotFound)

api_v1 = {
    'module_builds': {
        'url': '/module-build-service/1/module-builds/',
        'options': {
            'methods': ['POST'],
        }
    },
    'module_builds_list': {
        'url': '/module-build-service/1/module-builds/',
        'options': {
            'defaults': {'id': None},
            'methods': ['GET'],
        }
    },
    'module_build': {
        'url': '/module-build-service/1/module-builds/<int:id>',
        'options': {
            'methods': ['GET', 'PATCH'],
        }
    },
}

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
        username = module_build_service.auth.get_username(request)

        if conf.require_packager:
            module_build_service.auth.assert_is_packager(username, fas_kwargs=dict(
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

        schemes_re = '|'.join(map(re.escape, scm_url_schemes(terse=True)))
        scmurl_re = re.compile(
            r"(?P<giturl>(?:(?P<scheme>(" + schemes_re + r"))://(?P<host>[^/]+))?"
            r"(?P<repopath>/[^\?]+))\?(?P<modpath>[^#]*)#(?P<revision>.+)")
        if not scmurl_re.match(url):
            log.error("The submitted scmurl %r is not valid" % url)
            raise Unauthorized("The submitted scmurl %s is not valid" % url)

        module = submit_module_build(username, url, allow_local_url=False)
        return jsonify(module.json()), 201

    def patch(self, id):
        username = module_build_service.auth.get_username(request)

        if conf.require_packager:
            module_build_service.auth.assert_is_packager(
                username,
                fas_kwargs=dict(
                    base_url=conf.fas_url,
                    username=conf.fas_username,
                    password=conf.fas_password
                )
            )

        module = models.ModuleBuild.query.filter_by(id=id).first()
        if not module:
            raise NotFound('No such module found.')

        if module.owner != username:
            raise Unauthorized('You are not owner of this build and '
                               'therefore cannot modify it.')

        try:
            r = json.loads(request.get_data().decode("utf-8"))
        except:
            log.error('Invalid JSON submitted')
            raise ValidationError('Invalid JSON submitted')

        if not r.get('state'):
            log.error('Invalid JSON submitted')
            raise ValidationError('Invalid JSON submitted')

        if r['state'] == 'failed' \
                or r['state'] == str(models.BUILD_STATES['failed']):
            module.transition(conf, models.BUILD_STATES["failed"],
                              "Canceled by %s." % username)
        else:
            log.error('The provided state change of "{}" is not supported'
                      .format(r['state']))
            raise ValidationError('The provided state change is not supported')
        db.session.add(module)
        db.session.commit()

        return jsonify(module.api_json()), 200


def register_api_v1():
    """ Registers version 1 of Rida API. """
    module_view = ModuleBuildAPI.as_view('module_builds')
    for key, val in api_v1.items():
        app.add_url_rule(val['url'],
                         endpoint=key,
                         view_func=module_view,
                         **val['options'])

register_api_v1()
