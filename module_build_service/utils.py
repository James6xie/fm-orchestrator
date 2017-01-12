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

import modulemd

from flask import request, url_for
from datetime import datetime

from module_build_service import log, models
from module_build_service.errors import ValidationError, UnprocessableEntity
from module_build_service import conf, db
from module_build_service.errors import (Unauthorized, Conflict)
import module_build_service.messaging
from multiprocessing.dummy import Pool as ThreadPool


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


def start_build_batch(config, module, session, builder, components=None):
    """
    Starts a round of the build cycle for a module.

    Returns list of BaseMessage instances which should be scheduled by the
    scheduler.
    """
    import koji  # Placed here to avoid py2/py3 conflicts...

    if any([c.state == koji.BUILD_STATES['BUILDING']
            for c in module.component_builds]):
        raise ValueError("Cannot start a batch when another is in flight.")

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

    for c in unbuilt_components:
        if at_concurrent_component_threshold(config, session):
            log.info('Concurrent build threshold met')
            break

        try:
            c.task_id, c.state, c.state_reason, c.nvr = builder.build(
                artifact_name=c.package, source=c.scmurl)
        except Exception as e:
            c.state = koji.BUILD_STATES['FAILED']
            c.state_reason = "Failed to submit artifact %s to Koji: %s" % (c.package, str(e))
            continue

        if not c.task_id and c.state == koji.BUILD_STATES['BUILDING']:
            c.state = koji.BUILD_STATES['FAILED']
            c.state_reason = "Failed to submit artifact %s to Koji" % (c.package)
            continue

    further_work = []

    # If all components in this batch are already done, it can mean that they
    # have been built in the past and have been skipped in this module build.
    # We therefore have to generate fake KojiRepoChange message, because the
    # repo has been also done in the past and build system will not send us
    # any message now.
    if (all(c.state == koji.BUILD_STATES['COMPLETE'] for c in unbuilt_components)
            and builder.module_build_tag):
        further_work += [module_build_service.messaging.KojiRepoChange(
            'start_build_batch: fake msg', builder.module_build_tag['name'])]

    session.commit()
    return further_work

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


def _fetch_mmd(url, allow_local_url = False):
    # Import it here, because SCM uses utils methods
    # and fails to import them because of dep-chain.
    import module_build_service.scm

    yaml = ""
    td = None
    scm = None
    try:
        log.debug('Verifying modulemd')
        td = tempfile.mkdtemp()
        scm = module_build_service.scm.SCM(url, conf.scmurls, allow_local_url)
        cod = scm.checkout(td)
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

    mmd = modulemd.ModuleMetadata()
    try:
        mmd.loads(yaml)
    except Exception as e:
        log.error('Invalid modulemd: %s' % str(e))
        raise UnprocessableEntity('Invalid modulemd: %s' % str(e))

    # If undefined, set the name field to VCS repo name.
    if not mmd.name and scm:
        mmd.name = scm.name

    # If undefined, set the stream field to the VCS branch name.
    if not mmd.stream and scm:
        mmd.stream = scm.branch

    # If undefined, set the version field to int represenation of VCS commit.
    if not mmd.version and scm:
        mmd.version = int(scm.version)

    return mmd, scm, yaml

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

def record_component_builds(scm, mmd, module, initial_batch = 1):
    # Import it here, because SCM uses utils methods
    # and fails to import them because of dep-chain.
    import module_build_service.scm

    # List of (pkg_name, git_url) tuples to be used to check
    # the availability of git URLs paralelly later.
    full_urls = []

    # If the modulemd yaml specifies components, then submit them for build
    if mmd.components:
        # Add missing data in components
        for pkgname, pkg in mmd.components.rpms.items():
            try:
                if pkg.repository and not conf.rpms_allow_repository:
                    raise Unauthorized(
                        "Custom component repositories aren't allowed")
                if pkg.cache and not conf.rpms_allow_cache:
                    raise Unauthorized("Custom component caches aren't allowed")
                if not pkg.repository:
                    pkg.repository = conf.rpms_default_repository + pkgname
                if not pkg.cache:
                    pkg.cache = conf.rpms_default_cache + pkgname
                if not pkg.ref:
                    pkg.ref = 'master'
            except Exception:
                module.transition(conf, models.BUILD_STATES["failed"])
                db.session.add(module)
                db.session.commit()
                raise

        # Check that SCM URL is valid and replace potential branches in
        # pkg.ref by real SCM hash.
        pool = ThreadPool(20)
        err_msgs = pool.map(_scm_get_latest, mmd.components.rpms.values())
        # TODO: only the first error message is raised, perhaps concatenate
        # the messages together?
        for err_msg in err_msgs:
            if err_msg:
                raise UnprocessableEntity(err_msg)

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
                if not pkg.repository:
                    pkg.repository = scm.scm_url_from_name(pkg.name)
                full_url = pkg.repository + "?#" + pkg.ref
                mmd = _fetch_mmd(full_url)[0]
                batch = record_component_builds(scm, mmd, module, batch)
                continue

            if previous_buildorder != pkg.buildorder:
                previous_buildorder = pkg.buildorder
                batch += 1

            full_url = pkg.repository + "?#" + pkg.ref

            existing_build = models.ComponentBuild.query.filter_by(
                module_id=module.id, package=pkg.name).first()
            if (existing_build and existing_build.state != models.BUILD_STATES['done']):
                existing_build.state = models.BUILD_STATES['init']
                db.session.add(existing_build)
            else:
                # XXX: what about components that were present in previous
                # builds but are gone now (component reduction)?
                build = models.ComponentBuild(
                    module_id=module.id,
                    package=pkg.name,
                    format="rpms",
                    scmurl=full_url,
                    batch=batch
                )
                db.session.add(build)

        return batch

def submit_module_build(username, url, allow_local_url = False):
    # Import it here, because SCM uses utils methods
    # and fails to import them because of dep-chain.
    import module_build_service.scm

    mmd, scm, yaml = _fetch_mmd(url, allow_local_url)

    module = models.ModuleBuild.query.filter_by(name=mmd.name,
                                                stream=mmd.stream,
                                                version=mmd.version).first()
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
        module.transition(conf, models.BUILD_STATES["init"])
        log.info("Resumed existing module build in previous state %s"
                 % module.state)
    else:
        log.debug('Creating new module build')
        module = models.ModuleBuild.create(
            db.session,
            conf,
            name=mmd.name,
            stream=mmd.stream,
            version=mmd.version,
            modulemd=yaml,
            scmurl=url,
            username=username
        )

    record_component_builds(scm, mmd, module)

    module.modulemd = mmd.dumps()
    module.transition(conf, models.BUILD_STATES["wait"])
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

def module_build_state_from_msg(msg):
    state = int(msg.module_build_state)
    # TODO better handling
    assert state in models.BUILD_STATES.values(), (
        'state=%s(%s) is not in %s'
        % (state, type(state), list(models.BUILD_STATES.values())))
    return state
