# Copyright (c) 2016  Red Hat, Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# Written by Ralph Bean <rbean@redhat.com>
#            Matt Prahl <mprahl@redhat.com>

""" Utility functions for module_build_service. """
import re
import copy
import functools
import time
import shutil
import tempfile
import os
import kobo.rpmlib
import inspect
import hashlib
from functools import wraps

import modulemd
import yaml

from flask import request, url_for, Response
from datetime import datetime

from module_build_service import log, models
from module_build_service.errors import (ValidationError, UnprocessableEntity,
                                         ProgrammingError)
from module_build_service import conf, db
from module_build_service.errors import (Forbidden, Conflict)
import module_build_service.messaging
from multiprocessing.dummy import Pool as ThreadPool
import module_build_service.pdc
from module_build_service.pdc import resolve_requires

import concurrent.futures


def retry(timeout=conf.net_timeout, interval=conf.net_retry_interval, wait_on=Exception):
    """ A decorator that allows to retry a section of code...
    ...until success or timeout.
    """
    def wrapper(function):
        @functools.wraps(function)
        def inner(*args, **kwargs):
            start = time.time()
            while True:
                if (time.time() - start) >= timeout:
                    raise  # This re-raises the last exception.
                try:
                    return function(*args, **kwargs)
                except wait_on as e:
                    log.warn("Exception %r raised from %r.  Retry in %rs" % (
                        e, function, interval))
                    time.sleep(interval)
        return inner
    return wrapper


def at_concurrent_component_threshold(config, session):
    """
    Determines if the number of concurrent component builds has reached
    the configured threshold
    :param config: Module Build Service configuration object
    :param session: SQLAlchemy database session
    :return: boolean representing if there are too many concurrent builds at
    this time
    """

    # We must not check it for "mock" backend.
    # It would lead to multiple calls of continue_batch_build method and
    # creation of multiple worker threads there. Mock backend uses thread-id
    # to create and identify mock buildroot and for mock backend, we must
    # build whole module in this single continue_batch_build call to keep
    # the number of created buildroots low. The concurrent build limit
    # for mock backend is secured by setting max_workers in
    # ThreadPoolExecutor to num_concurrent_builds.
    if conf.system == "mock":
        return False

    import koji  # Placed here to avoid py2/py3 conflicts...

    if config.num_concurrent_builds and config.num_concurrent_builds <= \
        session.query(models.ComponentBuild).filter_by(
            state=koji.BUILD_STATES['BUILDING'],
            # Components which are reused should not be counted in, because
            # we do not submit new build for them. They are in BUILDING state
            # just internally in MBS to be handled by
            # scheduler.handlers.components.complete.
            reused_component_id=None).count():
        return True

    return False


def start_build_component(builder, c):
    """
    Submits single component build to builder. Called in thread
    by QueueBasedThreadPool in continue_batch_build.
    """
    import koji
    try:
        c.task_id, c.state, c.state_reason, c.nvr = builder.build(
            artifact_name=c.package, source=c.scmurl)
    except Exception as e:
        c.state = koji.BUILD_STATES['FAILED']
        c.state_reason = "Failed to build artifact %s: %s" % (c.package, str(e))
        log.exception(e)
        return

    if not c.task_id and c.state == koji.BUILD_STATES['BUILDING']:
        c.state = koji.BUILD_STATES['FAILED']
        c.state_reason = ("Failed to build artifact %s: "
                          "Builder did not return task ID" % (c.package))
        return


def continue_batch_build(config, module, session, builder, components=None):
    """
    Continues building current batch. Submits next components in the batch
    until it hits concurrent builds limit.

    Returns list of BaseMessage instances which should be scheduled by the
    scheduler.
    """
    import koji  # Placed here to avoid py2/py3 conflicts...

    # The user can either pass in a list of components to 'seed' the batch, or
    # if none are provided then we just select everything that hasn't
    # successfully built yet or isn't currently being built.
    unbuilt_components = components or [
        c for c in module.component_builds
        if (c.state != koji.BUILD_STATES['COMPLETE'] and
            c.state != koji.BUILD_STATES['BUILDING'] and
            c.state != koji.BUILD_STATES['FAILED'] and
            c.batch == module.batch)
    ]

    if not unbuilt_components:
        log.debug("Cannot continue building module %s. No component to build." % module)
        return []

    # Get the list of components to be built in this batch. We are not building
    # all `unbuilt_components`, because we can meet the num_concurrent_builds
    # threshold
    further_work = []
    components_to_build = []
    # Sort the unbuilt_components so that the components that take the longest to build are
    # first
    log.info('Sorting the unbuilt components by their average build time')
    unbuilt_components.sort(key=lambda c: builder.get_average_build_time(c), reverse=True)
    log.info('Done sorting the unbuilt components by their average build time')

    for c in unbuilt_components:
        # Check the concurrent build threshold.
        if at_concurrent_component_threshold(config, session):
            log.info('Concurrent build threshold met')
            break

        # We set state to "BUILDING" here because at this point we are committed
        # to build the component and at_concurrent_component_threshold() works by
        # counting the number of components in the "BUILDING" state.
        c.state = koji.BUILD_STATES['BUILDING']
        components_to_build.append(c)

    # Start build of components in this batch.
    max_workers = 1
    if config.num_concurrent_builds > 0:
        max_workers = config.num_concurrent_builds
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(start_build_component, builder, c):
                   c for c in components_to_build}
        concurrent.futures.wait(futures)
        # In case there has been an excepion generated directly in the
        # start_build_component, the future.result() will re-raise it in the
        # main thread so it is not lost.
        for future in futures:
            future.result()

    # If all components in this batch are already done, it can mean that they
    # have been built in the past and have been skipped in this module build.
    # We therefore have to generate fake KojiRepoChange message, because the
    # repo has been also done in the past and build system will not send us
    # any message now.
    if (all(c.state in [koji.BUILD_STATES['COMPLETE'],
                        koji.BUILD_STATES['FAILED']] or c.reused_component_id
            for c in unbuilt_components) and builder.module_build_tag):
        further_work += [module_build_service.messaging.KojiRepoChange(
            'start_build_batch: fake msg', builder.module_build_tag['name'])]

    session.commit()
    return further_work


def start_next_batch_build(config, module, session, builder, components=None):
    """
    Tries to start the build of next batch. In case there are still unbuilt
    components in a batch, tries to submit more components until it hits
    concurrent builds limit. Otherwise Increments module.batch and submits component
    builds from the next batch.

    :return: a list of BaseMessage instances to be handled by the MBSConsumer.
    """

    import koji  # Placed here to avoid py2/py3 conflicts...

    # Check the status of the module build and current batch so we can
    # later decide if we can start new batch or not.
    has_unbuilt_components = False
    has_unbuilt_components_in_batch = False
    has_building_components_in_batch = False
    has_failed_components = False
    # This is used to determine if it's worth checking if a component can be reused
    # later on in the code
    all_reused_in_prev_batch = True
    for c in module.component_builds:
        if c.state in [None, koji.BUILD_STATES['BUILDING']]:
            has_unbuilt_components = True

            if c.batch == module.batch:
                if not c.state:
                    has_unbuilt_components_in_batch = True
                elif c.state == koji.BUILD_STATES['BUILDING']:
                    has_building_components_in_batch = True
        elif (c.state in [koji.BUILD_STATES['FAILED'],
                          koji.BUILD_STATES['CANCELED']]):
            has_failed_components = True

        if c.batch == module.batch and not c.reused_component_id:
            all_reused_in_prev_batch = False

    # Do not start new batch if there are no components to build.
    if not has_unbuilt_components:
        log.debug("Not starting new batch, there is no component to build "
                  "for module %s" % module)
        return []

    # Check that there is something to build in current batch before starting
    # the new one. If there is, continue building current batch.
    if has_unbuilt_components_in_batch:
        log.info("Continuing building batch %d", module.batch)
        return continue_batch_build(
            config, module, session, builder, components)

    # Check that there are no components in BUILDING state in current batch.
    # If there are, wait until they are built.
    if has_building_components_in_batch:
        log.debug("Not starting new batch, there are still components in "
                  "BUILDING state in current batch for module %s", module)
        return []

    # Check that there are no failed components in this batch. If there are,
    # do not start the new batch.
    if has_failed_components:
        log.info("Not starting new batch, there are failed components for "
                 "module %s", module)
        return []

    # Identify active tasks which might contain relicts of previous builds
    # and fail the module build if this^ happens.
    active_tasks = builder.list_tasks_for_components(module.component_builds,
                                                     state='active')
    if isinstance(active_tasks, list) and active_tasks:
        state_reason = ("Cannot start a batch, because some components are already"
                        " in 'building' state.")
        state_reason += " See tasks (ID): {}".format(
            ', '.join([str(t['id']) for t in active_tasks])
        )
        module.transition(config, state=models.BUILD_STATES['failed'],
                          state_reason=state_reason)
        session.commit()
        return []

    else:
        log.debug("Builder {} doesn't provide information about active tasks."
                  .format(builder))

    # Find out if there is repo regeneration in progress for this module.
    # If there is, wait until the repo is regenerated before starting a new
    # batch.
    artifacts = [c.nvr for c in module.current_batch()]
    if not builder.buildroot_ready(artifacts):
        log.info("Not starting new batch, not all of %r are in the buildroot. "
                 "Waiting." % artifacts)
        return []

    # Although this variable isn't necessary, it is easier to read code later on with it
    prev_batch = module.batch
    module.batch += 1

    # The user can either pass in a list of components to 'seed' the batch, or
    # if none are provided then we just select everything that hasn't
    # successfully built yet or isn't currently being built.
    unbuilt_components = components or [
        c for c in module.component_builds
        if (c.state != koji.BUILD_STATES['COMPLETE'] and
            c.state != koji.BUILD_STATES['BUILDING'] and
            c.state != koji.BUILD_STATES['FAILED'] and
            c.batch == module.batch)
    ]

    # If there are no components to build, skip the batch and start building
    # the new one. This can happen when resubmitting the failed module build.
    if not unbuilt_components and not components:
        log.info("Skipping build of batch %d, no component to build.",
                 module.batch)
        return start_next_batch_build(config, module, session, builder)

    log.info("Starting build of next batch %d, %s" % (module.batch,
             unbuilt_components))

    # Attempt to reuse any components possible in the batch before attempting to build any
    further_work = []
    unbuilt_components_after_reuse = []
    components_reused = False
    should_try_reuse = True
    # If the rebuild strategy is "changed-and-after", try to figure out if it's worth checking if
    # the components can be reused to save on resources
    if module.rebuild_strategy == 'changed-and-after':
        # Check to see if the previous batch had all their builds reused except for when the
        # previous batch was 1 because that always has the module-build-macros component built
        should_try_reuse = all_reused_in_prev_batch or prev_batch == 1
    if should_try_reuse:
        for c in unbuilt_components:
            previous_component_build = get_reusable_component(
                session, module, c.package)

            if previous_component_build:
                components_reused = True
                further_work += reuse_component(c, previous_component_build)
            else:
                unbuilt_components_after_reuse.append(c)
        # Commit the changes done by reuse_component
        if components_reused:
            session.commit()

    # If all the components were reused in the batch then make a KojiRepoChange
    # message and return
    if components_reused and not unbuilt_components_after_reuse:
        further_work.append(module_build_service.messaging.KojiRepoChange(
            'start_build_batch: fake msg', builder.module_build_tag['name']))
        return further_work

    return further_work + continue_batch_build(
        config, module, session, builder, unbuilt_components_after_reuse)


def pagination_metadata(p_query, request_args):
    """
    Returns a dictionary containing metadata about the paginated query.
    This must be run as part of a Flask request.
    :param p_query: flask_sqlalchemy.Pagination object
    :param request_args: a dictionary of the arguments that were part of the
    Flask request
    :return: a dictionary containing metadata about the paginated query
    """
    request_args_wo_page = dict(copy.deepcopy(request_args))
    # Remove pagination related args because those are handled elsewhere
    # Also, remove any args that url_for accepts in case the user entered
    # those in
    for key in ['page', 'per_page', 'endpoint']:
        if key in request_args_wo_page:
            request_args_wo_page.pop(key)
    for key in request_args:
        if key.startswith('_'):
            request_args_wo_page.pop(key)

    pagination_data = {
        'page': p_query.page,
        'pages': p_query.pages,
        'per_page': p_query.per_page,
        'prev': None,
        'next': None,
        'total': p_query.total,
        'first': url_for(request.endpoint, page=1, per_page=p_query.per_page,
                         _external=True, **request_args_wo_page),
        'last': url_for(request.endpoint, page=p_query.pages,
                        per_page=p_query.per_page, _external=True,
                        **request_args_wo_page)
    }

    if p_query.has_prev:
        pagination_data['prev'] = url_for(request.endpoint, page=p_query.prev_num,
                                          per_page=p_query.per_page, _external=True,
                                          **request_args_wo_page)
    if p_query.has_next:
        pagination_data['next'] = url_for(request.endpoint, page=p_query.next_num,
                                          per_page=p_query.per_page, _external=True,
                                          **request_args_wo_page)

    return pagination_data


def _add_order_by_clause(flask_request, query, column_source):
    """
    Orders the given SQLAlchemy query based on the GET arguments provided
    :param flask_request: a Flask request object
    :param query: a SQLAlchemy query object
    :param column_source: a SQLAlchemy database model
    :return: a SQLAlchemy query object
    """
    colname = "id"
    descending = True
    order_desc_by = flask_request.args.get("order_desc_by", None)
    if order_desc_by:
        colname = order_desc_by
    else:
        order_by = flask_request.args.get("order_by", None)
        if order_by:
            colname = order_by
            descending = False

    column = getattr(column_source, colname, None)
    if not column:
        raise ValidationError('An invalid order_by or order_desc_by key '
                              'was supplied')
    if descending:
        column = column.desc()
    return query.order_by(column)


def filter_component_builds(flask_request):
    """
    Returns a flask_sqlalchemy.Pagination object based on the request parameters
    :param request: Flask request object
    :return: flask_sqlalchemy.Pagination
    """
    search_query = dict()
    state = flask_request.args.get('state', None)

    if state:
        if state.isdigit():
            search_query['state'] = state
        else:
            if state in models.BUILD_STATES:
                search_query['state'] = models.BUILD_STATES[state]
            else:
                raise ValidationError('An invalid state was supplied')

    # Lookup module_build from task_id, ref, format, nvr or tagged attribute
    # of a component build.
    for key in ['task_id', 'ref', 'nvr', 'format', 'tagged']:
        if flask_request.args.get(key, None):
            search_query[key] = flask_request.args[key]

    query = models.ComponentBuild.query

    if search_query:
        query = query.filter_by(**search_query)

    query = _add_order_by_clause(flask_request, query, models.ComponentBuild)

    page = flask_request.args.get('page', 1, type=int)
    per_page = flask_request.args.get('per_page', 10, type=int)
    return query.paginate(page, per_page, False)


def filter_module_builds(flask_request):
    """
    Returns a flask_sqlalchemy.Pagination object based on the request parameters
    :param request: Flask request object
    :return: flask_sqlalchemy.Pagination
    """
    search_query = dict()
    state = flask_request.args.get('state', None)

    if state:
        if state.isdigit():
            search_query['state'] = state
        else:
            if state in models.BUILD_STATES:
                search_query['state'] = models.BUILD_STATES[state]
            else:
                raise ValidationError('An invalid state was supplied')

    for key in ['name', 'owner', 'koji_tag']:
        if flask_request.args.get(key, None):
            search_query[key] = flask_request.args[key]

    query = models.ModuleBuild.query

    if search_query:
        query = query.filter_by(**search_query)

    # This is used when filtering the date request parameters, but it is here to avoid recompiling
    utc_iso_datetime_regex = re.compile(
        r'^(?P<datetime>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?'
        r'(?:Z|[-+]00(?::00)?)?$')

    # Filter the query based on date request parameters
    for item in ('submitted', 'modified', 'completed'):
        for context in ('before', 'after'):
            request_arg = '%s_%s' % (item, context)  # i.e. submitted_before
            iso_datetime_arg = request.args.get(request_arg, None)

            if iso_datetime_arg:
                iso_datetime_matches = re.match(utc_iso_datetime_regex, iso_datetime_arg)

                if not iso_datetime_matches or not iso_datetime_matches.group('datetime'):
                    raise ValidationError(('An invalid Zulu ISO 8601 timestamp was provided'
                                           ' for the "%s" parameter')
                                          % request_arg)
                # Converts the ISO 8601 string to a datetime object for SQLAlchemy to use to filter
                item_datetime = datetime.strptime(iso_datetime_matches.group('datetime'),
                                                  '%Y-%m-%dT%H:%M:%S')
                # Get the database column to filter against
                column = getattr(models.ModuleBuild, 'time_' + item)

                if context == 'after':
                    query = query.filter(column >= item_datetime)
                elif context == 'before':
                    query = query.filter(column <= item_datetime)

    query = _add_order_by_clause(flask_request, query, models.ModuleBuild)

    page = flask_request.args.get('page', 1, type=int)
    per_page = flask_request.args.get('per_page', 10, type=int)
    return query.paginate(page, per_page, False)


def _fetch_mmd(url, branch=None, allow_local_url=False, whitelist_url=False):
    # Import it here, because SCM uses utils methods
    # and fails to import them because of dep-chain.
    import module_build_service.scm

    yaml = ""
    td = None
    scm = None
    try:
        log.debug('Verifying modulemd')
        td = tempfile.mkdtemp()
        if whitelist_url:
            scm = module_build_service.scm.SCM(url, branch, [url], allow_local_url)
        else:
            scm = module_build_service.scm.SCM(url, branch, conf.scmurls, allow_local_url)
        scm.checkout(td)
        scm.verify()
        cofn = scm.get_module_yaml()

        with open(cofn, "r") as mmdfile:
            yaml = mmdfile.read()
    finally:
        try:
            if td is not None:
                shutil.rmtree(td)
        except Exception as e:
            log.warning(
                "Failed to remove temporary directory {!r}: {}".format(
                    td, str(e)))

    mmd = load_mmd(yaml)

    # If the name was set in the modulemd, make sure it matches what the scmurl
    # says it should be
    if mmd.name and mmd.name != scm.name:
        raise ValidationError('The name "{0}" that is stored in the modulemd '
                              'is not valid'.format(mmd.name))
    else:
        mmd.name = scm.name

    # If the stream was set in the modulemd, make sure it matches what the repo
    # branch is
    if mmd.stream and mmd.stream != scm.branch:
        raise ValidationError('The stream "{0}" that is stored in the modulemd '
                              'does not match the branch "{1}"'.format(
                                  mmd.stream, scm.branch))
    else:
        mmd.stream = str(scm.branch)

    # If the version is in the modulemd, throw an exception since the version
    # is generated by pdc-updater
    if mmd.version:
        raise ValidationError('The version "{0}" is already defined in the '
                              'modulemd but it shouldn\'t be since the version '
                              'is generated based on the commit time'.format(
                                  mmd.version))
    else:
        mmd.version = int(scm.version)

    return mmd, scm


def load_mmd(yaml):
    mmd = modulemd.ModuleMetadata()
    try:
        mmd.loads(yaml)
    except Exception as e:
        log.error('Invalid modulemd: %s' % str(e))
        raise UnprocessableEntity('Invalid modulemd: %s' % str(e))
    return mmd


def _scm_get_latest(pkg):
    try:
        # If the modulemd specifies that the 'f25' branch is what
        # we want to pull from, we need to resolve that f25 branch
        # to the specific commit available at the time of
        # submission (now).
        pkgref = module_build_service.scm.SCM(
            pkg.repository).get_latest(pkg.ref)
    except Exception as e:
        log.exception(e)
        return {
            'error': "Failed to get the latest commit for %s#%s" % (pkg.repository, pkg.ref)
        }

    return {
        'pkg_name': pkg.name,
        'pkg_ref': pkgref,
        'error': None
    }


def load_local_builds(local_build_nsvs, session=None):
    """
    Loads previously finished local module builds from conf.mock_resultsdir
    and imports them to database.

    :param local_build_nsvs: List of NSV separated by ':' defining the modules
        to load from the mock_resultsdir.
    """
    if not local_build_nsvs:
        return

    if not session:
        session = db.session

    if type(local_build_nsvs) != list:
        local_build_nsvs = [local_build_nsvs]

    # Get the list of all available local module builds.
    builds = []
    try:
        for d in os.listdir(conf.mock_resultsdir):
            m = re.match('^module-(.*)-([^-]*)-([0-9]+)$', d)
            if m:
                builds.append((m.group(1), m.group(2), int(m.group(3)), d))
    except OSError:
        pass

    # Sort with the biggest version first
    builds.sort(lambda a, b: -cmp(a[2], b[2]))

    for build_id in local_build_nsvs:
        parts = build_id.split(':')
        if len(parts) < 1 or len(parts) > 3:
            raise RuntimeError(
                'The local build "{0}" couldn\'t be be parsed into '
                'NAME[:STREAM[:VERSION]]'.format(build_id))

        name = parts[0]
        stream = parts[1] if len(parts) > 1 else None
        version = int(parts[2]) if len(parts) > 2 else None

        found_build = None
        for build in builds:
            if name != build[0]:
                continue
            if stream is not None and stream != build[1]:
                continue
            if version is not None and version != build[2]:
                continue

            found_build = build
            break

        if not found_build:
            raise RuntimeError(
                'The local build "{0}" couldn\'t be found in "{1}"'.format(
                    build_id, conf.mock_resultsdir))

        # Load the modulemd metadata.
        path = os.path.join(conf.mock_resultsdir, found_build[3], 'results')
        mmd_path = os.path.join(path, 'modules.yaml')
        with open(mmd_path, 'r') as f:
            mmd_data = yaml.safe_load(f)
        mmd = modulemd.ModuleMetadata()
        mmd.loadd(mmd_data)

        # Create ModuleBuild in database.
        module = models.ModuleBuild.create(
            session,
            conf,
            name=mmd.name,
            stream=mmd.stream,
            version=str(mmd.version),
            modulemd=mmd.dumps(),
            scmurl="",
            username="mbs",
            publish_msg=False)
        module.koji_tag = path
        module.state = models.BUILD_STATES['done']
        session.commit()

        if (found_build[0] != module.name or found_build[1] != module.stream or
                str(found_build[2]) != module.version):
            raise RuntimeError(
                'Parsed metadata results for "{0}" don\'t match the directory name'
                .format(found_build[3]))
        log.info("Loaded local module build %r", module)


def format_mmd(mmd, scmurl, session=None):
    """
    Prepares the modulemd for the MBS. This does things such as replacing the
    branches of components with commit hashes and adding metadata in the xmd
    dictionary.
    :param mmd: the ModuleMetadata object to format
    :param scmurl: the url to the modulemd
    """
    # Import it here, because SCM uses utils methods and fails to import
    # them because of dep-chain.
    from module_build_service.scm import SCM

    if not session:
        session = db.session

    mmd.xmd['mbs'] = {'scmurl': scmurl, 'commit': None}

    local_modules = models.ModuleBuild.local_modules(session)
    local_modules = {m.name + "-" + m.stream: m for m in local_modules}

    # If module build was submitted via yaml file, there is no scmurl
    if scmurl:
        scm = SCM(scmurl)
        # If a commit hash is provided, add that information to the modulemd
        if scm.commit:
            # We want to make sure we have the full commit hash for consistency
            if SCM.is_full_commit_hash(scm.scheme, scm.commit):
                full_scm_hash = scm.commit
            else:
                full_scm_hash = scm.get_full_commit_hash()

            mmd.xmd['mbs']['commit'] = full_scm_hash
        # If a commit hash wasn't provided then just get the latest from master
        else:
            mmd.xmd['mbs']['commit'] = scm.get_latest()

    pdc = module_build_service.pdc.get_pdc_client_session(conf)

    # Resolve Build-requires.
    if mmd.buildrequires:
        mmd.xmd['mbs']['buildrequires'] = resolve_requires(
            pdc, mmd.buildrequires)
    else:
        mmd.xmd['mbs']['buildrequires'] = {}

    # Resolve Requires.
    if mmd.requires:
        mmd.xmd['mbs']['requires'] = resolve_requires(pdc, mmd.requires)
    else:
        mmd.xmd['mbs']['requires'] = {}

    if mmd.components:
        if 'rpms' not in mmd.xmd['mbs']:
            mmd.xmd['mbs']['rpms'] = {}
        # Add missing data in RPM components
        for pkgname, pkg in mmd.components.rpms.items():
            if pkg.repository and not conf.rpms_allow_repository:
                raise Forbidden(
                    "Custom component repositories aren't allowed.  "
                    "%r bears repository %r" % (pkgname, pkg.repository))
            if pkg.cache and not conf.rpms_allow_cache:
                raise Forbidden(
                    "Custom component caches aren't allowed.  "
                    "%r bears cache %r" % (pkgname, pkg.cache))
            if not pkg.repository:
                pkg.repository = conf.rpms_default_repository + pkgname
            if not pkg.cache:
                pkg.cache = conf.rpms_default_cache + pkgname
            if not pkg.ref:
                pkg.ref = 'master'

        # Add missing data in included modules components
        for modname, mod in mmd.components.modules.items():
            if mod.repository and not conf.modules_allow_repository:
                raise Forbidden(
                    "Custom module repositories aren't allowed.  "
                    "%r bears repository %r" % (modname, mod.repository))
            if not mod.repository:
                mod.repository = conf.modules_default_repository + modname
            if not mod.ref:
                mod.ref = 'master'

        # Check that SCM URL is valid and replace potential branches in
        # pkg.ref by real SCM hash and store the result to our private xmd
        # place in modulemd.
        pool = ThreadPool(20)
        pkg_dicts = pool.map(_scm_get_latest, mmd.components.rpms.values())
        err_msg = ""
        for pkg_dict in pkg_dicts:
            if pkg_dict["error"]:
                err_msg += pkg_dict["error"] + "\n"
            else:
                pkg_name = pkg_dict["pkg_name"]
                pkg_ref = pkg_dict["pkg_ref"]
                mmd.xmd['mbs']['rpms'][pkg_name] = {'ref': pkg_ref}
        if err_msg:
            raise UnprocessableEntity(err_msg)


def validate_mmd(mmd):
    for modname, mod in mmd.components.modules.items():
        if mod.repository and not conf.modules_allow_repository:
            raise Forbidden(
                "Custom module repositories aren't allowed.  "
                "%r bears repository %r" % (modname, mod.repository))


def merge_included_mmd(mmd, included_mmd):
    """
    Merges two modulemds. This merges only metadata which are needed in
    the `main` when it includes another module defined by `included_mmd`
    """
    if 'rpms' in included_mmd.xmd['mbs']:
        if 'rpms' not in mmd.xmd['mbs']:
            mmd.xmd['mbs']['rpms'] = included_mmd.xmd['mbs']['rpms']
        else:
            mmd.xmd['mbs']['rpms'].update(included_mmd.xmd['mbs']['rpms'])


def record_component_builds(mmd, module, initial_batch=1,
                            previous_buildorder=None, main_mmd=None, session=None):
    if not session:
        session = db.session

    # Format the modulemd by putting in defaults and replacing streams that
    # are branches with commit hashes
    format_mmd(mmd, module.scmurl, session=session)

    # When main_mmd is set, merge the metadata from this mmd to main_mmd,
    # otherwise our current mmd is main_mmd.
    if main_mmd:
        # Check for components that are in both MMDs before merging since MBS
        # currently can't handle that situation.
        duplicate_components = [rpm for rpm in main_mmd.components.rpms.keys()
                                if rpm in mmd.components.rpms.keys()]
        if duplicate_components:
            error_msg = (
                'The included module "{0}" in "{1}" have the following '
                'conflicting components: {2}'
                .format(mmd.name, main_mmd.name,
                        ', '.join(duplicate_components)))
            raise UnprocessableEntity(error_msg)
        merge_included_mmd(main_mmd, mmd)
    else:
        main_mmd = mmd

    # If the modulemd yaml specifies components, then submit them for build
    if mmd.components:
        components = mmd.components.all
        components.sort(key=lambda x: x.buildorder)

        # We do not start with batch = 0 here, because the first batch is
        # reserved for module-build-macros. First real components must be
        # planned for batch 2 and following.
        batch = initial_batch

        for pkg in components:
            # Increment the batch number when buildorder increases.
            if previous_buildorder != pkg.buildorder:
                previous_buildorder = pkg.buildorder
                batch += 1

            # If the pkg is another module, we fetch its modulemd file
            # and record its components recursively with the initial_batch
            # set to our current batch, so the components of this module
            # are built in the right global order.
            if isinstance(pkg, modulemd.ModuleComponentModule):
                full_url = pkg.repository + "?#" + pkg.ref
                # It is OK to whitelist all URLs here, because the validity
                # of every URL have been already checked in format_mmd(...).
                included_mmd = _fetch_mmd(full_url, whitelist_url=True)[0]
                batch = record_component_builds(included_mmd, module, batch,
                                                previous_buildorder, main_mmd, session=session)
                continue

            pkgref = mmd.xmd['mbs']['rpms'][pkg.name]['ref']
            full_url = pkg.repository + "?#" + pkgref
            build = models.ComponentBuild(
                module_id=module.id,
                package=pkg.name,
                format="rpms",
                scmurl=full_url,
                batch=batch,
                ref=pkgref
            )
            session.add(build)

        return batch


def submit_module_build_from_yaml(username, handle, stream=None, optional_params=None):
    yaml = handle.read()
    mmd = load_mmd(yaml)

    # Mimic the way how default values are generated for modules that are stored in SCM
    # We can take filename as the module name as opposed to repo name,
    # and also we can take numeric representation of current datetime
    # as opposed to datetime of the last commit
    dt = datetime.utcfromtimestamp(int(time.time()))
    def_name = str(handle.filename.split(".")[0])
    def_version = int(dt.strftime("%Y%m%d%H%M%S"))

    mmd.name = mmd.name or def_name
    mmd.stream = mmd.stream or stream or "master"
    mmd.version = mmd.version or def_version

    return submit_module_build(username, None, mmd, None, yaml, optional_params)


_url_check_re = re.compile(r"^[^:/]+:.*$")


def submit_module_build_from_scm(username, url, branch, allow_local_url=False,
                                 skiptests=False, optional_params=None):
    # Translate local paths into file:// URL
    if allow_local_url and not _url_check_re.match(url):
        log.info(
            "'{}' is not a valid URL, assuming local path".format(url))
        url = os.path.abspath(url)
        url = "file://" + url
    mmd, scm = _fetch_mmd(url, branch, allow_local_url)
    if skiptests:
        mmd.buildopts.rpms.macros += "\n\n%__spec_check_pre exit 0\n"
    return submit_module_build(username, url, mmd, scm, yaml, optional_params)


def submit_module_build(username, url, mmd, scm, yaml, optional_params=None):
    import koji  # Placed here to avoid py2/py3 conflicts...

    # Import it here, because SCM uses utils methods
    # and fails to import them because of dep-chain.
    validate_mmd(mmd)
    module = models.ModuleBuild.query.filter_by(
        name=mmd.name, stream=mmd.stream, version=str(mmd.version)).first()
    if module:
        log.debug('Checking whether module build already exist.')
        if module.state != models.BUILD_STATES['failed']:
            err_msg = ('Module (state=%s) already exists. Only a new build or resubmission of '
                       'a failed build is allowed.' % module.state)
            log.error(err_msg)
            raise Conflict(err_msg)
        if optional_params:
            rebuild_strategy = optional_params.get('rebuild_strategy')
            if rebuild_strategy and module.rebuild_strategy != rebuild_strategy:
                raise ValidationError('You cannot change the module\'s "rebuild_strategy" when '
                                      'resuming a module build')
        log.debug('Resuming existing module build %r' % module)
        # Reset all component builds that didn't complete
        for component in module.component_builds:
            if component.state and component.state != koji.BUILD_STATES['COMPLETE']:
                component.state = None
                db.session.add(component)
        module.username = username
        prev_state = module.previous_non_failed_state
        if prev_state == models.BUILD_STATES['init']:
            transition_to = models.BUILD_STATES['init']
        else:
            transition_to = models.BUILD_STATES['wait']
            module.batch = 0
        module.transition(conf, transition_to, "Resubmitted by %s" % username)
        log.info("Resumed existing module build in previous state %s"
                 % module.state)
    else:
        log.debug('Creating new module build')
        module = models.ModuleBuild.create(
            db.session,
            conf,
            name=mmd.name,
            stream=mmd.stream,
            version=str(mmd.version),
            modulemd=mmd.dumps(),
            scmurl=url,
            username=username,
            **(optional_params or {})
        )

    db.session.add(module)
    db.session.commit()
    log.info("%s submitted build of %s, stream=%s, version=%s", username,
             mmd.name, mmd.stream, mmd.version)
    return module


def scm_url_schemes(terse=False):
    """
    Definition of URL schemes supported by both frontend and scheduler.

    NOTE: only git URLs in the following formats are supported atm:
        git://
        git+http://
        git+https://
        git+rsync://
        http://
        https://
        file://

    :param terse=False: Whether to return terse list of unique URL schemes
                        even without the "://".
    """

    scm_types = {
        "git": ("git://", "git+http://", "git+https://",
                "git+rsync://", "http://", "https://", "file://")
    }

    if not terse:
        return scm_types
    else:
        scheme_list = []
        for scm_type, scm_schemes in scm_types.items():
            scheme_list.extend([scheme[:-3] for scheme in scm_schemes])
        return list(set(scheme_list))


def get_scm_url_re():
    schemes_re = '|'.join(map(re.escape, scm_url_schemes(terse=True)))
    return re.compile(
        r"(?P<giturl>(?:(?P<scheme>(" + schemes_re + r"))://(?P<host>[^/]+))?"
        r"(?P<repopath>/[^\?]+))\?(?P<modpath>[^#]*)#(?P<revision>.+)")


def module_build_state_from_msg(msg):
    state = int(msg.module_build_state)
    # TODO better handling
    assert state in models.BUILD_STATES.values(), (
        'state=%s(%s) is not in %s'
        % (state, type(state), list(models.BUILD_STATES.values())))
    return state


def reuse_component(component, previous_component_build,
                    change_state_now=False):
    """
    Reuses component build `previous_component_build` instead of building
    component `component`

    Returns the list of BaseMessage instances to be handled later by the
    scheduler.
    """

    import koji

    log.info(
        'Reusing component "{0}" from a previous module '
        'build with the nvr "{1}"'.format(
            component.package, previous_component_build.nvr))
    component.reused_component_id = previous_component_build.id
    component.task_id = previous_component_build.task_id
    if change_state_now:
        component.state = previous_component_build.state
    else:
        # Use BUILDING state here, because we want the state to change to
        # COMPLETE by the fake KojiBuildChange message we are generating
        # few lines below. If we would set it to the right state right
        # here, we would miss the code path handling the KojiBuildChange
        # which works only when switching from BUILDING to COMPLETE.
        component.state = koji.BUILD_STATES['BUILDING']
    component.state_reason = \
        'Reused component from previous module build'
    component.nvr = previous_component_build.nvr
    nvr_dict = kobo.rpmlib.parse_nvr(component.nvr)
    # Add this message to further_work so that the reused
    # component will be tagged properly
    return [
        module_build_service.messaging.KojiBuildChange(
            msg_id='reuse_component: fake msg',
            build_id=None,
            task_id=component.task_id,
            build_new_state=previous_component_build.state,
            build_name=component.package,
            build_version=nvr_dict['version'],
            build_release=nvr_dict['release'],
            module_build_id=component.module_id,
            state_reason=component.state_reason
        )
    ]


def attempt_to_reuse_all_components(builder, session, module):
    """
    Tries to reuse all the components in a build. The components are also
    tagged to the tags using the `builder`.

    Returns True if all components could be reused, otherwise False. When
    False is returned, no component has been reused.
    """

    # [(component, component_to_reuse), ...]
    component_pairs = []

    # Find out if we can reuse all components and cache component and
    # component to reuse pairs.
    for c in module.component_builds:
        if c.package == "module-build-macros":
            continue
        component_to_reuse = get_reusable_component(
            session, module, c.package)
        if not component_to_reuse:
            return False

        component_pairs.append((c, component_to_reuse))

    # Stores components we will tag to buildroot and final tag.
    components_to_tag = []

    # Reuse all components.
    for c, component_to_reuse in component_pairs:
        # Set the module.batch to the last batch we have.
        if c.batch > module.batch:
            module.batch = c.batch

        # Reuse the component
        reuse_component(c, component_to_reuse, True)
        components_to_tag.append(c.nvr)

    # Tag them
    builder.buildroot_add_artifacts(components_to_tag, install=False)
    builder.tag_artifacts(components_to_tag)

    return True


def get_reusable_component(session, module, component_name):
    """
    Returns the component (RPM) build of a module that can be reused
    instead of needing to rebuild it
    :param session: SQLAlchemy database session
    :param module: the ModuleBuild object of module being built with a formatted
    mmd
    :param component_name: the name of the component (RPM) that you'd like to
    reuse a previous build of
    :return: the component (RPM) build SQLAlchemy object, if one is not found,
    None is returned
    """

    # We support components reusing only for koji and test backend.
    if conf.system not in ['koji', 'test']:
        return None

    # If the rebuild strategy is "all", that means that nothing can be reused
    if module.rebuild_strategy == 'all':
        log.info('Cannot re-use the component because the rebuild strategy is "all".')
        return None

    mmd = module.mmd()
    # Find the latest module that is in the done or ready state
    previous_module_build = session.query(models.ModuleBuild)\
        .filter_by(name=mmd.name)\
        .filter_by(stream=mmd.stream)\
        .filter(models.ModuleBuild.state.in_([3, 5]))\
        .filter(models.ModuleBuild.scmurl.isnot(None))\
        .order_by(models.ModuleBuild.time_completed.desc())
    # If we are rebuilding with the "changed-and-after" option, then we can't reuse
    # components from modules that were built more liberally
    if module.rebuild_strategy == 'changed-and-after':
        previous_module_build = previous_module_build.filter(
            models.ModuleBuild.rebuild_strategy.in_(['all', 'changed-and-after']))
    previous_module_build = previous_module_build.first()
    # The component can't be reused if there isn't a previous build in the done
    # or ready state
    if not previous_module_build:
        log.info("Cannot re-use.  %r is the first module build." % module)
        return None

    old_mmd = previous_module_build.mmd()

    # Perform a sanity check to make sure that the buildrequires are the same
    # as the buildrequires in xmd for the passed in mmd
    if set(mmd.buildrequires.keys()) != set(mmd.xmd['mbs']['buildrequires'].keys()):
        log.error(
            'Cannot re-use.  The submitted module "{0}" has different keys in '
            'mmd.buildrequires than in '
            'mmd.xmd[\'mbs\'][\'buildrequires\']'.format(mmd.name))
        return None
    # Perform a sanity check to make sure that the buildrequires are the same
    # as the buildrequires in xmd for the mmd of the previous module build
    if set(old_mmd.buildrequires.keys()) != \
            set(old_mmd.xmd['mbs']['buildrequires'].keys()):
        log.error(
            'Cannot re-use.  Version "{0}" of the module "{1}" has different '
            'keys in mmd.buildrequires than in '
            'mmd.xmd[\'mbs\'][\'buildrequires\']'
            .format(previous_module_build.version, previous_module_build.name))
        return None

    # If the chosen component for some reason was not found in the database,
    # or the ref is missing, something has gone wrong and the component cannot
    # be reused
    new_module_build_component = models.ComponentBuild.from_component_name(
        session, component_name, module.id)
    if not new_module_build_component or not new_module_build_component.batch \
            or not new_module_build_component.ref:
        log.info('Cannot re-use.  New component not found in the db.')
        return None

    prev_module_build_component = models.ComponentBuild.from_component_name(
        session, component_name, previous_module_build.id)
    # If the component to reuse for some reason was not found in the database,
    # or the ref is missing, something has gone wrong and the component cannot
    # be reused
    if not prev_module_build_component or not prev_module_build_component.batch\
            or not prev_module_build_component.ref:
        log.info('Cannot re-use.  Previous component not found in the db.')
        return None

    # Make sure the ref for the component that is trying to be reused
    # hasn't changed since the last build
    if prev_module_build_component.ref != new_module_build_component.ref:
        log.info('Cannot re-use.  Component commit hashes do not match.')
        return None

    # At this point we've determined that both module builds contain the component
    # and the components share the same commit hash
    if module.rebuild_strategy == 'changed-and-after':
        # Make sure the batch number for the component that is trying to be reused
        # hasn't changed since the last build
        if prev_module_build_component.batch != new_module_build_component.batch:
            log.info('Cannot re-use.  Batch numbers do not match.')
            return None

        # If the mmd.buildopts.macros.rpms changed, we cannot reuse
        modulemd_macros = ""
        old_modulemd_macros = ""
        if mmd.buildopts and mmd.buildopts.rpms:
            modulemd_macros = mmd.buildopts.rpms.macros
        if old_mmd.buildopts and old_mmd.buildopts.rpms:
            modulemd_macros = old_mmd.buildopts.rpms.macros
        if modulemd_macros != old_modulemd_macros:
            log.info('Cannot re-use.  Old modulemd macros do not match the new.')
            return None

        # If the module buildrequires are different, then we can't reuse the
        # component
        if mmd.buildrequires.keys() != old_mmd.buildrequires.keys():
            log.info('Cannot re-use.  The set of module buildrequires changed')
            return None

        # Make sure that the module buildrequires commit hashes are exactly the same
        for br_module_name, br_module in \
                mmd.xmd['mbs']['buildrequires'].items():
            # Assumes that the streams have been replaced with commit hashes, so we
            # can compare to see if they have changed. Since a build is unique to
            # a commit hash, this is a safe test.
            ref1 = br_module.get('ref')
            ref2 = old_mmd.xmd['mbs']['buildrequires'][br_module_name].get('ref')
            if not (ref1 and ref2) or ref1 != ref2:
                log.info('Cannot re-use.  The module buildrequires hashes changed')
                return None

        # At this point we've determined that both module builds contain the component
        # with the same commit hash and they are in the same batch. We've also determined
        # that both module builds depend(ed) on the same exact module builds. Now it's time
        # to determine if the components before it have changed.
        #
        # Convert the component_builds to a list and sort them by batch
        new_component_builds = list(module.component_builds)
        new_component_builds.sort(key=lambda x: x.batch)
        prev_component_builds = list(previous_module_build.component_builds)
        prev_component_builds.sort(key=lambda x: x.batch)

        new_module_build_components = []
        previous_module_build_components = []
        # Create separate lists for the new and previous module build. These lists
        # will have an entry for every build batch *before* the component's
        # batch except for 1, which is reserved for the module-build-macros RPM.
        # Each batch entry will contain a set of "(name, ref)" with the name and
        # ref (commit) of the component.
        for i in range(new_module_build_component.batch - 1):
            # This is the first batch which we want to skip since it will always
            # contain only the module-build-macros RPM and it gets built every time
            if i == 0:
                continue

            new_module_build_components.append(set([
                (value.package, value.ref) for value in
                new_component_builds if value.batch == i + 1
            ]))

            previous_module_build_components.append(set([
                (value.package, value.ref) for value in
                prev_component_builds if value.batch == i + 1
            ]))

        # If the previous batches don't have the same ordering and hashes, then the
        # component can't be reused
        if previous_module_build_components != new_module_build_components:
            log.info('Cannot re-use.  Ordering or commit hashes of '
                     'previous batches differ.')
            return None

    reusable_component = models.ComponentBuild.query.filter_by(
        package=component_name, module_id=previous_module_build.id).one()
    log.debug('Found reusable component!')
    return reusable_component


def validate_koji_tag(tag_arg_names, pre='', post='-', dict_key='name'):
    """
    Used as a decorator validates koji tag arg(s)' value(s)
    against configurable list of koji tag prefixes.
    Supported arg value types are: dict, list, str

    :param tag_arg_names: Str or list of parameters to validate.
    :param pre: Prepend this optional string (e.g. '.' in case of disttag
    validation) to each koji tag prefix.
    :param post: Append this string/delimiter ('-' by default) to each koji
    tag prefix.
    :param dict_key: In case of a dict arg, inspect this key ('name' by default).
    """

    if not isinstance(tag_arg_names, list):
        tag_arg_names = [tag_arg_names]

    def validation_decorator(function):
        def wrapper(*args, **kwargs):
            call_args = inspect.getcallargs(function, *args, **kwargs)

            for tag_arg_name in tag_arg_names:
                err_subject = "Koji tag validation:"

                # If any of them don't appear in the function, then fail.
                if tag_arg_name not in call_args:
                    raise ProgrammingError(
                        '{} Inspected argument {} is not within function args.'
                        ' The function was: {}.'
                        .format(err_subject, tag_arg_name, function.__name__))

                tag_arg_val = call_args[tag_arg_name]

                # First, check that we have some value
                if not tag_arg_val:
                    raise ValidationError('{} Can not validate {}. No value provided.'
                                          .format(err_subject, tag_arg_name))

                # If any of them are a dict, then use the provided dict_key
                if isinstance(tag_arg_val, dict):
                    if dict_key not in tag_arg_val:
                        raise ProgrammingError(
                            '{} Inspected dict arg {} does not contain {} key.'
                            ' The function was: {}.'
                            .format(err_subject, tag_arg_name, dict_key, function.__name__))
                    tag_list = [tag_arg_val[dict_key]]
                elif isinstance(tag_arg_val, list):
                    tag_list = tag_arg_val
                else:
                    tag_list = [tag_arg_val]

                # Check to make sure the provided values match our whitelist.
                for allowed_prefix in conf.koji_tag_prefixes:
                    if all([t.startswith(pre + allowed_prefix + post) for t in tag_list]):
                        break
                else:
                    # Only raise this error if the given tags don't start with
                    # *any* of our allowed prefixes.
                    raise ValidationError(
                        'Koji tag validation: {} does not satisfy any of allowed prefixes: {}'
                        .format(tag_list,
                                [pre + p + post for p in conf.koji_tag_prefixes]))

            # Finally.. after all that validation, call the original function
            # and return its value.
            return function(*args, **kwargs)

        # We're replacing the original function with our synthetic wrapper,
        # but dress it up to make it look more like the original function.
        wrapper.__name__ = function.__name__
        wrapper.__doc__ = function.__doc__
        return wrapper

    return validation_decorator


def get_rpm_release_from_mmd(mmd):
    """
    Returns the dist tag based on the modulemd metadata and MBS configuration.
    """

    if not mmd.name or not mmd.stream or not mmd.version:
        raise ValueError("Modulemd name, stream, and version are required.")

    dist_str = '.'.join([mmd.name, mmd.stream, str(mmd.version)])
    dist_hash = hashlib.sha1(dist_str).hexdigest()[:8]
    return conf.default_dist_tag_prefix + dist_hash


def create_dogpile_key_generator_func(skip_first_n_args=0):
    """
    Creates dogpile key_generator function with additional features:

    - when models.ModuleBuild is an argument of method cached by dogpile-cache,
      the ModuleBuild.id is used as a key. Therefore it is possible to cache
      data per particular module build, while normally, it would be per
      ModuleBuild.__str__() output, which contains also batch and other data
      which changes during the build of a module.
    - it is able to skip first N arguments of a cached method. This is useful
      when the db.session or PDCClient instance is part of cached method call,
      and the caching should work no matter what session instance is passed
      to cached method argument.
    """
    def key_generator(namespace, fn):
        fname = fn.__name__

        def generate_key(*arg, **kwarg):
            key_template = fname + "_"
            for s in arg[skip_first_n_args:]:
                if type(s) == models.ModuleBuild:
                    key_template += str(s.id)
                else:
                    key_template += str(s) + "_"
            return key_template

        return generate_key
    return key_generator


def cors_header(allow='*'):
    """
    A decorator that sets the Access-Control-Allow-Origin header to the desired value on a Flask
    route
    :param allow: a string of the domain to allow. This defaults to '*'.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            rv = func(*args, **kwargs)
            if rv:
                # If a tuple was provided, then the Flask Response should be the first object
                if isinstance(rv, tuple):
                    response = rv[0]
                else:
                    response = rv
                # Make sure we are dealing with a Flask Response object
                if isinstance(response, Response):
                    response.headers.add('Access-Control-Allow-Origin', allow)
            return rv
        return wrapper
    return decorator
