The module build orchestrator for Modularity
============================================

The orchestrator coordinates module builds and is responsible for a number of
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

Client-side API
===============

The orchestrator implements a RESTful interface for module build submission and
state querying.  Not all REST methods are supported.  See below for details.

Module build submission
-----------------------

Module submission is done via posting the modulemd SCM URL.

::

    POST /rida/module-builds/

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

Module build state query
------------------------

Once created, the client can query the current build state by requesting the
build task's URL.  Querying the BPO service might be preferred, however.

::

    GET /rida/module-builds/42

The response, if the task exists, would include various pieces of information
about the referenced build task.

::

    HTTP 200 OK

::

    {
        "id": 42,
        "state": "build",
        "tasks": {
            "rpms/foo" : "6378/closed",
            "rpms/bar : "6379/open"
        }
    }

"id" is the ID of the task.  "state" refers to the orchestrator module
build state and might be one of "init", "wait", "build", "done", "failed" or
"ready".  "tasks" is a dictionary of component names in the format of
"type/NVR" and related koji or other supported buildsystem tasks and
their states.

Listing all module builds
-------------------------

The list of all tracked builds and their states can be obtained by querying the
"module-builds" resource.

::

    GET /rida/module-builds/

::

    HTTP 200 OK

::

    [
        {
            "id": 41",
            "state": "done"
        },
        {
            "id": 42,
            "state": "build"
        },
        {
            "id": 43,
            "state": "init"
        }
    ]


HTTP Response Codes
-------------------

Possible response codes are for various requests include:

- HTTP 200 OK - The task exists and the query was successful.
- HTTP 201 Created - The module build task was successfully created.
- HTTP 400 Bad Request - The client's input isn't a valid request.
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

    import rida
    print(rida.BUILD_STATES)

Here's a description of what each of them means:

init
~~~~

This is (obviously) the first state a module build enters.

When a user first submits a module build, it enters this state.  We parse the
modulemd file, learn the NVR, and create a record for the module build.

Then, we validate that the components are available, and that we can fetch
them.  If this is all good, then we set the build to the 'wait' state.  If
anything goes wrong, we jump immediately to the 'failed' state.

wait
~~~~

Here, the scheduler picks up tasks in wait and switches to build immediately.
Eventually, we'll add throttling logic here so we don't submit too many builds for the build system to handle.

build
~~~~~

The scheduler works on builds in this state.  We prepare the buildroot, submit
builds for all the components, and wait for the results to come back.

done
~~~~

Once all components have succeeded, we set the top-level module build to 'done'.

failed
~~~~~~

If any of the component builds fail, then we set the top-level module build to 'failed' also.

ready
~~~~~

This is a state to be set when a module is ready to be part of a
larger compose.  perhaps it is set by an external service that knows
about the Grand Plan.

Bus messages
============

Message Topic
-------------

The suffix for message topics concerning changes in module state is
``module.state.change``. Currently, it is expected that these messages are sent
from koji or ridad, i.e. the topic is prefixed with ``*.buildsys.`` or
``*.ridad.``, respectively.

Message Body
------------

The message body (``msg['msg']``) is a dictionary with these fields:

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
