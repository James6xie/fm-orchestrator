The Module Build Service (MBS) for Modularity
=============================================

The MBS coordinates module builds and is responsible for a number of
tasks:

- Providing an interface for module client-side tooling via which module build
  submission and build state queries are possible.
- Verifying the input data (modulemd, RPM SPEC files and others) is available
  and correct.
- Preparing the build environment in the supported build systems, such as koji.
- Scheduling and building of the module components and tracking the build
  state.
- Emitting bus messages about all state changes so that other infrastructure
  services can pick up the work.

Supported build systems
=======================

Koji
----

Koji is the software that builds RPM packages from source tarballs and
SPEC files. It uses its own Mock to create chroot environments to
perform builds.

MBS comes with its own ``koji.conf`` config file which allows configuring
for your custom Koji instance(s).

Mock
----

Mock is a simple program that will build source RPMs inside a chroot. It
doesn't do anything terribly fancy other than populate a chroot with the
contents specified by a configuration file, then build any input SRPM(s)
in that chroot.

MBS is able to perform local module builds by directing local Mock.

MBS supports threaded Mock builds which utilizes performance and
significantly speeds up local module builds.

Copr
----

Copr is yet another an easy-to-use automatic build system providing a
package repository as its output.

As with Koji, MBS comes with its own ``copr.conf`` config file which allows
altering your default Copr configuration.

_`Client tooling`
=================

``mbs-build``
-------------

This command submits and manages module builds.

The most frequently used subcommand would be 'submit'. After providing
access credentials, a module build is passed to a preconfigured
MBS instanace. When 'scm_url' or 'branch' is not set, it presumes you
are executing this command in a directory with a cloned git repository
containing a module prescript. The same approach is used in the case of
local module submission.

Other subcommands allow local module submission, watching module builds,
canceling them etc. For more info, there's an existing help available.

``mbs-manager``
---------------

This command controls the MBS instance itself.

There are subcommands for running the MBS server, performing database
migrations, generating certificates and submitting local module
builds. For more info, there's an existing help available.

Client-side API
===============

The MBS implements a RESTful interface for module build submission and state
querying. Not all REST methods are supported. See below for details. For client
tooling which utilizes the API, please refer to `Client tooling`_ section.

Module build submission
-----------------------

Module submission is done via posting the modulemd SCM URL.

::

    POST /module-build-service/1/module-builds/

::

    {
        "scmurl": "git://pkgs.fedoraproject.org/modules/foo.git/foo.yaml?#f1d2d2f924e986ac86fdf7b36c94bcdf32beec15
    }

The response, in case of a successful submission, would include the task ID.

::

    HTTP 201 Created

::

    {
        id: 42
    }


When ``YAML_SUBMIT_ALLOWED`` is enabled, it is also possible to submit
raw modulemd yaml file by sending ``multipart/form-data`` request with
input file named as ``yaml``.

Module build state query
------------------------

Once created, the client can query the current build state by requesting the
build task's URL. Querying the BPO service might be preferred, however.

::

    GET /module-build-service/1/module-builds/42

The response, if the task exists, would include various pieces of information
about the referenced build task.

::

    HTTP 200 OK

::

    {
        "id": 42,
        "state": "build",
        "tasks": {
            "rpms": {
                "foo": {
                    "task_id": 6378,
                    "state": 1,
                    "state_reason": None,
                    "nvr": "foo-1.2.3-1...",
                },
                "bar": {
                    "task_id": 6379,
                    "state": 0,
                    "state_reason": None,
                    "nvr": None,
                }

            }
        },
        ...
    }

"id" is the ID of the task. "state" refers to the MBS module build state and
might be one of "init", "wait", "build", "done", "failed" or "ready". "tasks"
is a dictionary of information about the individual component builds including
their IDs in the backend buildsystem, their state, a reason for their state,
and the NVR (if known).

By adding ``?verbose=1`` to the request, additional detailed information
about the module can be obtained.

::

    GET /module-build-service/1/module-builds/42?verbose=1

Listing all module builds
-------------------------

The list of all tracked builds and their states can be obtained by
querying the "module-builds" resource.
There are a number of configurable GET parameters to change how the
module builds are displayed. These parameters are:

- ``verbose`` - Shows the builds with the same amount of detail as querying
  them individually (i.e. ``verbose=True``). This value defaults to False.
- ``page`` - Specifies which page should be displayed (e.g. ``page=3``). This
  value defaults to 1.
- ``per_page`` - Specifies how many items per page should be displayed
  (e.g. ``per_page=20``). This value defaults to 10.

An example of querying the "module-builds" resource without any additional
parameters::

    GET /module-build-service/1/module-builds/

::

    HTTP 200 OK

::

    {
      "items": [
        {
          "id": 1,
          "state": 3
        },
        {
          "id": 2,
          "state": 3
        },
        {
          "id": 3,
          "state": 3
        },
        {
          "id": 4,
          "state": 4
        },
        {
          "id": 5,
          "state": 4
        },
        {
          "id": 6,
          "state": 4
        },
        {
          "id": 7,
          "state": 4
        },
        {
          "id": 8,
          "state": 4
        },
        {
          "id": 9,
          "state": 4
        },
        {
          "id": 10,
          "state": 1
        }
      ],
      "meta": {
        "first": "https://127.0.0.1:5000/module-build-service/1/module-builds/?per_page=10&page=1",
        "last": "https://127.0.0.1:5000/module-build-service/1/module-builds/?per_page=10&page=3",
        "next": "https://127.0.0.1:5000/module-build-service/1/module-builds/?per_page=10&page=2",
        "page": 1,
        "pages": 3,
        "per_page": 10,
        "total": 30
      }
    }


An example of querying the "module-builds" resource with the "verbose",
"per_page", and the "page" parameters::

    GET /module-build-service/1/module-builds/?verbose=true&per_page=3&page=1

::

    HTTP 200 OK

::

    {
      "items": [
        {
          "id": 1,
          "name": "testmodule",
          "owner": "mprahl",
          "state": 3,
          "tasks": {
            "rpms": {
              "bash": {
                "task_id": 90109464,
                "state": 1,
                ...
              },
              "module-build-macros": {
                "task_id": 90109446,
                "state": 1,
                ...
              }
            }
          },
          "time_completed": "2016-08-22T09:44:11Z",
          "time_modified": "2016-08-22T09:44:11Z",
          "time_submitted": "2016-08-22T09:40:07Z"
        },
        {
          "id": 2,
          "name": "testmodule",
          "owner": "ralph",
          "state": 3,
          "tasks": {
            "rpms": {
              "bash": {
                "task_id": 90109465,
                "state": 1,
                ...
              },
              "module-build-macros": {
                "task_id": 90109450,
                "state": 1,
                ...
              }
            }
          },
          "time_completed": "2016-08-22T09:54:04Z",
          "time_modified": "2016-08-22T09:54:04Z",
          "time_submitted": "2016-08-22T09:48:11Z"
        },
        {
          "id": 3,
          "name": "testmodule",
          "owner": "mprahl",
          "state": 3,
          "tasks": {
            "rpms": {
              "bash": {
                "task_id": 90109497,
                "state": 1,
                ...
              },
              "module-build-macros": {
                "task_id": 90109480,
                "state": 1,
                ...
              }
            }
          },
          "time_completed": "2016-08-22T10:05:08Z",
          "time_modified": "2016-08-22T10:05:08Z",
          "time_submitted": "2016-08-22T09:58:04Z"
        }
      ],
      "meta": {
        "first": "https://127.0.0.1:5000/module-build-service/1/module-builds/?per_page=3&page=1",
        "last": "https://127.0.0.1:5000/module-build-service/1/module-builds/?per_page=3&page=10",
        "next": "https://127.0.0.1:5000/module-build-service/1/module-builds/?per_page=3&page=2",
        "page": 1,
        "pages": 10,
        "per_page": 3,
        "total": 30
      }
    }


Filtering module builds
-----------------------

The module-builds can be filtered by a variety of GET parameters. These
paramters are:

- ``name`` - Shows builds of modules with a particular name (e.g.
  ``name=testmodule``)
- ``koji_tag`` - Shows builds tagged with a particular Koji tag (e.g.
  ``koji_tag=module-984ed60dd37b9361``)
- ``owner`` - Shows builds submitted by a particular user (e.g.
  ``owner=mprahl``)
- ``state`` - Shows builds in a particular state (can be the state name or
  the state ID) (e.g. ``state=done``)
- ``submitted_before`` - Shows builds that were submitted before a particular
  Zulu ISO 8601 timestamp (e.g. ``submitted_before=2016-08-23T09:40:07Z``)
- ``submitted_after`` - Shows builds that were submitted after a particular
  Zulu ISO 8601 timestamp (e.g. ``submitted_after=2016-08-22T09:40:07Z``)
- ``modified_before`` - Shows builds that were modified before a particular
  Zulu ISO 8601 timestamp (e.g. ``modified_before=2016-08-23T09:40:07Z``)
- ``modified_after`` - Shows builds that were modified after a particular
  Zulu ISO 8601 timestamp (e.g. ``modified_after=2016-08-22T09:40:07Z``)
- ``completed_before`` - Shows builds that were completed before a particular
  Zulu ISO 8601 timestamp (e.g. ``completed_before=2016-08-22T09:40:07Z``)
- ``completed_after`` - Shows builds that were completed after a particular
  Zulu ISO 8601 timestamp (e.g. ``completed_after=2016-08-23T09:40:07Z``)

An example of querying the "module-builds" resource with the "state",
and the "submitted_before" parameters::

    GET /module-build-service/1/module-builds/?state=done&submitted_before=2016-08-23T08:10:07Z

::

    HTTP 200 OK

::

    {
      "items": [
        {
          "id": 1,
          "state": 3
        },
        {
          "id": 2,
          "state": 3
        },
        {
          "id": 3,
          "state": 3
        }
      ],
      "meta": {
        "first": "https://127.0.0.1:5000/module-build-service/1/module-builds/?per_page=10&page=1",
        "last": "https://127.0.0.1:5000/module-build-service/1/module-builds/?per_page=10&page=1",
        "page": 1,
        "pages": 1,
        "per_page": 3,
        "total": 3
      }

Component build state query
---------------------------

Getting particular component build is very similar to a module build query.

::

    GET /module-build-service/1/component-builds/1

The response, if the build exists, would include various pieces of information
about the referenced component build.

::

    HTTP 200 OK

::

    {
        "format": "rpms", 
        "id": 1, 
        "module_build": 1, 
        "package": "nginx", 
        "state": 1, 
        "state_name": "COMPLETE", 
        "state_reason": null, 
        "task_id": 12312345
    }

"id" is the ID of the component build. "state_name" refers to the MBS component
build state and might be one of "COMPLETE", "FAILED", "CANCELED". "task_id"
is a related task ID in the backend buildsystem, their state and a reason
for their state. "module_build" refers to the module build ID for which this
component was built. "format" is typically "rpms", since we're building it
and "package" is simply the package name.

By adding ``?verbose=1`` to the request, additional detailed information
about the component can be obtained.

::

    GET /module-build-service/1/component-builds/1?verbose=1

Listing component builds
------------------------

An example of querying the "component-builds" resource without any additional
parameters::

    GET /module-build-service/1/component-builds/

::

    HTTP 200 OK

::

    {
      "items": [
        {
          "id": 854,
          "state": 1
        },
        {
          "id": 107,
          "state": 1
        },
        {
          "id": 104,
          "state": 1
        },
        ....
      ],
      "meta": {
        "first": "https://127.0.0.1:5000/module-build-service/1/component-builds/?per_page=10&page=1",
        "last": "https://127.0.0.1:5000/module-build-service/1/component-builds/?per_page=10&page=4237",
        "next": "https://127.0.0.1:5000/module-build-service/1/component-builds/?per_page=10&page=2",
        "page": 1,
        "pages": 4237,
        "per_page": 10,
        "prev": null,
        "total": 42366
      }
    }

HTTP Response Codes
-------------------

Possible response codes are for various requests include:

- HTTP 200 OK - The task exists and the query was successful.
- HTTP 201 Created - The module build task was successfully created.
- HTTP 400 Bad Request - The client's input isn't a valid request.
- HTTP 401 Unauthorized - No 'authorization' header found.
- HTTP 403 Forbidden - The SCM URL is not pointing to a whitelisted SCM server.
- HTTP 404 Not Found - The requested URL has no handler associated with it or
  the requested resource doesn't exist.
- HTTP 409 Conflict - The submitted module's NVR already exists.
- HTTP 422 Unprocessable Entity - The submitted modulemd file is not valid or
  the module components cannot be retrieved
- HTTP 500 Internal Server Error - An unknown error occured.
- HTTP 501 Not Implemented - The requested URL is valid but the handler isn't
  implemented yet.
- HTTP 503 Service Unavailable - The service is down, possibly for maintanance.

_`Module Build States`
----------------------

You can see the list of possible states with::

    from module_build_service.models import BUILD_STATES
    print(BUILD_STATES)

Here's a description of what each of them means:

init
~~~~

This is (obviously) the first state a module build enters.

When a user first submits a module build, it enters this state. We parse the
modulemd file, learn the NVR, and create a record for the module build.

Then, we validate that the components are available, and that we can fetch
them. If this is all good, then we set the build to the 'wait' state. If
anything goes wrong, we jump immediately to the 'failed' state.

wait
~~~~

Here, the scheduler picks up tasks in wait and switches to build immediately.
Eventually, we'll add throttling logic here so we don't submit too many
builds for the build system to handle.

build
~~~~~

The scheduler works on builds in this state. We prepare the buildroot, submit
builds for all the components, and wait for the results to come back.

done
~~~~

Once all components have succeeded, we set the top-level module build to 'done'.

failed
~~~~~~

If any of the component builds fail, then we set the top-level module
build to 'failed' also.

ready
~~~~~

This is a state to be set when a module is ready to be part of a
larger compose. perhaps it is set by an external service that knows
about the Grand Plan.

Bus messages
============

Supported messaging backends:

- fedmsg - Federated Messaging with ZeroMQ
- in_memory - Local/internal messaging only
- amq - Apache ActiveMQ

Message Topic
-------------

The suffix for message topics concerning changes in module state is
``module.state.change``. Currently, it is expected that these messages are sent
from koji or module_build_service_daemon, i.e. the topic is prefixed with
``*.buildsys.`` or ``*.module_build_service.``, respectively.

Message Body
------------

The message body is a dictionary with these fields:

``state``
~~~~~~~~~

This is the current state of the module, corresponding with the states
described above in `Module Build States`_.

``name``, ``version``, ``release``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Name, version and release of the module.

``scmurl``
~~~~~~~~~~

Specifies the exact repository state from which a module is built.

E.g. ``"scmurl": "git://pkgs.stg.fedoraproject.org/modules/testmodule.git?#020ea37251df5019fde9e7899d2f7d7a987dfbf5"``

``topdir``
~~~~~~~~~~

The toplevel directory containing the trees for each architecture of a module.
This field is only present when a module finished building, i.e. with the
states 'done' or 'ready'.

Configuration
=============

MBS configures itself according to the environment where it runs + according to
the following rules (all of them are evaluated from top to bottom):

- DevConfiguration is the initial configuration chosen.
- If configuration file is found within its final installation location,
  ProdConfiguration is assumed.
- If Flask app running within mod_wsgi is detected,
  ProdConfiguration is assumed.
- If environment variables determining configuration file/section are found,
  they are used for configuration. Following environment variables are
  recognized:

    - ``MBS_CONFIG_FILE``: Overrides default configuration file location,
      typically ``/etc/module-build-service/config.py``.
    - ``MBS_CONFIG_SECTION``: Overrides configuration section.

  It is possible to set these values in httpd using ``SetEnv``,
  anywhere in ``/etc/profile.d/`` etc.

- If test-runtime environment is detected,
  TestConfiguration is used, otherwise...
- if ``MODULE_BUILD_SERVICE_DEVELOPER_ENV`` is set to some reasonable
  value, DevConfiguration is forced and ``config.py`` is used directly from the
  MBS's develop instance. For more information see ``docs/CONTRIBUTING.rst``.


Setting Up Kerberos + LDAP Authentication
=========================================

MBS defaults to using OIDC as its authentication mechanism. It additionally
supports Kerberos + LDAP, where Kerberos proves the user's identity and LDAP
is used to determine the user's group membership. To configure this, the following
must be set in ``/etc/module-build-service/config.py``:

- ``AUTH_METHOD`` must be set to ``'kerberos'``.
- ``KERBEROS_HTTP_HOST`` can override the hostname MBS will present itself as when
  performing Kerberos authentication. If this is not set, Python will try to guess the
  hostname of the server.
- ``KERBEROS_KEYTAB`` is the path to the keytab used by MBS. If this is not set,
  the environment variable ``KRB5_KTNAME`` will be used.
- ``LDAP_URI`` is the URI to connect to LDAP (e.g. ``'ldaps://ldap.domain.local:636'``
  or ``'ldap://ldap.domain.local'``).
- ``LDAP_GROUPS_DN`` is the distinguished name of the container or organizational unit where groups
  are located (e.g. ``'ou=groups,dc=domain,dc=local'``). MBS does not search the tree below the
  distinguished name specified here for security reasons because it ensures common names are
  unique.
- ``ALLOWED_GROUPS`` and ``ADMIN_GROUPS`` both need to declare the common name of the LDAP groups,
  not the distinguished name.

Development
===========

For help on setting up a development environment, see ``docs/CONTRIBUTING.rst``.

License
=======

MBS is licensed under MIT license. See LICENSE file for details.

Parts of MBS are licensed under 3-clause BSD license from:
https://github.com/projectatomic/atomic-reactor/blob/master/LICENSE
