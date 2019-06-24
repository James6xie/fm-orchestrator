Rebuild Strategies
==================

To view the available/allowed rebuild strategies on your MBS instance, query the rebuild-strategies
API.

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


As described in the API, the following rebuild strategies are supported in MBS:

- ``all`` - all components will be rebuilt. This means that even if the components have not changed
  since the previous build of the module, all components will be rebuilt and not reused.
- ``changed-and-after`` - all components that have changed and those in subsequent batches will be
  rebuilt. Take for example a module with two batches, and each batch has two components. If one of
  the two components in the first batch is changed, the other component in the batch will be reused
  while all other components in the module will be rebuilt. By default, MBS only allows this
  rebuild strategy.
- ``only-changed`` - all changed components will be rebuilt. This means that all components,
  regardless of what happened in previous batches, will be reused if they haven't been changed.
  This strategy is a compromise between ``all`` and ``changed-and-after``.

To configure the rebuild strategies in MBS, you may configure the following options:

- ``rebuild_strategy`` - a string of the rebuild strategy to use by default. This defaults to
  ``changed-and-after``.
- ``rebuild_strategy_allow_override`` - a boolean that determines if a user is allowed to specify
  the rebuild strategy they want to use when submitting a module build. This defaults to ``False``.
- ``rebuild_strategies_allowed`` - a list of rebuild strategies that are allowed to be used. This
  only takes effect if ``rebuild_strategy_allow_override`` is set to ``True``. This defaults to
  allowing all rebuild strategies that MBS supports.
