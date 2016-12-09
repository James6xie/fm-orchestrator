Development
===========

We have two mechanisms for quickly setting up a development environment.  `docker-compose` and `vagrant`.

In order to to setup a development environment, it is required that you have
your Fedora kerberos credentials generated in a *special location*. Before
starting your development environment, run the following::

    $ KRB5CCNAME=FILE:/var/tmp/krbcc kinit YOUR_USERNAME@STG.FEDORAPROJECT.ORG

If you have problems in later steps with kerberos reading those credentials
inside the `scheduler` container, you should check that `/var/tmp/krbcc` exists
on your machine and that *it is not a directory*.  Try removing it with `$ sudo
rm -rf /var/tmp/krbcc` and running `kinit` again.

Docker
------

You can use docker containers for development.  Here's a guide on how to setup
`docker <https://developer.fedoraproject.org/tools/docker/about.html>`_ and
`docker-compose <https://developer.fedoraproject.org/tools/docker/compose.html>`_
for Fedora users (it's just a `dnf install` away).  Mac users should see `these
docs <https://docs.docker.com/docker-for-mac/>`_.

After your docker engine is set up and running and docker-compose is installed,
you can start the entire development environment with a single command::

    $ sudo docker-compose up

That will start a number of services in containers, including the `frontend`
and the backend `scheduler`. You can submit a local test build with the
`submit-build.py` script, which should submit an HTTP POST to the frontend,
requesting a build.

You may want to wipe your local development database from time to time. Try the
following commands, and you should have a fresh environment::

    $ rm module_build_service.db
    $ docker-compose down -v && docker-compose up

If things get really screwy and your containers won't start properly, the best thing
to do is to rebuild the environment from scratch::

    $ docker-compose down -v
    $ docker-compose build --no-cache --pull

The first command will stop and remove all your containers and volumes and the second
command will pull the latest base image and perform a clean build without using the cache.

Vagrant
-------

If you are using VirtualBox, you will need to install the Vagrant plugin `vagrant-vbguest`.
This plugin automatically installs guest additions to Vagrant guests that do not have them installed.
The official Fedora Vagrant box unfortunately does not contain the guest additions, and they are needed for folder syncing::

    $ vagrant plugin install vagrant-vbguest

To launch Vagrant, run (depending on your OS, you may need to run it with sudo)::

    $ vagrant up

This will start module_build_service's frontend (API) and scheduler. To access the frontend, visit the following URL::

    https://127.0.0.1:5000/module-build-service/1/module-builds/

At any point you may enter the guest VM with::

    $ vagrant ssh

To start the frontend manually, run the following inside the guest::

    $ mbs-frontend

To start the scheduler manually, run the following inside the guest::

    $ mbs-daemon

Alternatively, you can restart the Vagrant guest, which inherently starts/restarts the frontend and the scheduler with::

    $ vagrant reload

Logging
-------

If you're running module_build_service from scm, then the DevConfiguration from
`conf/config.py` which contains `LOG_LEVEL=debug` should get applied. See more about
it in `module_build_service/config.py`, `app.config.from_object()`.

Environment
-----------

The environment variable `MODULE_BUILD_SERVICE_DEVELOPER_ENV`, which if set to "1", indicates to the Module Build Service that the development configuration should be used. Docker and Vagrant are being run with this environment variable set. 

Anytime, you can do::

    $ export MODULE_BUILD_SERVICE_DEVELOPER_ENV=1

fedmsg Signing for Development
------------------------------

In order to enable fedmsg signing in development, you will need to follow a series of steps.
Note that this will conflict with signed messages from a different CA that are on the message bus, so this may cause unexpected results.

Generate the CA, the certificate to be used by fedmsg, and the CRL with::

    $ python manage.py gendevfedmsgcert

Setup Apache to host the CRL::

    $ dnf install httpd && systemctl enable httpd && systemctl start httpd
    $ mkdir -p /var/www/html/crl
    $ ln -s /opt/module_build_service/pki/ca.crl /var/www/html/crl/ca.crl
    $ ln -s /opt/module_build_service/pki/ca.crt /var/www/html/crl/ca.crt

Create a directory to house the fedmsg cache::

    $ mkdir -p /etc/pki/fedmsg

Then uncomment the fedmsg signing configuration in fedmsg.d/module_build_service.py.
