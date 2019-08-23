Modules gating using Greenwave
==============================

Every successfully built module is moved to the ``done`` state. Modules in this state cannot
be used as a build dependency for other modules. They need to be moved to the ``ready`` state.

By default, MBS moves the module from the ``done`` state to the ``ready`` state automatically,
but MBS can also be configured to gate the ``done`` to ``ready`` state transition using
`Greenwave <https://pagure.io/docs/greenwave/>`_.

When Greenwave integration is configured, the following additional MBS features are enabled:

- When the module is moved to the ``done`` state, Greenwave is queried to find out whether
  the module can be moved to the ``ready`` state instantly.
- If the module cannot be moved to the ``ready`` state yet, MBS keeps the module build in the
  ``done`` state and waits for a message from Greenwave. If this message says that all the
  tests defined by Greenwave policy have passed, then the module build is moved to the ``ready``
  state.
- MBS also queries Greenwave periodically to find out the current gating status for modules
  in the ``done`` state. This is useful in case a message from Greenwave was missed.
