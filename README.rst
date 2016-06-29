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
- HTTP 422 Unprocessable Entity - The submitted modulemd file is not valid or
  the module components cannot be retrieved
- HTTP 500 Internal Server Error - An unknown error occured.
- HTTP 501 Not Implemented - The requested URL is valid but the handler isn't
  implemented yet.
- HTTP 503 Service Unavailable - The service is down, possibly for maintanance.
