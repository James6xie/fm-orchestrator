Virtual (Pseudo) Modules
========================

A virtual module is any module which is not built by MBS directly, but instead its metadata is
imported to the MBS database. A virtual module is defined using a modulemd file with extra data
in the ``xmd`` section. These are usually base modules such as ``platform``.


Example
=======

Here is an example of the Fedora 31 platform module, which is also virtual module::

    document: modulemd
    version: 1
    data:
      description: Fedora 31 traditional base
      license:
        module: [MIT]
      name: platform
      profiles:
        buildroot:
        rpms: [bash, bzip2, coreutils, cpio, diffutils, fedora-release, findutils, gawk,
               glibc-minimal-langpack, grep, gzip, info, make, patch, redhat-rpm-config,
               rpm-build, sed, shadow-utils, tar, unzip, util-linux, which, xz]
        srpm-buildroot:
        rpms: [bash, fedora-release, fedpkg-minimal, glibc-minimal-langpack, gnupg2,
               redhat-rpm-config, rpm-build, shadow-utils]
      stream: f31
      summary: Fedora 31 traditional base
      context: 00000000
      version: 1
      xmd:
        mbs:
        buildrequires: {}
        commit: f31
        requires: {}
        koji_tag: module-f31-build
        mse: TRUE


Virtual Module Fields
=====================

Required standard fields:

- ``name`` - the module's name.
- ``stream`` - the module's stream.
- ``version`` - the module's version.
- ``context`` - the module's context. This can be simply ``00000000``, which is the default value
  in MBS.

Optional standard fields:

- ``profiles.buildroot`` - defines the list of packages installed during the RPM build in Koji.
- ``profiles.srpm-buildroot`` - defines the list of packages installed during the SRPM build.
  ``module-build-macros`` must be present if this is a base module like ``platform``.

Custom fields in xmd:

- ``buildrequires`` - the buildrequires as resolved by MBS. It should always be an empty dictionary
  for base modules.
- ``requires`` - the requires as resolved by MBS. It should always be an empty dictionary
  for base modules.
- ``commit`` - this should be ``virtual`` or some other identifier that is meaningful since a commit
  is not applicable when a module is directly imported.
- ``mse`` - this is an internal identifier used by MBS to know if this is a legacy module build
  prior to module stream expansion. This should always be ``TRUE``.
- ``koji_tag`` - this defines the Koji tag with the RPMs that are part of this module. For base
  modules this will likely be a tag representing a buildroot.
- ``virtual_streams`` - the list of streams which groups multiple modules together. For more
  information on this field, see the ``Virtual Streams`` section below.
- ``disttag_marking`` - if this module is a base module, then MBS will use the stream of the base
  module in the disttag of the RPMS being built. If the stream is not the appropriate value, then
  this can be overridden with a custom value using this property. This value can't contain a dash,
  since that is an invalid character in the disttag.


Virtual Streams
===============

The ``virtual_streams`` field defines the list of streams which groups multiple modules together.

For example, all the 8.y.z versions of the ``platform:el8.y.z`` module defines
``virtual_streams: [el8]``. That tells MBS that if some built module has a runtime dependency on
``platform:el8``, MBS can choose dependencies built against any platform modules which provides
the ``el8`` virtual stream to fulfill this dependency.

This allows building a module which buildrequires ``platform:el8.1.0`` against modules which have
been built against ``platform:el8.0.0`` as long as they both have a runtime requirement of
``platform:el8``.
