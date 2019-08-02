How Dependency Resolution Works in MBS
======================================

#. Evaluate any buildrequire or require overrides submitted manually by the user.

   #. If there is none, the MBS configuration of ``BR_STREAM_OVERRIDE_MODULE`` and
      ``BR_STREAM_OVERRIDE_REGEXES`` are used to parse the branch name, to see if there are any
      buildrequires that should be overridden.

#. Perform module stream expansion.

   #. If a buildrequire is an empty list, then MBS gets all the latest versions of every available
      stream in all contexts.

   #. If a buildrequire contains only streams with ``-`` prefix, the list of streams are treated as
      a blacklist.

      #. For example, if the buildrequire is ``platform: ["-f29"]``, then the module is built for
         all the streams of ``platform`` except the ``f29`` one.

#. Get all the compatible latest buildrequires and recursively the requires of the buildrequires.

   #. Compatibility is determined by finding the compatible ``platforms`` that the module is
      buildrequiring. For example, if you buildrequire ``platform: el8.1.0``, and you buildrequire
      module ``foo`` that was built against ``platform: el8.0.0``, then that module ``foo`` is
      compatible as a buildrequire. The reason is that all modules that have been built with a lower
      ``platform`` of the same major version, are considered compatible. These ``platform`` modules,
      must also all provide the same virtual stream. In the case of RHEL, that is a virtual stream
      of ``el8``.

#. If there are multiple sets of dependencies in the ``dependencies`` list, then these are treated
   like all the possible valid combinations, and MBS will build the input module for each
   combination if the dependency resolution succeeds for that combination.

#. Resolve all the possible combinations of buildrequires.

   #. For each resolved buildrequire combination, a modulemd file is generated based on the original
      modulemd, but with the buildrequires/requires changed based on the resolved combinations.

      #. If the buildrequire and require streams are the same on the original modulemd for a
         particular module, then set the required stream on that module to the same as the
         buildrequired stream. For examples, see the table below.

      #. In the event that you buildrequire two streams of two different modules, four module builds
         are generated.

   #. MBS records the resulting buildrequires (and the recursive requires of the buildrequires) in
      the ``xmd`` section of the modulemd.

   #. MBS records the context in the modulemd file since the buildrequires have been determined.

#. Each generated modulemd file is submitted as a module build.


Examples of buildrequire and require changes from resolved combinations
-----------------------------------------------------------------------

+--------------------------+-------------------------+----------------------------+-----------------------+
| Buildrequires            | Requires                | Resulting Build #1         | Resulting Build #2    |
+==========================+=========================+============================+=======================+
| .. code:: yaml           | .. code:: yaml          | .. code:: yaml             | .. code:: yaml        |
|                          |                         |                            |                       |
|    platform: [f29, f30]  |    platform: [f29, f30] |     buildrequires:         |     buildrequires:    |
|                          |                         |     - platform: [f29]      |     - platform: [f30] |
|                          |                         |     requires:              |     requires:         |
|                          |                         |     - platform: [f29]      |     - platform: [f30] |
+--------------------------+-------------------------+----------------------------+-----------------------+
| .. code:: yaml           | .. code:: yaml          | .. code:: yaml             | .. code:: yaml        |
|                          |                         |                            |                       |
|    platform: [f29, f30]  |    platform: [f30]      |     buildrequires:         |     buildrequires:    |
|                          |                         |     - platform: [f29]      |     - platform: [f30] |
|                          |                         |     requires:              |     requires:         |
|                          |                         |     - platform: [f30]      |     - platform: [f30] |
+--------------------------+-------------------------+----------------------------+-----------------------+
| .. code:: yaml           | .. code:: yaml          | .. code:: yaml             |                       |
|                          |                         |                            |                       |
|    platform: [f30]       |    platform: [f29, f30] |     buildrequires:         |                       |
|                          |                         |     - platform: [f30]      |                       |
|                          |                         |     requires:              |                       |
|                          |                         |     - platform: [f29, f30] |                       |
+--------------------------+-------------------------+----------------------------+-----------------------+
| .. code:: yaml           | .. code:: yaml          | .. code:: yaml             |                       |
|                          |                         |                            |                       |
|    platform: [f29]       |    platform: [f29]      |     buildrequires:         |                       |
|                          |                         |     - platform: [f29]      |                       |
|                          |                         |     requires:              |                       |
|                          |                         |     - platform: [f29]      |                       |
+--------------------------+-------------------------+----------------------------+-----------------------+


How libsolv Works in MBS
========================

Libsolv Terms
-------------

- **Pool** - the main object that represents the libsolv context that all "solvables" get added to
  it.
- **Dep** - an object used for dependency resolution metadata on a string. For example, a ``Dep``
  object might be "platform:el8" (module name and stream), or it might just be a version of a
  module, such as "80000". With these ``Dep`` objects, we can use operators, such as ``REL_EQ``,
  ``REL_OR``, and ``REL_GT`` to define the relation between ``Dep`` objects. For example, the
  "platform:el8" ``Dep`` object would have a ``REL_EQ`` relationship with the "80000" ``Dep``
  object. After creating this relationship, a new ``Dep`` object is returned, with that
  relationship. That ``Dep`` object can then be used in the ``add_deparray`` method, which provides
  a relationship from this ``Dep`` object to a solvable.
- **Solvable** - an installable artifact with properties such as name, version, release, and arch
  that is created in a repo in the pool. Usually, a solvable represents an RPM, but in the case of
  MBS, it represents a module.

  - **Requires** - the ``Dep`` objects that this solvable requires to be available in the repo when
    the solvable is installed.
  - **Provides** - the ``Dep`` objects that this solvable provides. For example,
    "platform:el8:0:c1" (NSVC), would also provide "platform:el8" and "platform:el8 = 0"
    (``REL_EQ`` relationship), this way a solvable can require ``platform:el8`` and not the whole
    NSVC.
  - **Conflicts** - the ``Dep`` objects that represent a solvable that cannot be installed when this
    solvable is installed. For example, two modules of the same name but different stream, cannot be
    installed at the same time, so a "foo:bar1" conflicts with "foo:bar2" and vice-versa.
- **Repo** - a collection of solvables.
- **Job** - what to do with the solvables in the pool. In MBS, this involves stating the solvable we
  want to install (the module being built), and then the solvables that are preferred in the
  solution, which override the default behavior of libsolv. For example, if the "platform:f28" and
  "platform:f29" solvables are both in the pool (due to Module Stream Expansion), MBS will create
  two sets of jobs, the first which favors "platform:f28", and the second which favors
  "platform:f29". This way, if possible, the dependencies are determined for both platforms.
- **Solver** - executes the jobs, and finds the best solution for the given jobs based on the
  solvables in the pool.
- **Transaction** - this describes the solution from the solver execution. In MBS, this is always
  about installing the solvable that represents the module being built.


How It's Used
-------------

There are two repos initialized in the constructor the ``MMDResolver`` class: ``build`` and
``available``. The ``build`` repo contains solvable objects that are created to represent the input
module to resolve. The ``available`` repo contains the solvable objects of the possible build
dependencies of the input module.

There are two main methods: ``add_modules`` and ``solve``.

add_modules
~~~~~~~~~~~

#. Gets the NSVC of the input module.

#. If the context is set, then it’s treated as a dependency.

   #. A solvable object is created in the ``available`` repo with the name, version, and
      architecture (hard-coded to "x86_64" since libsolv requires an architecture, but MBS is
      architecture agnostic for dependency resolution).

   #. Fill in the ``Provides`` for the module by creating a ``Dep`` object.

      #. If it’s not a base module, it provides:

         #. ``module(foo)``
         #. ``module(foo:stream) = 2019``

            #. The version is just used to find the latest version by libsolv.

      #. If it's a base module, it provides:

         #. ``module(platform)``

         #. ``module(platform:el8.0.0) = 3``

            #. This shouldn't be defined if a stream version is set (see #1334).

         #. ``module(platform:el8.0.0) = 80000``

            #. ``80000`` is the "stream version" and not the version of the module.

         #. For each virtual stream if there is a "stream version":

            #. ``module(platform:virtual_stream) = stream_version``

   #. Fills in the ``Requires``.

      #. ``_deps2reqs`` is called, which translates the elements of the dependencies array in the
         modulemd to a libsolv ``Dep`` object. So for a simple example, with the input
         ``deps = [{'gtk': ['1'], 'foo': ['1']}]``, the resulting ``solv.Dep`` expression will be
         ``((module(gtk) with module(gtk:1)) and (module(foo) with module(foo:1)))``.

   #. Fills in the ``Conflicts``.

      #. This is so that modules of the same stream cannot both be used. For example,
         ``module(bar:1)`` will conflict with ``module(bar)``, meaning any other module that also
         provides ``module(bar)``.

#. If the context is not set, it’s treated as the input module.

   #. For each buildrequires/requires pair, a solvable object is created in the ``build`` repo with
      the name, version, and architecture (always ``src``).

   #. The context of the solvable is the index of the buildrequires/requires pair. This is later
      used by the MSE code to distinguish the buildrequires/requires pair, and then which to keep in
      the final modulemd and which to remove.

   #. The requires are filled in by ``_deps2reqs``, as described above.


solve method
~~~~~~~~~~~~

#. The input modulemd is of the input module.

#. For each solvable in the ``build`` repo:

   #. Create a libsolv job to "install" the module.

   #. Iterate over all possible combinations of streams without trying to parallel install any
      module. As part of this iteration, this is done by telling libsolv to favor that combination.
      If what libsolv resolves is the same combination that was favored, we know it’s a valid
      combination.
