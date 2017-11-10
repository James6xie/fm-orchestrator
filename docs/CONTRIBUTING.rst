Running Tests
=============

The proper way how to run unit tests is using `tox
<http://tox.readthedocs.io/>`_. See `tox.ini` configuration file in the
topmost directory of the project's repository.

For most cases, you need to work against tox's `py27` environment. This
will just invoke the `pytest` command. For the full set of tests, omit the `-e
py27` argument. This will invoke code analysis, security analysis, and
code coverage checks. This will also run any additional environments
that will be added to the `tox.ini` file in the future.


Examples
--------

Purge environment (this will remove all untracked files/dirs and
uncommited changes!) and run tests::

    $ git clean -fdxe '/.vagrant'
    $ tox -e py27

Just recreate tox's `py27` environment and run the tests::

    $ tox -e py27 -r

Just rerun tests in the existing `py27` enviromnent::

    $ tox -e py27

Pass additional arg(s) to `pytest`, e.g. `-x` to exit on first
error/failed test::

    $ tox -e py27 -- -x

Run only tests in the given file or directory::

    $ tox -e py27 -- path/to/test_file.py/or/test_dir

For more `tox` or `pytest` options, see the corresponding help/man pages.

*Note: Consider using detox which makes efficient use of multiple CPUs
by running all possible activities in parallel. It has the same options
and configuration that tox has.*

Development
===========

In most cases, you don't need to deploy your development instance. Please,
refer to the `Running Tests` section first.

We have two mechanisms for quickly setting up a development environment,
`docker-compose` and `vagrant`.

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

If you are using libvirt, then folder syncing will be done using SSHFS. To
install this on Fedora, use:

    $ dnf install vagrant-sshfs

If you are using libvirt but not using Fedora, you can install the plugin
directly in Vagrant using:

    $ vagrant plugin install vagrant-sshfs

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

You can submit a local test build with the `contrib/mbs-build` script,
which should submit an HTTP POST to the frontend, requesting a build::

    $ ./contrib/mbs-build -s [server] submit [scm_url] [branch]

Here, `server` should specify the `hostname[:port]` port of the MBS instance
you want to submit to. For local development, try `https://127.0.0.1:5000`.

The `scmurl` should be a url to a dist-git repo of the module in question and
the `branch` should be the stream that you want to build. Note that
authentication will be required for submitting a module build. Follow the
on-screen instructions to authenticate.

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

PEP 8
=====

Following PEP 8 is highly recommended and all patches and future code
changes shall be PEP 8 compliant to keep at least constant or decreasing
number of PEP 8 violations.

Historical Names of Module Build Service
========================================

- Rida
- The Orchestrator
