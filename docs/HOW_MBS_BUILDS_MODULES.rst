How does MBS build modules?
===========================

This document describes how are modules built internally in MBS. The goal of this document is
to explain code-flow of module builds. It assumes everything goes as expected and does not
mention any error handling or corner cases.


User submits module build request
---------------------------------

There is MBS frontend providing REST API (See `views.py`). User sends POST request with JSON
describing the module to build. There is mainly the URL to git repository (called `scmurl`)
and branch name (called `branch`). The `scmurl` points to git repository containing the
modulemd file defining the module.

This JSON data is handled by `views.SCMHandler`, which validates the JSON and calls
`utils.submit.submit_module_build_from_scm(...)` method. This goes down to
`submit_module_build(...)`.


Module Stream Expansion (MSE)
-----------------------------

The first thing done in `submit_module_build(...)` is Module Stream Expansion (MSE).

The submitted modulemd file might have buildrequires and requires pairs defined in ambigous way.
For example the module can buildrequire `platform:[28, 29]` modules, which means it should
be built against the `f28` and `f29` streams of `platform` module.

The process of resolving these ambigous buildrequires and requires is called Module Stream
Expansion.

Input for this process is the submitted modulemd file with ambigous buildrequires/requires.
Output of this process is list of multiple modulemd files with all the ambigous
buildrequires/requires resolved.

This all happens in `utils.mse.generate_expanded_mmds(...)` method.

At first, this method finds out all the possible buildrequires/requires for the input module.
This is done using `DBResolver` which simply finds out the modules in the MBS database.
In our case, it would list all the `platform:f28` and `platform:f29` modules.

It then uses `MMDResolver` class to find all the possible combinations of buildrequires/requires
for which the input module can be built.

In our case, it would generate two expanded modulemd files (one for each platform stream) which
would be identical to input modulemd file with only following exceptions:

- The buildrequires/requires pairs from input modulemd files will be replaced by the particular
  combination returned by `MMDResolver`
- The `xmd` section of generated modulemd files will contain `buildrequires` list which lists all
  the modules required to build this expanded modulemd file. This is used later by MBS.
- The context is computed and filled for each expanded modulemd file. It is based on the
  expanded buildrequires and requires pairs. See `models.ModuleBuild.contexts_from_mmd(...)`.

Such expanded modulemd files are then added to database as next step in `submit_module_build(...)`
and are handled as separate module builds later in MBS.

The `submit_module_build(...)` then moves the module builds to "init" state and sends message to
fedmsg hub or UMB for each submitted expanded module build


Backend handles module moved to "init" state
--------------------------------------------

When module build is moved to "init" state, backend handles that in
`scheduler.handlers.modules.init(...)` method.

This method calls `utils.submit.record_component_builds` which reads the modulemd file
stored in database by frontend and records all the components (future RPM packages) in the
database.

The components are divided into the **batches** based on their buildorder in the modulemd file.

Once the components which are supposed to be built as part of this module build are recorded,
the module moves to "wait" state and another message it sent to the message bus.


Backend handles module moved to "wait" state
--------------------------------------------

When module build is moved to "wait" state, backend handles that in
`scheduler.handlers.modules.wait(...)` method.

At first, this method uses KojiModuleBuilder to generate Koji tag in which the components will be
build. The Koji tag reflects the buildrequires of module by inheriting their Koji tags. In our
case, the Koji tag would inherit just `platform:f28` or `platform:f29` Koji tag, because that's
the only buildrequired module we have.
The list of modules buildrequired by currently building module is get from `buildrequires` list in
the `xmd` section of expanded modulemd file.

Once the Koji tag is ready, it tries to build `module-build-macros` package. This package contains
special build macros which for example defines the dist-tag for built RPMs, ensures that filtered
packages are not installed into the buildroot and so on.

The module-build-macros is always built in first batch.


Module-build-macros package is built
------------------------------------

Once the module-build-macros package is built, Koji sends message to message hub which is handled
in `scheduler.handlers.components.complete(...)` method.

This method changes that state of component build in MBS database to "complete".

It then checks if there are any other unbuilt components in current batch. Because the
"module-build-macros" is the only component in batch 1, it can continue tagging it
into the Koji tag representing the module, so the module-build-macros can be later
installed during the build of next components and can influence them.


Module-build-macros package is tagged into the Koji tag
-------------------------------------------------------

Once the module-build-macros package is tagged by Koji, the `scheduler.handlers.tags.tagged(...)`
method is called.

This simply waits until all the components in a currently built batch are tagged in a Koji tag.

Because module-build-macros is the only component in batch 1, it can continue by regenerating
the Koji repository based on a tag, so the newly build packages (just module-build-macros
in our case), can be installed from that repository when building next components in a module.


Koji repository is regenerated
------------------------------

Once the Koji repository containing packages from currently built batch is regenerated,
the `scheduler.handlers.repos.done(...)` method is called.

This verifies that all the packages from current batch (just module-build-macros for now)
really appear in generated repository and if so, it starts building next batch by calling
`utils.batches.start_next_batch_build(...)`.


Building next batch
-------------------

The `start_next_batch_build(...)` increases the `ModuleBuild.batch` counter to note that it
is going to build next batch with next component builds.

It then generates the list of unbuilt components in the batch and tries to reuse some from
previous module builds. This can happen for example when the component is built from the
same source as previously, no component builds in previous batches changed and the
buildrequires/requires of current module build are still the same as previously.

For components which cannot be reused, it submits them to Koji.


Build all components in all batches in a module
-----------------------------------------------

The process for every component build is the same as for module-build-macros.

MBS builds it in Koji. Once all the components in current batch are built, MBS tags them into
the Koji tag. Once they are tagged, it regenerates the Koji tag repository and then starts
building next batch.

It all ends up when all batches are done.


Last component is built
-----------------------

Once the last component is built and the repository is regenerated, the
`scheduler.handlers.repos.done(...)` method moves the module build to "done" state.


Importing module build to Koji
------------------------------

The "done" state message is handled in `scheduler.handlers.modules.done(...)` method.

This method imports the module build into the Koji using the `KojiContentGenerator` class.
The module build in Koji points to Koji tag with module components and also contains the
final modulemd files generated for earch architecture the module is built for.
