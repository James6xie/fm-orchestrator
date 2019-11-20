==============================================
Integration tests for the Module Build Service
==============================================

This directory stores the integration tests for MBS.

Configuration
=============

The tests should be configured by a ``test.env.yaml`` file placed in the
top-level directory of this repository. This can be changed to a different
path by setting ``MBS_TEST_CONFIG``.

Usually each test will trigger a new module build, and potentially wait until
it completes before doing the checks. In order to avoid waiting for this
during test development, an existing module build can be reused by specifying
a ``build_id`` for the test case.

See `tests/integration/example.test.env.yaml`_ for a complete list of
configuration options and examples.

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

``MBS_TEST_WORKERS`` can be used to run the tests in parallel. For example to
have 4 tests running in parallel one could call::

    MBS_TEST_WORKERS=4 tox -e integration

.. _tests/integration/example.test.env.yaml: example.test.env.yaml
