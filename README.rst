The module build orchestrator for Modularity
============================================

The orchestrator coordinates module builds and is responsible for a number of
tasks:

- Providing an interface for module client-side tooling via which module build
  submission and build state queries are possible.
- Verifying the input data (modulemd, RPM SPEC files and others) is available
  and correct.
- Preparing the build environment in the supported build systems, such as koji.
- Scheduling and building of the module components and tracking the build
  state.
- Emitting bus messages about all state changes so that other infrastructure
  services can pick up the work.

Client-side API
---------------

TBD
