==============================================
Integration tests for the Module Build Service
==============================================

This directory stores the integration tests for MBS.

Configuration
=============

The tests should be configured by a ``test.env.yaml`` file placed in the
top-level directory of this repository. This can be changed to a different
path by setting ``MBS_TEST_CONFIG``.

See `tests/integration/example.test.env.yaml`_ for the list of configuration
options and examples.

Running the tests
=================

Tests can be triggered from the top-level directory of this repository with::

    tox -e integration

Note, that the ``integration`` environment is not part of the default ``tox``
envlist.

``REQUESTS_CA_BUNDLE`` is passed in ``tox.ini`` for the ``integration``
environment in order to enable running the tests against MBS instances which
have self-signed certificates. Example usage::

    REQUESTS_CA_BUNDLE=/etc/pki/tls/certs/ca-bundle.crt tox -e integration

.. _tests/integration/example.test.env.yaml: example.test.env.yaml
