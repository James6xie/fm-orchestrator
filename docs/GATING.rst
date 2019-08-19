Modules gating using Greenwave
==============================

Every successfully built module is moved to ``done`` state. Modules in this state cannot
be used as a build-dependency for other modules. They need to be moved to ``ready`` state.

By default, MBS moves the module from ``done`` state to ``ready`` state automatically,
but MBS can also be configured to gate move from ``done`` to ``ready`` state according
to Greenwave service.

When Greenwave integration is configured, then following additional MBS features are enabled:

- When the module is moved to ``done`` state, Greenwave is queried to find out whether to module
  can be moved to ``ready`` state instantly.
- If the module cannot be moved to ``ready`` state yet, MBS keeps the module build in the
  ``done`` state and waits for a message from Greenwave. If this message says that all the
  tests defined by Greenwave policy have passed, then the module build is moved to ``ready``
  state.
- MBS also queries Greenwave periodically to find out the current gating status for modules
  in the ``done`` state. This is useful in case when message from Greenwave has been lost.
