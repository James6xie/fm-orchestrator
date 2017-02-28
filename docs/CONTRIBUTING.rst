Development
===========

We have two mechanisms for quickly setting up a development environment,
`docker-compose` and `vagrant`.

In order to to setup a development environment, it is required that you have
your Fedora kerberos credentials generated in a *special location*. Before
starting your development environment, run the following::

    $ KRB5CCNAME=FILE:/tmp/mbs-krbcc kinit YOUR_USERNAME@STG.FEDORAPROJECT.ORG

If you have problems in later steps with kerberos reading those credentials
inside the `scheduler` container, you should check that `/var/tmp/krbcc` exists
on your machine and that *it is not a directory*. Try removing it with `$ sudo
rm -rf /var/tmp/krbcc` and running `kinit` again. Also, check for permissions
and SELinux context of the credentials cache file.

PDC and pdc-updater
-------------------

To be able to communicate with PDC, your development instance will need to
be able to access the URL defined in the configuration option `PDC_URL`,
located in your local `conf/config.py`

To communicate with pdc-updater, you will need to configure SSH on your host
machine to forward remote ports from pdc-updater's devel instance, typically
`modularity.fedorainfracloud.org`. This enables communication between PDC
and your Module Build Service development instance.

Your `ssh_config` should look like this::

    Host MODULARITY-DEV
        HostName modularity.fedorainfracloud.org
        User fedora
        RemoteForward 300x 127.0.0.1:5001  # x is one of 0...9

The configuration above assumes that the development instance with
pdc-updater has the following endpoints configured (typically in
`/etc/fedmsg.d/endpoints.py`)::

    endpoints={
        "rida.local": [
            "tcp://127.0.0.1:300%i" % i for i in range(10)
        ],
        ...

Docker
------

You can use docker containers for development. Here's a guide on how to setup
`docker <https://developer.fedoraproject.org/tools/docker/about.html>`_ and
`docker-compose <https://developer.fedoraproject.org/tools/docker/compose.html>`_
for Fedora users (it's just a `dnf install` away). Mac users should see `these
docs <https://docs.docker.com/docker-for-mac/>`_.

After your docker engine is set up and running and docker-compose is installed,
you can start the entire development environment with a single command::

    $ sudo docker-compose up

That will start a number of services in containers, including the `frontend`
and the backend `scheduler`.

You may want to wipe your local development database from time to time. Try the
following commands, and you should have a fresh environment::

    $ rm module_build_service.db
    $ docker-compose down -v && docker-compose up

If things get really screwy and your containers won't start properly, the
best thing to do is to rebuild the environment from scratch::

    $ docker-compose down -v
    $ docker-compose build --no-cache --pull

The first command will stop and remove all your containers and volumes and
the second command will pull the latest base image and perform a clean build
without using the cache.

Vagrant
-------

If you are using VirtualBox, you will need to install the Vagrant plugin
`vagrant-vbguest`. This plugin automatically installs guest additions to
Vagrant guests that do not have them installed. The official Fedora Vagrant
box unfortunately does not contain the guest additions, and they are needed
for folder syncing::

    $ vagrant plugin install vagrant-vbguest

To launch Vagrant, run (depending on your OS, you may need to run it with sudo)::

    $ vagrant up

This will start module_build_service's frontend (API) and scheduler. To
access the frontend, visit the following URL::

    https://127.0.0.1:5000/module-build-service/1/module-builds/

At any point you may enter the guest VM with::

    $ vagrant ssh

The outputs of running services can be tailed as follows::

    $ tail -f /tmp/*.out &

To start the frontend manually, run the following inside the guest::

    $ mbs-frontend

To start the scheduler manually, run the following at
`/tmp/module_build_service` inside the guest::

    $ fedmsg-hub

Alternatively, you can restart the Vagrant guest, which inherently
starts/restarts the frontend and the scheduler with::

    $ vagrant reload

Logging
-------

If you're running module_build_service from scm, then the DevConfiguration
from `conf/config.py` which contains `LOG_LEVEL=debug` should get applied. See
more about it in `module_build_service/config.py`, `app.config.from_object()`.

Environment
-----------

The environment variable `MODULE_BUILD_SERVICE_DEVELOPER_ENV`, which if
set to "1", indicates to the Module Build Service that the development
configuration should be used. Docker and Vagrant are being run with this
environment variable set. This overrides all configuration settings and forces
usage of DevConfiguration section in `conf/config.py` from MBS's develop
instance.

Prior to starting MBS, you can force development mode::

    $ export MODULE_BUILD_SERVICE_DEVELOPER_ENV=1

Module Submission
-----------------

You can submit a local test build with the `contrib/submit_build.py` script,
which should submit an HTTP POST to the frontend, requesting a build::

    $ cd contrib/ && python submit_build.py

This script uses `scmurl` from the input file `contrib/submit-build.json`. Note
that authentication will be required for submitting a module build. Follow
the on-screen instructions to authenticate.

See also `SCMURLS` in `conf/config.py` for list of allowed SCM URLs.

fedmsg Signing for Development
------------------------------

In order to enable fedmsg signing in development, you will need to follow
a series of steps. Note that this will conflict with signed messages from
a different CA that are on the message bus, so this may cause unexpected results.

Generate the CA, the certificate to be used by fedmsg, and the CRL with::

    $ python manage.py gendevfedmsgcert

Setup Apache to host the CRL::

    $ dnf install httpd && systemctl enable httpd && systemctl start httpd
    $ mkdir -p /var/www/html/crl
    $ ln -s /opt/module_build_service/pki/ca.crl /var/www/html/crl/ca.crl
    $ ln -s /opt/module_build_service/pki/ca.crt /var/www/html/crl/ca.crt

Create a directory to house the fedmsg cache::

    $ mkdir -p /etc/pki/fedmsg

Then uncomment the fedmsg signing configuration in
`fedmsg.d/module_build_service.py`.

Historical Names of Module Build Service
----------------------------------------

- Rida
- The Orchestrator
