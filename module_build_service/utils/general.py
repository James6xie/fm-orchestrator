# -*- coding: utf-8 -*-
# Copyright (c) 2018  Red Hat, Inc.
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
#            Jan Kaluza <jkaluza@redhat.com>
import functools
import inspect
import hashlib
import time
from datetime import datetime

from module_build_service import conf, log, models
from module_build_service.errors import (
    ValidationError, ProgrammingError, UnprocessableEntity)


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


def retry(timeout=conf.net_timeout, interval=conf.net_retry_interval, wait_on=Exception):
    """ A decorator that allows to retry a section of code...
    ...until success or timeout.
    """
    def wrapper(function):
        @functools.wraps(function)
        def inner(*args, **kwargs):
            start = time.time()
            while True:
                try:
                    return function(*args, **kwargs)
                except wait_on as e:
                    log.warn("Exception %r raised from %r.  Retry in %rs" % (
                        e, function, interval))
                    time.sleep(interval)
                    if (time.time() - start) >= timeout:
                        raise  # This re-raises the last exception.
        return inner
    return wrapper


def module_build_state_from_msg(msg):
    state = int(msg.module_build_state)
    # TODO better handling
    assert state in models.BUILD_STATES.values(), (
        'state=%s(%s) is not in %s'
        % (state, type(state), list(models.BUILD_STATES.values())))
    return state


def generate_koji_tag(name, stream, version, context, max_length=256):
    """
    Generate a koji tag from name, stream, version and context.

    :param name: a module's name
    :param stream: a module's stream
    :param version: a module's version
    :param context: a module's context
    :kwarg max_length: the maximum length the Koji tag can be before falling back to
    the old format of "module-<hash>"
    :return: a Koji tag
    """
    nsvc_list = [name, stream, str(version), context]
    nsvc_tag = 'module-' + '-'.join(nsvc_list)
    if len(nsvc_tag) + len('-build') > max_length:
        # Fallback to the old format of 'module-<hash>' if the generated koji tag
        # name is longer than max_length
        nsvc_hash = hashlib.sha1('.'.join(nsvc_list)).hexdigest()[:16]
        return 'module-' + nsvc_hash
    return nsvc_tag


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


def get_rpm_release(module_build):
    """
    Generates the dist tag for the specified module
    :param module_build: a models.ModuleBuild object
    :return: a string of the module's dist tag
    """
    dist_str = '.'.join([module_build.name, module_build.stream, str(module_build.version),
                         str(module_build.context)]).encode('utf-8')
    dist_hash = hashlib.sha1(dist_str).hexdigest()[:8]

    # We need to share the same auto-incrementing index in dist tag between all MSE builds.
    # We can achieve that by using the lowest build ID of all the MSE siblings including
    # this module build.
    mse_build_ids = module_build.siblings + [module_build.id or 0]
    mse_build_ids.sort()
    index = mse_build_ids[0]
    return "{prefix}{index}+{dist_hash}".format(
        prefix=conf.default_dist_tag_prefix,
        index=index,
        dist_hash=dist_hash,
    )


def create_dogpile_key_generator_func(skip_first_n_args=0):
    """
    Creates dogpile key_generator function with additional features:

    - when models.ModuleBuild is an argument of method cached by dogpile-cache,
      the ModuleBuild.id is used as a key. Therefore it is possible to cache
      data per particular module build, while normally, it would be per
      ModuleBuild.__str__() output, which contains also batch and other data
      which changes during the build of a module.
    - it is able to skip first N arguments of a cached method. This is useful
      when the db.session is part of cached method call, and the caching should
      work no matter what session instance is passed to cached method argument.
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


def import_mmd(session, mmd):
    """
    Imports new module build defined by `mmd` to MBS database using `session`.
    If it already exists, it is updated.

    The ModuleBuild.koji_tag is set according to xmd['mbs]['koji_tag'].
    The ModuleBuild.state is set to "ready".
    The ModuleBuild.rebuild_strategy is set to "all".
    The ModuleBuild.owner is set to "mbs_import".

    TODO: The "context" is not stored directly in database. We only store
    build_context and runtime_context and compute context, but when importing
    the module, we have no idea what build_context or runtime_context is - we only
    know the resulting "context", but there is no way to store it into do DB.
    By now, we just ignore mmd.get_context() and use default 00000000 context instead.

    :return: module build (ModuleBuild),
             log messages collected during import (list)
    :rtype: tuple
    """
    mmd.set_context(models.DEFAULT_MODULE_CONTEXT)
    name = mmd.get_name()
    stream = mmd.get_stream()
    version = str(mmd.get_version())
    context = mmd.get_context()

    # Log messages collected during import
    msgs = []

    # NSVC is used for logging purpose later.
    try:
        nsvc = ":".join([name, stream, version, context])
    except TypeError:
        msg = "Incomplete NSVC: {}:{}:{}:{}".format(name, stream, version, context)
        log.error(msg)
        raise UnprocessableEntity(msg)

    # Get the koji_tag.
    try:
        xmd = mmd.get_xmd()
        koji_tag = xmd["mbs"]["koji_tag"]
    except KeyError:
        msg = "'koji_tag' is not set in xmd['mbs'] for module {}".format(nsvc)
        log.error(msg)
        raise UnprocessableEntity(msg)

    # Get the ModuleBuild from DB.
    build = models.ModuleBuild.get_build_from_nsvc(
        session, name, stream, version, context)
    if build:
        msg = "Updating existing module build {}.".format(nsvc)
        log.info(msg)
        msgs.append(msg)
    else:
        build = models.ModuleBuild()

    build.name = name
    build.stream = stream
    build.version = version
    build.koji_tag = koji_tag
    build.state = models.BUILD_STATES['ready']
    build.modulemd = mmd.dumps()
    build.context = context
    build.owner = "mbs_import"
    build.rebuild_strategy = 'all'
    build.time_submitted = datetime.utcnow()
    build.time_modified = datetime.utcnow()
    build.time_completed = datetime.utcnow()
    session.add(build)
    session.commit()
    msg = "Module {} imported".format(nsvc)
    log.info(msg)
    msgs.append(msg)

    return build, msgs


def get_mmd_from_scm(url):
    """
    Provided an SCM URL, fetch mmd from the corresponding module YAML
    file. If ref is specified within the URL, the mmd will be returned
    as of the ref.
    """
    from module_build_service.utils.submit import _fetch_mmd

    mmd, _ = _fetch_mmd(url, branch=None, allow_local_url=False,
                        whitelist_url=False, mandatory_checks=False)

    return mmd
