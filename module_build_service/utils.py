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
import functools
import time
import shutil
import tempfile
import os
import logging
import copy
import kobo.rpmlib
import inspect
from six import iteritems

import modulemd

from flask import request, url_for
from datetime import datetime

from module_build_service import log, models
from module_build_service.errors import (ValidationError, UnprocessableEntity,
                                         ProgrammingError)
from module_build_service import conf, db
from module_build_service.errors import (Forbidden, Conflict)
import module_build_service.messaging
from multiprocessing.dummy import Pool as ThreadPool
import module_build_service.pdc
from module_build_service.pdc import get_module_commit_hash_and_version

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

    import koji  # Placed here to avoid py2/py3 conflicts...

    if config.num_consecutive_builds and config.num_consecutive_builds <= \
        session.query(models.ComponentBuild).filter_by(
            state=koji.BUILD_STATES['BUILDING']).count():
        return True

    return False

def start_build_component(builder, c):
    """
    Submits single component build to builder. Called in thread
    by QueueBasedThreadPool in continue_batch_build.
    """
    try:
        c.task_id, c.state, c.state_reason, c.nvr = builder.build(
            artifact_name=c.package, source=c.scmurl)
    except Exception as e:
        c.state = koji.BUILD_STATES['FAILED']
        c.state_reason = "Failed to build artifact %s: %s" % (c.package, str(e))
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
        if (c.state != koji.BUILD_STATES['COMPLETE']
            and c.state != koji.BUILD_STATES['BUILDING']
            and c.state != koji.BUILD_STATES['FAILED']
            and c.batch == module.batch)
    ]

    if not unbuilt_components:
        log.debug("Cannot continue building module %s. No component to build." % module)
        return []

    # Get the list of components to be build in this batch. We are not
    # building all `unbuilt_components`, because we can a) meet
    # the num_consecutive_builds threshold or b) reuse previous build.
    further_work = []
    components_to_build = []
    for c in unbuilt_components:
        previous_component_build = None
        # Check to see if we can reuse a previous component build
        # instead of rebuilding it if the builder is Koji
        if conf.system == 'koji':
            previous_component_build = get_reusable_component(
                session, module, c.package)
        # If a component build can't be reused, we need to check
        # the concurrent threshold
        if not previous_component_build and \
                at_concurrent_component_threshold(config, session):
            log.info('Concurrent build threshold met')
            break

        if previous_component_build:
            log.info(
                'Reusing component "{0}" from a previous module '
                'build with the nvr "{1}"'.format(
                    c.package, previous_component_build.nvr))
            c.reused_component_id = previous_component_build.id
            c.task_id = previous_component_build.task_id
            # Use BUILDING state here, because we want the state to change to
            # COMPLETE by the fake KojiBuildChange message we are generating
            # few lines below. If we would set it to the right state right
            # here, we would miss the code path handling the KojiBuildChange
            # which works only when switching from BUILDING to COMPLETE.
            c.state = koji.BUILD_STATES['BUILDING']
            c.state_reason = \
                'Reused component from previous module build'
            c.nvr = previous_component_build.nvr
            nvr_dict = kobo.rpmlib.parse_nvr(c.nvr)
            # Add this message to further_work so that the reused
            # component will be tagged properly
            further_work.append(
                module_build_service.messaging.KojiBuildChange(
                    msg_id='start_build_batch: fake msg',
                    build_id=None,
                    task_id=c.task_id,
                    build_new_state=previous_component_build.state,
                    build_name=c.package,
                    build_version=nvr_dict['version'],
                    build_release=nvr_dict['release'],
                    module_build_id=c.module_id,
                    state_reason=c.state_reason
                )
            )
            continue

        # We set state to BUILDING here, because we are going to build the
        # component anyway and at_concurrent_component_threshold() works
        # by counting components in BUILDING state.
        c.state = koji.BUILD_STATES['BUILDING']
        components_to_build.append(c)

    # Start build of components in this batch.
    with concurrent.futures.ThreadPoolExecutor(max_workers=config.num_consecutive_builds) as executor:
        futures = {executor.submit(start_build_component, builder, c): c for c in components_to_build}
        concurrent.futures.wait(futures)

    # If all components in this batch are already done, it can mean that they
    # have been built in the past and have been skipped in this module build.
    # We therefore have to generate fake KojiRepoChange message, because the
    # repo has been also done in the past and build system will not send us
    # any message now.
    if (all(c.state in [koji.BUILD_STATES['COMPLETE'], koji.BUILD_STATES['FAILED']]
            or c.reused_component_id
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
        state_reason = "Cannot start a batch, because some components are already in 'building' state."
        state_reason += " See tasks (ID): {}".format(', '.join([str(t['id']) for t in active_tasks]))
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

    module.batch += 1

    # The user can either pass in a list of components to 'seed' the batch, or
    # if none are provided then we just select everything that hasn't
    # successfully built yet or isn't currently being built.
    unbuilt_components = components or [
        c for c in module.component_builds
        if (c.state != koji.BUILD_STATES['COMPLETE']
            and c.state != koji.BUILD_STATES['BUILDING']
            and c.state != koji.BUILD_STATES['FAILED']
            and c.batch == module.batch)
    ]

    log.info("Starting build of next batch %d, %s" % (module.batch,
        unbuilt_components))

    return continue_batch_build(
        config, module, session, builder, unbuilt_components)

def pagination_metadata(p_query):
    """
    Returns a dictionary containing metadata about the paginated query. This must be run as part of a Flask request.
    :param p_query: flask_sqlalchemy.Pagination object
    :return: a dictionary containing metadata about the paginated query
    """

    pagination_data = {
        'page': p_query.page,
        'per_page': p_query.per_page,
        'total': p_query.total,
        'pages': p_query.pages,
        'first': url_for(request.endpoint, page=1, per_page=p_query.per_page, _external=True),
        'last': url_for(request.endpoint, page=p_query.pages, per_page=p_query.per_page, _external=True)
    }

    if p_query.has_prev:
        pagination_data['prev'] = url_for(request.endpoint, page=p_query.prev_num,
                                          per_page=p_query.per_page, _external=True)
    if p_query.has_next:
        pagination_data['next'] = url_for(request.endpoint, page=p_query.next_num,
                                          per_page=p_query.per_page, _external=True)

    return pagination_data


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

    for key in ['name', 'owner']:
        if flask_request.args.get(key, None):
            search_query[key] = flask_request.args[key]

    query = models.ModuleBuild.query

    if search_query:
        query = query.filter_by(**search_query)

    # This is used when filtering the date request parameters, but it is here to avoid recompiling
    utc_iso_datetime_regex = re.compile(r'^(?P<datetime>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?'
                                        r'(?:Z|[-+]00(?::00)?)?$')

    # Filter the query based on date request parameters
    for item in ('submitted', 'modified', 'completed'):
        for context in ('before', 'after'):
            request_arg = '%s_%s' % (item, context)  # i.e. submitted_before
            iso_datetime_arg = request.args.get(request_arg, None)

            if iso_datetime_arg:
                iso_datetime_matches = re.match(utc_iso_datetime_regex, iso_datetime_arg)

                if not iso_datetime_matches or not iso_datetime_matches.group('datetime'):
                    raise ValidationError('An invalid Zulu ISO 8601 timestamp was provided for the "%s" parameter'
                                          % request_arg)
                # Converts the ISO 8601 string to a datetime object for SQLAlchemy to use to filter
                item_datetime = datetime.strptime(iso_datetime_matches.group('datetime'), '%Y-%m-%dT%H:%M:%S')
                # Get the database column to filter against
                column = getattr(models.ModuleBuild, 'time_' + item)

                if context == 'after':
                    query = query.filter(column >= item_datetime)
                elif context == 'before':
                    query = query.filter(column <= item_datetime)

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
        cod = scm.checkout(td)
        scm.verify(cod)
        cofn = os.path.join(cod, (scm.name + ".yaml"))

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

    return mmd, scm, yaml


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
        pkg.ref = module_build_service.scm.SCM(
            pkg.repository).get_latest(branch=pkg.ref)
    except Exception as e:
        return "Failed to get the latest commit for %s#%s" % (pkg.repository, pkg.ref)
    return None

def format_mmd(mmd, scmurl):
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

    mmd.xmd['mbs'] = {'scmurl': scmurl}

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
        scm = SCM(scmurl)
        mmd.xmd['mbs']['commit'] = scm.get_latest()


    # If the modulemd yaml specifies module buildrequires, replace the streams
    # with commit hashes
    if mmd.buildrequires:
        mmd.xmd['mbs']['buildrequires'] = copy.deepcopy(mmd.buildrequires)
        pdc = module_build_service.pdc.get_pdc_client_session(conf)
        for module_name, module_stream in \
                mmd.xmd['mbs']['buildrequires'].items():
            # Assumes that module_stream is the stream and not the commit hash
            module_info = {
                'name': module_name,
                'version': module_stream}
            commit_hash, version = get_module_commit_hash_and_version(
                pdc, module_info)
            if commit_hash and version:
                mmd.xmd['mbs']['buildrequires'][module_name] = {
                    'ref': commit_hash,
                    'stream': mmd.buildrequires[module_name],
                    'version': version
                }
            else:
                raise RuntimeError(
                    'The module "{0}" didn\'t contain either a commit hash or a'
                    ' version in PDC'.format(module_name))
    else:
        mmd.xmd['mbs']['buildrequires'] = {}

    if mmd.components:
        # Add missing data in RPM components
        for pkgname, pkg in mmd.components.rpms.items():
            if pkg.repository and not conf.rpms_allow_repository:
                raise Forbidden(
                    "Custom component repositories aren't allowed")
            if pkg.cache and not conf.rpms_allow_cache:
                raise Forbidden("Custom component caches aren't allowed")
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
                    "Custom component repositories aren't allowed")
            if not mod.repository:
                mod.repository = conf.modules_default_repository + modname
            if not mod.ref:
                mod.ref = 'master'

        # Check that SCM URL is valid and replace potential branches in
        # pkg.ref by real SCM hash.
        pool = ThreadPool(20)
        err_msgs = pool.map(_scm_get_latest, mmd.components.rpms.values())
        # TODO: only the first error message is raised, perhaps concatenate
        # the messages together?
        for err_msg in err_msgs:
            if err_msg:
                raise UnprocessableEntity(err_msg)

def record_component_builds(scm, mmd, module, initial_batch = 1):
    import koji  # Placed here to avoid py2/py3 conflicts...

    # Format the modulemd by putting in defaults and replacing streams that
    # are branches with commit hashes
    try:
        format_mmd(mmd, module.scmurl)
    except Exception:
        module.transition(conf, models.BUILD_STATES["failed"])
        db.session.add(module)
        db.session.commit()
        raise

    # List of (pkg_name, git_url) tuples to be used to check
    # the availability of git URLs in parallel later.
    full_urls = []

    # If the modulemd yaml specifies components, then submit them for build
    if mmd.components:
        for pkgname, pkg in mmd.components.rpms.items():
            full_url = "%s?#%s" % (pkg.repository, pkg.ref)
            full_urls.append((pkgname, full_url))

        components = mmd.components.all
        components.sort(key=lambda x: x.buildorder)
        previous_buildorder = None

        # We do not start with batch = 0 here, because the first batch is
        # reserved for module-build-macros. First real components must be
        # planned for batch 2 and following.
        batch = initial_batch

        for pkg in components:
            # If the pkg is another module, we fetch its modulemd file
            # and record its components recursively with the initial_batch
            # set to our current batch, so the components of this module
            # are built in the right global order.
            if isinstance(pkg, modulemd.ModuleComponentModule):
                full_url = pkg.repository + "?#" + pkg.ref
                # It is OK to whitelist all URLs here, because the validity
                # of every URL have been already checked in format_mmd(...).
                mmd = _fetch_mmd(full_url, whitelist_url=True)[0]
                batch = record_component_builds(scm, mmd, module, batch)
                continue

            if previous_buildorder != pkg.buildorder:
                previous_buildorder = pkg.buildorder
                batch += 1

            full_url = pkg.repository + "?#" + pkg.ref

            existing_build = models.ComponentBuild.query.filter_by(
                module_id=module.id, package=pkg.name).first()
            if existing_build:
                if existing_build.state != koji.BUILD_STATES['COMPLETE']:
                    existing_build.state = None
                    db.session.add(existing_build)
            else:
                # XXX: what about components that were present in previous
                # builds but are gone now (component reduction)?
                build = models.ComponentBuild(
                    module_id=module.id,
                    package=pkg.name,
                    format="rpms",
                    scmurl=full_url,
                    batch=batch,
                    ref=pkg.ref
                )
                db.session.add(build)

        return batch


def submit_module_build_from_yaml(username, yaml, optional_params=None):
    mmd = load_mmd(yaml)
    return submit_module_build(username, None, mmd, None, yaml, optional_params)


def submit_module_build_from_scm(username, url, branch, allow_local_url=False,
                                 optional_params=None):
    mmd, scm, yaml = _fetch_mmd(url, branch, allow_local_url)
    return submit_module_build(username, url, mmd, scm, yaml, optional_params)


def submit_module_build(username, url, mmd, scm, yaml, optional_params=None):
    # Import it here, because SCM uses utils methods
    # and fails to import them because of dep-chain.
    import module_build_service.scm

    module = models.ModuleBuild.query.filter_by(
        name=mmd.name, stream=mmd.stream, version=str(mmd.version)).first()
    if module:
        log.debug('Checking whether module build already exist.')
        # TODO: make this configurable, we might want to allow
        # resubmitting any stuck build on DEV no matter the state
        if module.state not in (models.BUILD_STATES['failed'],
                                models.BUILD_STATES['init']):
            err_msg = ('Module (state=%s) already exists. '
                      'Only new build or resubmission of build in "init" or '
                      '"failed" state is allowed.' % module.state)
            log.error(err_msg)
            raise Conflict(err_msg)
        log.debug('Resuming existing module build %r' % module)
        module.username = username
        module.transition(conf, models.BUILD_STATES["init"],
                          "Resubmitted by %s" % username)
        module.batch = 0
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
            modulemd=yaml,
            scmurl=url,
            username=username,
            **(optional_params or {})
        )

    record_component_builds(scm, mmd, module)

    module.modulemd = mmd.dumps()
    module.transition(conf, models.BUILD_STATES["wait"])
    db.session.add(module)
    db.session.commit()
    log.info("%s submitted build of %s, stream=%s, version=%s", username,
             mmd.name, mmd.stream, mmd.version)
    return module


def validate_optional_params(params):
    forbidden_params = [k for k in params if k not in models.ModuleBuild.__table__.columns and k not in ["branch"]]
    if forbidden_params:
        raise ValidationError('The request contains unspecified parameters: {}'.format(", ".join(forbidden_params)))

    forbidden_params = [k for k in params if k.startswith("copr_")]
    if conf.system != "copr" and forbidden_params:
        raise ValidationError('The request contains parameters specific to Copr builder: {} even though {} is used'
                              .format(", ".join(forbidden_params), conf.system))


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
    mmd = module.mmd()
    # Find the latest module that is in the done or ready state
    previous_module_build = session.query(models.ModuleBuild)\
        .filter_by(name=mmd.name)\
        .filter(models.ModuleBuild.state.in_([3, 5]))\
        .order_by(models.ModuleBuild.time_completed.desc())\
        .first()
    # The component can't be reused if there isn't a previous build in the done
    # or ready state
    if not previous_module_build:
        log.info("Cannot re-use.  %r is the first module build." % module)
        return None

    old_mmd = previous_module_build.mmd()

    # Perform a sanity check to make sure that the buildrequires are the same
    # as the buildrequires in xmd for the passed in mmd
    if mmd.buildrequires.keys() != mmd.xmd['mbs']['buildrequires'].keys():
        log.error(
            'The submitted module "{0}" has different keys in mmd.buildrequires'
            ' than in mmd.xmd[\'mbs\'][\'buildrequires\']'.format(mmd.name))
        return None
    # Perform a sanity check to make sure that the buildrequires are the same
    # as the buildrequires in xmd for the mmd of the previous module build
    if old_mmd.buildrequires.keys() != \
            old_mmd.xmd['mbs']['buildrequires'].keys():
        log.error(
            'Version "{0}" of the module "{1}" has different keys in '
            'mmd.buildrequires than in mmd.xmd[\'mbs\'][\'buildrequires\']'
            .format(previous_module_build.version, previous_module_build.name))
        return None

    # If the module buildrequires are different, then we can't reuse the
    # component
    if mmd.buildrequires.keys() != old_mmd.buildrequires.keys():
        return None

    # Make sure that the module buildrequires commit hashes are exactly the same
    for br_module_name, br_module in \
            mmd.xmd['mbs']['buildrequires'].items():
        # Assumes that the streams have been replaced with commit hashes, so we
        # can compare to see if they have changed. Since a build is unique to
        # a commit hash, this is a safe test.
        if br_module['ref'] != \
                old_mmd.xmd['mbs']['buildrequires'][br_module_name]['ref']:
            return None

    # At this point we've determined that both module builds depend(ed) on the
    # same exact module builds. Now it's time to determine if the batch of the
    # components have changed
    #
    # If the chosen component for some reason was not found in the database,
    # or the ref is missing, something has gone wrong and the component cannot
    # be reused
    new_module_build_component = models.ComponentBuild.from_component_name(
        session, component_name, module.id)
    if not new_module_build_component or not new_module_build_component.batch \
            or not new_module_build_component.ref:
        return None

    prev_module_build_component = models.ComponentBuild.from_component_name(
        session, component_name, previous_module_build.id)
    # If the component to reuse for some reason was not found in the database,
    # or the ref is missing, something has gone wrong and the component cannot
    # be reused
    if not prev_module_build_component or not prev_module_build_component.batch\
            or not prev_module_build_component.ref:
        return None

    # Make sure the batch number for the component that is trying to be reused
    # hasn't changed since the last build
    if prev_module_build_component.batch != new_module_build_component.batch:
        return None

    # Make sure the ref for the component that is trying to be reused
    # hasn't changed since the last build
    if prev_module_build_component.ref != new_module_build_component.ref:
        return None

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
    # Each batch entry will contain a list of dicts with the name and ref
    # (commit) of the component.
    for i in range(new_module_build_component.batch - 1):
        # This is the first batch which we want to skip since it will always
        # contain only the module-build-macros RPM and it gets built every time
        if i == 0:
            continue

        new_module_build_components.append([
            {'name': value.package, 'ref': value.ref} for value in
            new_component_builds if value.batch == i + 1
        ])

        previous_module_build_components.append([
            {'name': value.package, 'ref': value.ref} for value in
            prev_component_builds if value.batch == i + 1
        ])

    # If the previous batches have the same ordering and hashes, then the
    # component can be reused
    if previous_module_build_components == new_module_build_components:
        reusable_component = models.ComponentBuild.query.filter_by(
            package=component_name, module_id=previous_module_build.id).one()
        return reusable_component

    return None


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
