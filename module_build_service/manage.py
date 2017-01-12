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
from functools import wraps
import flask_migrate
import logging
import os
import ssl
from shutil import rmtree
import getpass

import fedmsg.config
import moksha.hub
import moksha.hub.hub
import moksha.hub.reactor

from module_build_service import app, conf, db
from module_build_service import models
from module_build_service.pdc import (
    get_pdc_client_session, get_module, get_module_runtime_dependencies,
    get_module_tag, get_module_build_dependencies)
from module_build_service.utils import (
    submit_module_build,
)
from module_build_service.messaging import RidaModule
import module_build_service.messaging
import module_build_service.scheduler.consumer


manager = Manager(app)
help_args = ('-?', '--help')
manager.help_args = help_args
migrate = flask_migrate.Migrate(app, db)
manager.add_command('db', flask_migrate.MigrateCommand)


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

    # Then, establish the ssl context and return it
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
    ssl_ctx.load_cert_chain(conf.ssl_certificate_file,
                            conf.ssl_certificate_key_file)
    ssl_ctx.verify_mode = ssl.CERT_OPTIONAL
    ssl_ctx.load_verify_locations(cafile=conf.ssl_ca_certificate_file)
    return ssl_ctx


@manager.command
def testpdc():
    """ A helper function to test PDC interaction
    """
    cfg = conf
    cfg.pdc_url = "http://modularity.fedorainfracloud.org:8080/rest_api/v1"
    cfg.pdc_insecure = True
    cfg.pdc_develop = True

    pdc_session = get_pdc_client_session(cfg)
    module = get_module(pdc_session, {'name': 'testmodule', 'version': '4.3.43',
                                      'release': '1'})

    if module:
        print("pdc_data=%s" % str(module))
        print("deps=%s" % get_module_runtime_dependencies(pdc_session, module))
        print("build_deps=%s" % get_module_build_dependencies(
            pdc_session, module))
        print("tag=%s" % get_module_tag(pdc_session, module))
    else:
        print('module was not found')


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


@manager.command
def build_module_locally(url):
    """ Performs local module build using Mock
    """
    conf.set_item("system", "mock")

    # Use our own local SQLite3 database.
    confdir = os.path.abspath(os.path.dirname(__file__))
    dbdir = os.path.abspath(os.path.join(confdir, '..')) if confdir.endswith('conf') \
        else confdir
    dbpath = '/{0}'.format(os.path.join(dbdir, '.mbs_local_build.db'))
    dburi = 'sqlite://' + dbpath
    app.config["SQLALCHEMY_DATABASE_URI"] = dburi
    conf.set_item("sqlalchemy_database_uri", dburi)
    if os.path.exists(dbpath):
        os.remove(dbpath)

    # Create the database and insert fake base-runtime module there. This is
    # normally done by the flask_migrate.upgrade(), but I (jkaluza) do not
    # call it here, because after that call, all the logged messages are not
    # printed to stdout/stderr and are ignored... I did not find a way how to
    # fix that.
    #
    # In the future, we should use PDC to get what we need from the fake module,
    # so it's probably not big problem.
    db.create_all()

    username = getpass.getuser()
    submit_module_build(username, url, allow_local_url=True)

    stop = module_build_service.scheduler.make_simple_stop_condition(db.session)
    initial_messages = [RidaModule("local module build", 1, 1)]

    # Run the consumer until stop_condition returns True
    module_build_service.scheduler.main(initial_messages, stop)


@manager.command
def gendevfedmsgcert(pki_dir='/etc/module_build_service', force=False):
    """ Creates a CA, a certificate signed by that CA, and generates a CRL.
    """
    from OpenSSL import crypto

    if os.path.exists(pki_dir):
        if force:
            rmtree(pki_dir)
        else:
            print('The directory "{}" already exists'.format(pki_dir))
            return

    os.mkdir(pki_dir)

    ca_crt_path = os.path.join(pki_dir, 'ca.crt')
    ca_key_path = os.path.join(pki_dir, 'ca.key')
    msg_key_path = os.path.join(pki_dir, 'localhost.key')
    msg_crt_path = os.path.join(pki_dir, 'localhost.crt')
    ca_crl = os.path.join(pki_dir, 'ca.crl')

    # Create a key pair for the CA
    ca_key = crypto.PKey()
    ca_key.generate_key(crypto.TYPE_RSA, 2048)

    with open(ca_key_path, 'w') as ca_key_file:
        ca_key_file.write(
            crypto.dump_privatekey(crypto.FILETYPE_PEM, ca_key))

    # Create a self-signed CA cert
    ca_cert = crypto.X509()
    ca_subject = ca_cert.get_subject()
    ca_subject.C = 'US'
    ca_subject.ST = 'MA'
    ca_subject.L = 'Boston'
    ca_subject.O = 'Development'
    ca_subject.CN = 'Dev-CA'
    ca_cert.set_serial_number(1)
    ca_cert.gmtime_adj_notBefore(0)
    ca_cert.gmtime_adj_notAfter(315360000)  # 10 years
    ca_cert.set_issuer(ca_cert.get_subject())
    ca_cert.set_pubkey(ca_key)
    ca_cert.add_extensions([
        crypto.X509Extension('basicConstraints', True, 'CA:true')])
    ca_cert.sign(ca_key, 'sha256')

    with open(ca_crt_path, 'w') as ca_crt_file:
        ca_crt_file.write(
            crypto.dump_certificate(crypto.FILETYPE_PEM, ca_cert))

    # Create a key pair for the message signing cert
    msg_key = crypto.PKey()
    msg_key.generate_key(crypto.TYPE_RSA, 2048)

    with open(msg_key_path, 'w') as msg_key_file:
        msg_key_file.write(
            crypto.dump_privatekey(crypto.FILETYPE_PEM, msg_key))

    # Create a cert signed by the CA
    msg_cert = crypto.X509()
    msg_cert_subject = msg_cert.get_subject()
    msg_cert_subject.C = 'US'
    msg_cert_subject.ST = 'MA'
    msg_cert_subject.L = 'Boston'
    msg_cert_subject.O = 'Development'
    msg_cert_subject.CN = 'localhost'
    msg_cert.set_serial_number(2)
    msg_cert.gmtime_adj_notBefore(0)
    msg_cert.gmtime_adj_notAfter(315360000)  # 10 years
    msg_cert.set_issuer(ca_cert.get_subject())
    msg_cert.set_pubkey(msg_key)
    cert_extensions = [
        crypto.X509Extension(
            'keyUsage', True,
            'digitalSignature, keyEncipherment, nonRepudiation'),
        crypto.X509Extension('extendedKeyUsage', True, 'serverAuth'),
        crypto.X509Extension('basicConstraints', True, 'CA:false'),
        crypto.X509Extension('crlDistributionPoints', False,
                             'URI:http://localhost/crl/ca.crl'),
        crypto.X509Extension('authorityInfoAccess', False,
                             'caIssuers;URI:http://localhost/crl/ca.crt'),
        crypto.X509Extension('subjectKeyIdentifier', False, 'hash',
                             subject=ca_cert)
    ]
    msg_cert.add_extensions(cert_extensions)
    msg_cert.sign(ca_key, 'sha256')

    with open(msg_crt_path, 'w') as msg_crt_file:
        msg_crt_file.write(
            crypto.dump_certificate(crypto.FILETYPE_PEM, msg_cert))

    # Generate the CRL
    with open(ca_crl, 'w') as ca_crl_file:
        ca_crl_file.write(
            crypto.CRL().export(ca_cert, ca_key, type=crypto.FILETYPE_PEM,
                                days=3650, digest='sha256'))


@console_script_help
@manager.command
def generatelocalhostcert():
    """ Creates a public/private key pair for message signing and the frontend
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
    cert.set_serial_number(2)
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
