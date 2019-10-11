Koji Resolver
=============

MBS supports multiple methods of determining which modules are available to satisfy the
buildrequires of a submitted module build. Each method is implemented as a derived class
of ``GenericResolver`` in MBS, and can be configured using the ``resolver`` option in the MBS
configuration file.

This document describes ``KojiResolver`` and how it influences module builds in MBS.


Enabling Koji Resolver
======================

Koji Resolver is enabled in the MBS configuration file using the ``RESOLVER = "koji"`` option,
but this configuration is not enough to enable it for submitted module builds. It also needs
to be enabled in the modulemd definition of the buildrequired base module of the submitted module
build.

This is done by adding the ``koji_tag_with_modules`` option to the ``xmd`` section of a base module
definition. For example:

.. code-block:: yaml

    document: modulemd
    version: 1
    data:
        xmd:
            mbs:
                koji_tag_with_modules: rhel-8.1.0-modules-build

This option defines the Koji tag from where the buildrequires for the submitted module
build will be taken. All module builds submitted against this base module stream will then use
Koji Resolver.

In case this option is not defined and Koji Resolver is enabled in the MBS configuration
file, MBS simply falls back to using the default resolver (``DBResolver``).


Koji Tag With Modules
=====================

The ``koji_tag_with_modules`` option mentioned above, defines the Koji tag with the modules
available as buildrequires for a submitted module build that buildrequires this base module stream.

This Koji tag inheritance should reflect the compatibility between different base modules.
For example, if there is a ``platform:f31-server`` base module which should further extend
the ``platform:f31`` module, the Koji tag of ``platform:f31-server`` should inherit the Koji tag of
``platform:f31``.

That way, all the modules built against ``platform:f31`` are available in the buildroot
for modules built against ``platform:f31-server``.


MBS Module Builds With KojiResolver
===================================

When KojiResolver is used for a particular base module, MBS will change the way it determines the
available modules to be used as buildrequires as follows:

- It does not try to find compatible base modules using virtual streams. The compatible
  base modules are defined by using Koji tag inheritance.
- It only uses module builds tagged in the tag defined in ``koji_tag_with_modules`` as possible
  buildrequires, and therefore, also as input to Module Stream Expansion.
- It reuses already built components only from the modules tagged in the tag defined in
  ``koji_tag_with_modules``.
