Change Log
==========

v1.6.1
------

* Fix an error that occurs when a module build is resumed and module-build-macros was cancelled

v1.6.0
------

* Use available Koji repos during local builds instead of building them locally
* Add an incrementing prefix to module components' releases
* Add a "context" field on component and module releases in Koji for uniqueness for when Module Stream Expansion is implemented
* Remove urlgrabber as a dependency
* Set an explicit log level on our per-build file handler
* Set the timeout on git operations to 60 seconds to help alleviate client tooling timeouts
* Improve the efficiency of the stale module builds poller
* Fix situations where module-build-macros builds in Koji but fails in MBS and the build is resumed
