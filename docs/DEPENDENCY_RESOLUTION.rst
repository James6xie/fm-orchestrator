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
