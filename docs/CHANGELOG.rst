Change Log
==========

v1.7.0
------

* Use external repos tied to the Koji tags on local builds
* Make the MBS resolver interchangeable
* Make component reuse faster
* Fix a bug that caused module builds with no buildrequires to fail
* Make the poller not resume paused module builds if there was recent activity on the build
* A module's "time_modified" attribute is now updated more often to reflect changes in the build
* Fix getting the module name when a YAML file is submitted directly instead of using SCM
* Remove the Koji proxyuser functionality
* Set the owner on the overall module build in Koji
* Fix a bug that could cause a module build to fail with multiple buildrequires

v1.6.3
------

* Fix a bug that caused a module build to fail when it was cancelled during the module-build-macros phase and then resumed
* Reset the "state_reason" field on all components after a module build is resumed

v1.6.2
------

* Cancel new repo tasks on module build failures in Koji

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
