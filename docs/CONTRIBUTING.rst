Running Tests
=============

Since MBS requires Python dependencies that aren't available using PyPi (e.g. libsolv bindings),
there is a Docker image that can be used to run the code analysis and unit tests.

To run the tests, you must first install and start Docker with::

    $ sudo dnf install docker
    $ sudo systemctl start docker

From the main git directory, build the Docker image with::

    $ sudo docker build -t mbs/test -f docker/Dockerfile-tests .

Then run the tests with::

    $ sudo docker run -t --rm -v $PWD:/src:Z mbs/test

Style Guide
===========

Automatically Checked
---------------------

The codebase conforms to the style enforced by ``flake8`` with the following exceptions:

- The maximum line length allowed is 100 characters instead of 80 characters
- The use of lambda functions are allowed (ignoring E731)
- Line breaks should occur before a binary operator (ignoring W503)

These rules are enforced by running ``tox -e flake8`` on pull-requests.

Requires Manual Review
----------------------

In addition to the ``flake8`` rules, **double quotes** are used over single quotes. If the string
contains double quotes in it, then single quotes may be used to avoid escaping.

Also, the format of the docstrings should be in the
`Sphinx style <http://www.sphinx-doc.org/en/master/usage/restructuredtext/domains.html>`_ such as:

::

    Calculate the sum of two numbers.

    :param int a: the first number to add
    :param int b: the second number to add
    :return: the sum of a and b
    :rtype: int
    :raises TypeError: if a or b are not integers


Additionally, the imports should be ordered by standard library, third-party, then local. For example:

::

    import math
    import os

    import flask
    import requests

    import module_build_service.utils
    from module_build_service.errors import ValidationError


Lastly, hanging indentation should be avoided when possible. For example:

::

    # Preferred
    def get_module_build_dependencies(
        self, name=None, stream=None, version=None, context=None, mmd=None, strict=False
    ):
        pass

    # Should be avoided
    def get_module_build_dependencies(self, name=None, stream=None, version=None,
                                      context=None, mmd=None, strict=False):
        pass

Development
===========

In most cases, you don't need to deploy your development instance. Please,
refer to the `Running Tests`_ section first.

The easiest way to setup a development environment is by using ``vagrant``. You can see instructions
about it below.

Vagrant
-------

If you are using VirtualBox, you will need to install the Vagrant plugin
``vagrant-vbguest``. This plugin automatically installs guest additions to
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
``/opt/module_build_service`` inside the guest::

    $ fedmsg-hub

Alternatively, you can restart the Vagrant guest, which inherently
starts/restarts the frontend and the scheduler with::

    $ vagrant reload

Logging
-------

If you're running module_build_service from scm, then the DevConfiguration
from ``conf/config.py`` which contains ``LOG_LEVEL=debug`` should get applied. See
more about it in ``module_build_service/config.py``, ``app.config.from_object()``.

Environment
-----------

The environment variable ``MODULE_BUILD_SERVICE_DEVELOPER_ENV``, which if
set to "1", indicates to the Module Build Service that the development
configuration should be used. Vagrant already runs with this environment variable set.
This overrides all configuration settings and forces usage of DevConfiguration section
in ``conf/config.py`` from MBS's develop instance.

Prior to starting MBS, you can force development mode::

    $ export MODULE_BUILD_SERVICE_DEVELOPER_ENV=1

PEP 8
=====

Following PEP 8 is highly recommended and all patches and future code
changes shall be PEP 8 compliant to keep at least constant or decreasing
number of PEP 8 violations.

Historical Names of Module Build Service
========================================

- Rida
- The Orchestrator
