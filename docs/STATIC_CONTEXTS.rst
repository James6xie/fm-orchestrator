Static contexts
===============

- the user can specifically set their own context and dependencies when required through
  ``mbs_options``. ``mbs_options`` is a dict which is part of the ``xmd`` property and
  is used to configure additional build options for MBS. To make static contexts work,
  you need to define ``contexts`` dict inside ``mbs_options`` property.
- The context definition needs to be defined in the initial modulemd yaml file. ``contexts``
  build property overrides any dependencies set through the ``dependencies`` property.
- `static contexts` and `stream expansion` are mutually exclusive i. e. the streams defined in
  ``buildrequires`` and ``requires`` of `static context` will not be expanded and need
  to be precisely defined by the user. (You can not use `stream expansion` notation as ``[]``
  or ``-f28`` as this will result in an error)
- `static contexts` only override ``context`` of a module stream i. e. the one which
  is the part of the module streams NSVC. ``build context`` is still calculated and preserved
  in the resulting build in ``mbs`` property in ``xmd`` so the reuse of builds with the
  same ``build contexts`` takes place.
- as per design of the modulemdlib the only types which can be put inside of the ``xmd``
  property are ``dict`` and ``string``.


**Example**:

::

    .
    .
    .
    xmd:
        mbs_options:
            contexts:
                context1:
                    buildrequires:
                        module1: stream1
                        .
                        .
                        .
                        moduleN: streamN
                    requires:
                        moduleN: stream1
                        .
                        .
                        .
                        moduleN: streamN
                .
                .
                .
                contextN:
                    .
                    .
                    .

