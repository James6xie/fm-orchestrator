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
from flask import request, jsonify
from flask.views import MethodView

from module_build_service import app, conf, log
from module_build_service import models, db
from module_build_service.utils import (
    pagination_metadata, filter_module_builds, submit_module_build_from_scm,
    submit_module_build_from_yaml, scm_url_schemes, get_scm_url_re, validate_optional_params)
from module_build_service.errors import (
    ValidationError, Forbidden, NotFound)

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
        verbose_flag = request.args.get('verbose', 'false')

        if id is None:
            # Lists all tracked module builds
            p_query = filter_module_builds(request)

            json_data = {
                'meta': pagination_metadata(p_query)
            }

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
                if verbose_flag.lower() == 'true' or verbose_flag == '1':
                    return jsonify(module.json()), 200
                else:
                    return jsonify(module.api_json()), 200
            else:
                raise NotFound('No such module found.')

    def post(self):
        username, groups = module_build_service.auth.get_user(request)

        if conf.allowed_groups and not (conf.allowed_groups & groups):
            raise Forbidden("%s is not in any of  %r, only %r" % (
                username, conf.allowed_groups, groups))

        kwargs = {"username": username}
        module = (self.post_file(**kwargs) if "multipart/form-data" in request.headers.get("Content-Type", "") else
                  self.post_scm(**kwargs))

        return jsonify(module.json()), 201

    def post_scm(self, username):
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
            raise Forbidden("The submitted scmurl %s is not allowed" % url)

        if not get_scm_url_re().match(url):
            log.error("The submitted scmurl %r is not valid" % url)
            raise Forbidden("The submitted scmurl %s is not valid" % url)

        if "branch" not in r:
            log.error('Missing branch')
            raise ValidationError('Missing branch')

        branch = r["branch"]

        # python-modulemd expects this to be bytes, not unicode.
        if isinstance(branch, unicode):
            branch = branch.encode('utf-8')

        validate_optional_params(r)
        optional_params = {k: v for k, v in r.items() if k != "scmurl" and k != 'branch'}
        return submit_module_build_from_scm(username, url, branch, allow_local_url=False, optional_params=optional_params)

    def post_file(self, username):
        if not conf.yaml_submit_allowed:
            raise Forbidden("YAML submission is not enabled")
        validate_optional_params(request.form)

        try:
            r = request.files["yaml"]
        except:
            log.error('Invalid file submitted')
            raise ValidationError('Invalid file submitted')

        return submit_module_build_from_yaml(username, r.read(), optional_params=request.form.to_dict())

    def patch(self, id):
        username, groups = module_build_service.auth.get_user(request)

        if conf.allowed_groups and not (conf.allowed_groups & groups):
            raise Forbidden("%s is not in any of  %r, only %r" % (
                username, conf.allowed_groups, groups))

        module = models.ModuleBuild.query.filter_by(id=id).first()
        if not module:
            raise NotFound('No such module found.')

        if module.owner != username:
            raise Forbidden('You are not owner of this build and '
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
    """ Registers version 1 of MBS API. """
    module_view = ModuleBuildAPI.as_view('module_builds')
    for key, val in api_v1.items():
        app.add_url_rule(val['url'],
                         endpoint=key,
                         view_func=module_view,
                         **val['options'])

register_api_v1()
