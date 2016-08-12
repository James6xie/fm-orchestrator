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
# Written by Matt Prahl <mprahl@redhat.com> except for the test functions

from flask_script import Manager
import flask_migrate
import logging
import os
import ssl

from rida import app, conf, db
from rida.config import Config
from rida.pdc import get_pdc_client_session, get_module, get_module_runtime_dependencies, get_module_tag, \
    get_module_build_dependencies
import rida.auth


manager = Manager(app)
migrate = flask_migrate.Migrate(app, db)
manager.add_command('db', flask_migrate.MigrateCommand)


def _establish_ssl_context():
    if not conf.ssl_enabled:
        return None
    # First, do some validation of the configuration
    attributes = (
        'ssl_certificate_file',
        'ssl_certificate_key_file',
        'ssl_ca_certificate_file',
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


@manager.command
def testpdc():
    """ A helper function to test pdc interaction
    """
    cfg = Config()
    cfg.pdc_url = "http://modularity.fedorainfracloud.org:8080/rest_api/v1"
    cfg.pdc_insecure = True
    cfg.pdc_develop = True

    pdc_session = get_pdc_client_session(cfg)
    module = get_module(pdc_session, {'name': 'testmodule', 'version': '4.3.43', 'release': '1'})

    if module:
        print ("pdc_data=%s" % str(module))
        print ("deps=%s" % get_module_runtime_dependencies(pdc_session, module))
        print ("build_deps=%s" % get_module_build_dependencies(pdc_session, module))
        print ("tag=%s" % get_module_tag(pdc_session, module))
    else:
        print ('module was not found')


@manager.command
def testbuildroot():
    """ A helper function to test buildroot creation
    """

    # Do a locally namespaced import here to avoid importing py2-only libs in a
    # py3 runtime.
    from rida.builder import KojiModuleBuilder #, Builder

    cfg = Config()
    cfg.koji_profile = "koji"
    cfg.koji_config = "/etc/rida/koji.conf"
    cfg.koji_arches = ["x86_64", "i686"]

    mb = KojiModuleBuilder(module="testmodule-1.0", config=cfg, tag="testmodule-1.0")  # or By using Builder
    # mb = Builder(module="testmodule-1.0", backend="koji", config=cfg)

    mb.buildroot_connect()
    mb.buildroot_add_repos(["fakemodulebuild-1.0-0",])
    srpm_path = mb.get_disttag_srpm("testmodule-1.0")
    task_id = mb.build(artifact_name="module-build-macros", source=srpm_path)
    #task_id = mb.build(artifact_name="fedora-release",
    #                   source="git://pkgs.fedoraproject.org/rpms/fedora-release?#b1d65f349dca2f597b278a4aad9e41fb0aa96fc9")
    #mb.buildroot_add_artifacts(["fedora-release-24-2", ])  # just example with disttag macro
    #mb.buildroot_ready(artifact="fedora-release-24-2")
    new_task_id = mb.build(artifact_name="module-build-macros", source=srpm_path)

    assert new_task_id == task_id, "Component was already built. Expected same task_id (%s != %s). Fix it!" % (new_task_id, task_id)



@manager.command
def upgradedb():
    """ Upgrades the database schema to the latest revision
    """
    flask_migrate.upgrade()


@manager.command
def runssl(host=conf.host, port=conf.port, debug=False):
    """ Runs the Flask app with the HTTPS settings configured in config.py
    """
    logging.info('Starting Rida')
    ssl_ctx = _establish_ssl_context()
    app.run(
        host=host,
        port=port,
        request_handler=rida.auth.ClientCertRequestHandler,
        ssl_context=ssl_ctx,
        debug=debug
    )

if __name__ == "__main__":
    manager.run()
