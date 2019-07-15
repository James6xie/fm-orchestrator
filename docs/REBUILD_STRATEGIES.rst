Rebuild Strategies
==================

MBS has the concept of rebuild strategies, which influence which components can be reused from a
previous module build. This only affects MBS deployments that use Koji as the builder.

Support Rebuild Strategies
==========================

To view the available and allowed rebuild strategies on an MBS instance, query the
rebuild-strategies API endpoint.

::

    GET /module-build-service/1/rebuild-strategies/

::

    HTTP 200 OK

::

    {
      "items": [
        {
          "allowed": false,
          "default": false,
          "description": "All components will be rebuilt",
          "name": "all"
        },
        {
          "allowed": true,
          "default": true,
          "description": "All components that have changed and those in subsequent batches will be rebuilt",
          "name": "changed-and-after"
        },
        {
          "allowed": false,
          "default": false,
          "description": "All changed components will be rebuilt",
          "name": "only-changed"
        }
      ]
    }


System Configuration
====================

To configure the rebuild strategies in MBS, you may configure the following options:

- ``rebuild_strategy`` - a string of the rebuild strategy to use by default. This defaults to
  ``changed-and-after``.
- ``rebuild_strategy_allow_override`` - a boolean that determines if a user is allowed to specify
  the rebuild strategy they want to use when submitting a module build. This defaults to ``False``.
- ``rebuild_strategies_allowed`` - a list of rebuild strategies that are allowed to be used. This
  only takes effect if ``rebuild_strategy_allow_override`` is set to ``True``. This defaults to
  allowing all rebuild strategies that MBS supports.


How MBS Finds a Compatible Module
=================================

MBS finds a compatible module to reuse components from by searching its database for the last built
module with the following requirements:

- The module name is the same as the module being built
- The module stream is the same as the module being built
- The module is in the ``ready`` state (this inherently ignores scratch builds)
- The expanded buildrequires section (after Module Stream Expansion) has the same name:stream
  entries as the module being built
- The module must have been built from a modulemd stored in source control (most deployments only
  allow this)

Additionally, if the rebuild strategy for the module being built is ``changed-and-after``, then the
module to reuse components from will have a rebuild strategy of ``changed-and-after`` or ``all``.

If the user wants to specify the compatible module, they can use the ``reuse_components_from``
parameter.


How the Rebuild Strategies Work
===============================

all
---

No components will be reused. This is used to completely rebuild a module.


changed-and-after
-----------------

All components that have changed and those in subsequent batches will be rebuilt. This is a
conservative middle ground between ``all`` and ``only-changed``.

The following characteristics of the compatible module must be true for a component to be reused:

- The ``buildopts.rpms.macros`` field of the module being built must match the compatible module
- All the components in the module being built must have also been built in the compatible module
- All the arches of the components in the module being built must match the components in the
  compatible module

The following characteristics of the component must be true for it to be reused:

- The ref has to match the one being built
- The batch has to match the one being built
- The previous batches of the module build must have the same exact components and component refs


only-changed
------------

All changed components will be rebuilt. This means that all components, regardless of what happened
in previous batches, will be reused if they haven't changed.

The following characteristics of the compatible module must be true for a component to be reused
(this will be changed after #1298):

- All the components in the module being built must have also been built in the compatible module
- All the arches of the components in the module being built must match the components in the
  compatible module

The following characteristics of the component must be true for it to be reused:

- The ref has to match the one being built
