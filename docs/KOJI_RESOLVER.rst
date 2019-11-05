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

Defining Layered Products Using KojiResolver
============================================

Sometimes it is needed to define a "layered product" on top of an existing base module.
A layered product is a special module that extends a base module. The goal of a layered product is
to allow building modules on top of an existing base module, but to not tag such module builds back
to the original base module's Koji tag. The module builds built for a layered product are therefore,
separated from the base module.

Defining a layered product using KojiResolver is simple. One just needs to create a new Koji
tag for the layered product which inherits the base module's Koji tag. There also needs to be
a new base module defined using the virtual modules MBS feature. This virtual module needs
to point to this newly created layered product's Koji tag. This virtual module should not
buildrequire a base module on the modulemd file level. This dependency is expressed using
Koji tag inheritance.
