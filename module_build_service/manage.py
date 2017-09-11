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

import random
from flask_script import Manager
from functools import wraps
import flask_migrate
import logging
import os
import getpass

from module_build_service import app, conf, db, create_app
from module_build_service import models
from module_build_service.utils import (
    submit_module_build_from_scm,
    load_local_builds,
)
import module_build_service.messaging
import module_build_service.scheduler.consumer


manager = Manager(create_app)
help_args = ('-?', '--help')
manager.help_args = help_args
migrate = flask_migrate.Migrate(app, db)
manager.add_command('db', flask_migrate.MigrateCommand)
manager.add_option('-d', '--debug', dest='debug', action='store_true')
manager.add_option('-v', '--verbose', dest='verbose', action='store_true')
manager.add_option('-q', '--quiet', dest='quiet', action='store_true')


def console_script_help(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        import sys
        if any([arg in help_args for arg in sys.argv[1:]]):
            command = os.path.basename(sys.argv[0])
            print("""{0}

Usage: {0} [{1}]

See also:
  mbs-manager(1)""".format(command,
                           '|'.join(help_args)))
            sys.exit(2)
        r = f(*args, **kwargs)
        return r
    return wrapped


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

    return (os.path.abspath(conf.ssl_certificate_file),
            os.path.abspath(conf.ssl_certificate_key_file))


@console_script_help
@manager.command
def upgradedb():
    """ Upgrades the database schema to the latest revision
    """
    app.config["SERVER_NAME"] = 'localhost'
    # TODO: configurable?
    migrations_dir = os.path.join(os.path.abspath(os.path.dirname(__file__)),
                                  'migrations')
    with app.app_context():
        flask_migrate.upgrade(directory=migrations_dir)


@manager.command
def cleardb():
    """ Clears the database
    """
    models.ModuleBuild.query.delete()
    models.ComponentBuild.query.delete()


@manager.option('branch')
@manager.option('url')
@manager.option('--skiptests', action='store_true')
@manager.option('-l', '--add-local-build', action='append', default=None, dest='local_build_nsvs')
def build_module_locally(url, branch, local_build_nsvs=None, skiptests=False):
    """ Performs local module build using Mock
    """
    if 'SERVER_NAME' not in app.config or not app.config['SERVER_NAME']:
        app.config["SERVER_NAME"] = 'localhost'

    with app.app_context():
        conf.set_item("system", "mock")

        # Use our own local SQLite3 database.
        confdir = os.path.abspath(os.getcwd())
        dbdir = os.path.abspath(os.path.join(confdir, '..')) if confdir.endswith('conf') \
            else confdir
        dbpath = '/{0}'.format(os.path.join(dbdir, '.mbs_local_build.db'))
        dburi = 'sqlite://' + dbpath
        app.config["SQLALCHEMY_DATABASE_URI"] = dburi
        conf.set_item("sqlalchemy_database_uri", dburi)
        if os.path.exists(dbpath):
            os.remove(dbpath)

        db.create_all()
        load_local_builds(local_build_nsvs)

        username = getpass.getuser()
        submit_module_build_from_scm(username, url, branch, allow_local_url=True,
                                     skiptests=skiptests)

        stop = module_build_service.scheduler.make_simple_stop_condition(db.session)

        # Run the consumer until stop_condition returns True
        module_build_service.scheduler.main([], stop)


@console_script_help
@manager.command
def generatelocalhostcert():
    """ Creates a public/private key pair for the frontend
    """
    from OpenSSL import crypto
    cert_key = crypto.PKey()
    cert_key.generate_key(crypto.TYPE_RSA, 2048)

    with open(conf.ssl_certificate_key_file, 'w') as cert_key_file:
        os.chmod(conf.ssl_certificate_key_file, 0o600)
        cert_key_file.write(
            crypto.dump_privatekey(crypto.FILETYPE_PEM, cert_key))

    cert = crypto.X509()
    msg_cert_subject = cert.get_subject()
    msg_cert_subject.C = 'US'
    msg_cert_subject.ST = 'MA'
    msg_cert_subject.L = 'Boston'
    msg_cert_subject.O = 'Development'
    msg_cert_subject.CN = 'localhost'
    cert.set_serial_number(random.randint(2, 99999999))
    cert.gmtime_adj_notBefore(0)
    cert.gmtime_adj_notAfter(315360000)  # 10 years
    cert.set_issuer(cert.get_subject())
    cert.set_pubkey(cert_key)
    cert_extensions = [
        crypto.X509Extension(
            'keyUsage', True,
            'digitalSignature, keyEncipherment, nonRepudiation'),
        crypto.X509Extension('extendedKeyUsage', True, 'serverAuth'),
    ]
    cert.add_extensions(cert_extensions)
    cert.sign(cert_key, 'sha256')

    with open(conf.ssl_certificate_file, 'w') as cert_file:
        cert_file.write(
            crypto.dump_certificate(crypto.FILETYPE_PEM, cert))


@console_script_help
@manager.command
def runssl(host=conf.host, port=conf.port, debug=conf.debug):
    """ Runs the Flask app with the HTTPS settings configured in config.py
    """
    logging.info('Starting Module Build Service frontend')

    ssl_ctx = _establish_ssl_context()
    app.run(
        host=host,
        port=port,
        ssl_context=ssl_ctx,
        debug=debug
    )


def manager_wrapper():
    manager.run()

if __name__ == "__main__":
    manager_wrapper()
