Change Log
==========

v2.4.2
------
* Fix a bug where the fedmsg messaging plugin wouldn't send the NVR on a KojiTagChange message

v2.4.1
------
* Fix bugs when building modules with SCL components
* Expose the component build's NVR and batch in the REST API

v2.4.0
------
* MBS local builds now use the production MBS API for dependency resolution instead of PDC
* Remove COPR support (this hasn't been working for several months now)
* Make `repo_include_all setting` configurable in xmd

v2.3.2
------
* Typofix related to the v2.3.1 release.

v2.3.1
------
* Support the modulemd buildopts.rpms.whitelist option
* Allow searching for modules by a binary RPM using the MBS API
* Some fixes around local builds

v2.3.0
------

* Get buildrequired modules for Koji tag inheritance using NSVC instead of NSV
* Support querying for modules/components with multiple state filters
* Support querying for builds by an NSVC string
* Fix an MSE issue when a module buildrequires on the same name and stream as itself

v2.2.4
------

* Use /etc instead of %_sysconfdir in module-build-macros to fix builds with flatpak-rpm-macros

v2.2.3
------

* Fix an issue that occurred when the legacy modulemd module wasn't installed

v2.2.2
------

* Fix some local build issues

v2.2.1
------

* Fix exception in the poller when processing old module builds
* Revert the context values in the database to what they were previous to the algorithm change

v2.2.0
------

* Make the published messages smaller
* Show siblings and component_builds in the standard modules API

v2.1.1
------

* Some py3 compat fixes.
* Fallback to the old Koji tag format for the target when the tag name is too long

v2.1.0
------

* Change ModuleBuild.context to a database column which allows filtering
* Generate informative Koji tag names when "name:stream:version" is not too long
* Reuse components only from modules with the same build_context (same buildrequires names and streams)
* Generate 'context' from hash based on buildrequires/requires stream instead of commit hashes
* Allow defining list of packages which are blocked in the "-build" tag until they are built in a module
* Keep the 'module_name:[]' in requires unexpanded in the recorded modulemd

v2.0.2
------

* Return a friendly error when a module build's dependencies can't be met
* Remove unused dependencies

v2.0.1
------

* Fix Koji Content Generator imports
* Fix a module stream expansion issue that occurs when a module requires a module that isn't also a
  buildrequire

v2.0.0
------

* Add module stream expansion support
* Remove deprecated mbs-build tool (fedpkg/rhpkg should be used instead)
* Add the `mbs-manager import_module` command
* Add a database resolver for resolving dependencies for increased performance
* Support modulemd v2
* Fix error that occurs when a batch hasn't started but a repo regen message is received
* Improve Python 3 compatibility
* Improve unit testing performance

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
