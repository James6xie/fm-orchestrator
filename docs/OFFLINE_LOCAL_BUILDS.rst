MBS Offline local builds
========================

MBS can build modules locally in offline mode. This means that MBS will only use repositories
which are enabled locally in `/etc/yum.repos.d` as dependencies, and will not query any external
infrastructure (except the RPM repositories identified in /etc/yum.repos.d) to build a module.

This document describes how to build modules in this way.


Definition of module to build
=============================

The module to build offline is defined by a regular modulemd yaml file. This file does not have
to live in a git repository. The following are things to keep in mind in regards to offline local
builds:

- The buildrequired platform stream must be the one provided by the local system. You can see
  the platform stream your system provides by checking the PLATFORM_ID in the ``/etc/os-release``
  file.
- To build components (RPMs) defined by a spec file and sources from some local path, you need
  to define `repository: file:///home/user/path/to/component` for each component. For more
  information, refer to the modulemd specification. If you do not specify the ``repository``,
  MBS will get this component from the configured remote dist-git as it would normally do.


Definition of local components (RPMs) to build
==============================================

To build a component (RPM) defined locally in some directory, you need to specify the path to it
in the `repository` section of the component in the modulemd definition of the module as
described earlier in this document.

Important facts about this directory are:

- The directory with the component must be a git repository.
- All changes you want to include in the local module build must be committed.
- The directory must contain all the sources referred to by the spec file.

In case you want to test some change in some Fedora package by building it in a module locally,
you can get such directory by these commands::

    $ fedpkg clone some-rpm-package
    $ cd some-rpm-package
    $ fedpkg prep
    $ vi some-fedora-package.spec
    ... do some local changes ...
    $ git commit -a -m 'testing offline local builds'


Building module locally in offline mode
=======================================

Note: In the future, it might be possible that fedpkg provides a better user-experience than
the way described here. This is using the mbs-manager directly, which is not intended to be
used by the end-user, but it is so far the only way to perform offline local builds.

A module can be built locally using following command::

    $ mbs-manager build_module_locally --file=/home/user/module.yaml --offline -r /etc/yum.repos.d/fedora.repo -r /etc/yum.repos.d/fedora-updates.repo

Here is a description of the arguments that were used:

- ``--file`` - Defines the full-path to the modulemd file that defines the module to build.
- ``--offline`` - Enables the offline local module builds mode.
- ``-r`` - The full path to the `.repo` files with repositories defining the platform module.
  These repositories contain the non-modular RPMs which form the basic buildroot for the module.

When ``mbs-manager build_module_locally`` is executed, it will do the following:

- It examines all the repositories enabled locally to find out all the available modules defined
  in these repositories.
- Using the list of available modules, it resolves the dependencies between them and chooses
  the combination which will be built locally.
- In the case that Module Stream Expansion generates multiple contexts (possible builds),
  the user needs to choose the one they want to build using the `-s` or `--set-stream` argument.
- The Mock configuration is generated from ``/etc/module-build-service/mock.cfg`` template
  and ``/etc/module-build-service/yum.conf`` template.
- The local repositories with modules and the repositories defined by ``-r`` argument are added
  to the buildroot using the ``yum.conf`` template.
- Mock is used to build each component.
- The built modules are stored in ``~/modulebuild/builds``.
