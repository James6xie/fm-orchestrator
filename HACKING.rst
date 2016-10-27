Development
===========

We have two mechanisms for quickly setting up a development environment.  `docker-compose` and `vagrant`.

In order to to setup a development environment, it is required that you have
your FAS (Fedora Account System) certificates generated and located in your
home directory. For more information on these certificates, visit the `Koji
documentation <https://fedoraproject.org/wiki/Using_the_Koji_build_system#Fedora_Certificates>`_.

Docker
------

You can use docker containers for development.  Here's a guide how to setup
`docker <https://developer.fedoraproject.org/tools/docker/about.html>`_ and
`docker-compose <https://developer.fedoraproject.org/tools/docker/compose.html>`_
(it's just a `dnf install` away).

After your docker engine is set up and running, and docker-compose installed
you can start whole system with a single command::

    $ docker-compose up

That will start a number of services in containers, including the `frontend`
and the backend `scheduler`. You can submit a local test build with the
`submit-build.sh` script, which should submit an HTTP POST to the frontend,
requesting a build.

You may want to wipe your local development database from time to time to try
something starting from scratch.  Try the following commands, and you should
have a fresh environment::

    $ rm module_build_service.db
    $ docker-compose down -v && docker-compose up

If things get really screwy and your container won't start properly, best thing
to do is to rebuild the environment from scratch::

    $ docker-compose down -v
    $ docker-compose build --no-cache --pull

First command will stop and remove all containers and volumes and second
command will pull latest base image and perform a clean build without cache.

Vagrant
-------

Once your environment is setup, run (depending on your OS, you may need to run it with sudo)::

    $ vagrant up

This will start module_build_service's frontend (API) and scheduler. To access the frontend, visit the following URL::

    https://127.0.0.1:5000/module-build-service/1/module-builds/

At any point you may enter the guest VM with::

    $ vagrant ssh

To start the frontend manually, run the following inside the guest::

    $ cd /opt/module_build_service/src
    $ python manage.py runssl --debug

To start the scheduler manually, run the following inside the guest::

    $ cd /opt/module_build_service/src
    $ python module_build_service_daemon.py

Alternatively, you can restart the Vagrant guest, which inherently starts/restarts the frontend and the scheduler with::

    $ vagrant reload

Logging
------

If you're running module_build_service from scm then the DevConfiguration from config.py which contains LOG_LEVEL=debug should get applied. If you're having trouble just change LOG_LEVEL in BaseConfiguration.
See more about it in module_build_service/__init__.py config.from_object()


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
