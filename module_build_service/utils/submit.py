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
import json
import re
import time
import shutil
import tempfile
import os
from multiprocessing.dummy import Pool as ThreadPool
from datetime import datetime
import copy
from module_build_service.utils import to_text_type

import kobo.rpmlib
import requests
from gi.repository import GLib

import module_build_service.scm
import module_build_service.resolver

from module_build_service import conf, db, log, models, Modulemd
from module_build_service.errors import (
    ValidationError, UnprocessableEntity, Forbidden, Conflict)
from module_build_service import glib
from module_build_service.resolver import GenericResolver
from .mse import generate_expanded_mmds


def record_filtered_rpms(mmd):
    """Record filtered RPMs that should not be installed into buildroot

    These RPMs are filtered:

    * Reads the mmd["xmd"]["buildrequires"] and extends it with "filtered_rpms"
      list containing the NVRs of filtered RPMs in a buildrequired module.

    :param Modulemd mmd: Modulemd that will be built next.
    :rtype: Modulemd.Module
    :return: Modulemd extended with the "filtered_rpms" in XMD section.
    """
    # Imported here to allow import of utils in GenericBuilder.
    from module_build_service.builder import GenericBuilder

    resolver = GenericResolver.create(conf)
    builder = GenericBuilder.backends[conf.system]

    new_buildrequires = {}
    for req_name, req_data in mmd.get_xmd()["mbs"]["buildrequires"].items():
        # In case this is module resubmit or local build, the filtered_rpms
        # will already be there, so there is no point in generating them again.
        if "filtered_rpms" in req_data:
            new_buildrequires[req_name] = req_data
            continue

        # We can just get the first modulemd data from result right here thanks to
        # strict=True, so in case the module cannot be found, get_module_modulemds
        # raises an exception.
        req_mmd = resolver.get_module_modulemds(
            req_name, req_data["stream"], req_data["version"], req_data["context"], True)[0]

        # Find out the particular NVR of filtered packages
        filtered_rpms = []
        rpm_filter = req_mmd.get_rpm_filter()
        if rpm_filter and rpm_filter.get():
            rpm_filter = rpm_filter.get()
            built_nvrs = builder.get_built_rpms_in_module_build(req_mmd)
            for nvr in built_nvrs:
                parsed_nvr = kobo.rpmlib.parse_nvr(nvr)
                if parsed_nvr["name"] in rpm_filter:
                    filtered_rpms.append(nvr)
        req_data["filtered_rpms"] = filtered_rpms

        new_buildrequires[req_name] = req_data

    # Replace the old buildrequires with new ones.
    xmd = glib.from_variant_dict(mmd.get_xmd())
    xmd["mbs"]["buildrequires"] = new_buildrequires
    mmd.set_xmd(glib.dict_values(xmd))
    return mmd


def _scm_get_latest(pkg):
    try:
        # If the modulemd specifies that the 'f25' branch is what
        # we want to pull from, we need to resolve that f25 branch
        # to the specific commit available at the time of
        # submission (now).
        pkgref = module_build_service.scm.SCM(
            pkg.get_repository()).get_latest(pkg.get_ref())
    except Exception as e:
        log.exception(e)
        return {'error': "Failed to get the latest commit for %s#%s" % (
            pkg.get_repository(), pkg.get_ref())}

    return {
        'pkg_name': pkg.get_name(),
        'pkg_ref': pkgref,
        'error': None
    }


def format_mmd(mmd, scmurl, module=None, session=None):
    """
    Prepares the modulemd for the MBS. This does things such as replacing the
    branches of components with commit hashes and adding metadata in the xmd
    dictionary.
    :param mmd: the Modulemd.Module object to format
    :param scmurl: the url to the modulemd
    :param module: When specified together with `session`, the time_modified
        of a module is updated regularly in case this method takes lot of time.
    :param session: Database session to update the `module`.
    """
    # Import it here, because SCM uses utils methods and fails to import
    # them because of dep-chain.
    from module_build_service.scm import SCM

    xmd = glib.from_variant_dict(mmd.get_xmd())
    if 'mbs' not in xmd:
        xmd['mbs'] = {}
    if 'scmurl' not in xmd['mbs']:
        xmd['mbs']['scmurl'] = scmurl or ''
    if 'commit' not in xmd['mbs']:
        xmd['mbs']['commit'] = ''

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

            xmd['mbs']['commit'] = full_scm_hash
        # If a commit hash wasn't provided then just get the latest from master
        else:
            xmd['mbs']['commit'] = scm.get_latest()

    if mmd.get_rpm_components() or mmd.get_module_components():
        if 'rpms' not in xmd['mbs']:
            xmd['mbs']['rpms'] = {}
        # Add missing data in RPM components
        for pkgname, pkg in mmd.get_rpm_components().items():
            # In case of resubmit of existing module which have been
            # cancelled/failed during the init state, the package
            # was maybe already handled by MBS, so skip it in this case.
            if pkgname in xmd['mbs']['rpms']:
                continue
            if pkg.get_repository() and not conf.rpms_allow_repository:
                raise Forbidden(
                    "Custom component repositories aren't allowed.  "
                    "%r bears repository %r" % (pkgname, pkg.get_repository()))
            if pkg.get_cache() and not conf.rpms_allow_cache:
                raise Forbidden(
                    "Custom component caches aren't allowed.  "
                    "%r bears cache %r" % (pkgname, pkg.cache))
            if not pkg.get_repository():
                pkg.set_repository(conf.rpms_default_repository + pkgname)
            if not pkg.get_cache():
                pkg.set_cache(conf.rpms_default_cache + pkgname)
            if not pkg.get_ref():
                pkg.set_ref('master')
            if pkg.get_arches().size() == 0:
                arches = Modulemd.SimpleSet()
                arches.set(conf.arches)
                pkg.set_arches(arches)

        # Add missing data in included modules components
        for modname, mod in mmd.get_module_components().items():
            if mod.get_repository() and not conf.modules_allow_repository:
                raise Forbidden(
                    "Custom module repositories aren't allowed.  "
                    "%r bears repository %r" % (modname, mod.get_repository()))
            if not mod.get_repository():
                mod.set_repository(conf.modules_default_repository + modname)
            if not mod.get_ref():
                mod.set_ref('master')

        # Check that SCM URL is valid and replace potential branches in pkg refs
        # by real SCM hash and store the result to our private xmd place in modulemd.
        pool = ThreadPool(20)
        try:
            # Filter out the packages which we have already resolved in possible
            # previous runs of this method (can be caused by module build resubmition).
            pkgs_to_resolve = [pkg for pkg in mmd.get_rpm_components().values()
                               if pkg.get_name() not in xmd['mbs']['rpms']]
            async_result = pool.map_async(_scm_get_latest, pkgs_to_resolve)

            # For modules with lot of components, the _scm_get_latest can take a lot of time.
            # We need to bump time_modified from time to time, otherwise poller could think
            # that module is stuck in "init" state and it would send fake "init" message.
            while not async_result.ready():
                async_result.wait(60)
                if module and session:
                    module.time_modified = datetime.utcnow()
                    session.commit()
            pkg_dicts = async_result.get()
        finally:
            pool.close()

        err_msg = ""
        for pkg_dict in pkg_dicts:
            if pkg_dict["error"]:
                err_msg += pkg_dict["error"] + "\n"
            else:
                pkg_name = pkg_dict["pkg_name"]
                pkg_ref = pkg_dict["pkg_ref"]
                xmd['mbs']['rpms'][pkg_name] = {'ref': pkg_ref}
        if err_msg:
            raise UnprocessableEntity(err_msg)

    # Set the modified xmd back to the modulemd
    mmd.set_xmd(glib.dict_values(xmd))


def get_prefixed_version(mmd):
    """
    Return the prefixed version of the module based on the buildrequired base module stream.

    :param mmd: the Modulemd.Module object to format
    :return: the prefixed version
    :rtype: int
    """
    xmd = mmd.get_xmd()
    version = mmd.get_version()

    base_module_stream = None
    for base_module in conf.base_module_names:
        # xmd is a GLib Variant and doesn't support .get() syntax
        try:
            base_module_stream = xmd['mbs']['buildrequires'].get(
                base_module, {}).get('stream')
            if base_module_stream:
                # Break after finding the first base module that is buildrequired
                break
        except KeyError:
            log.warning('The module\'s mmd is missing information in the xmd section')
            return version
    else:
        log.warning('This module does not buildrequire a base module ({0})'
                    .format(' or '.join(conf.base_module_names)))
        return version

    # The platform version (e.g. prefix1.2.0 => 010200)
    version_prefix = models.ModuleBuild.get_stream_version(base_module_stream, right_pad=False)

    if not version_prefix:
        log.warning('The "{0}" stream "{1}" couldn\'t be used to prefix the module\'s '
                    'version'.format(base_module, base_module_stream))
        return version

    new_version = int(str(version_prefix) + str(version))
    if new_version > GLib.MAXUINT64:
        log.warning('The "{0}" stream "{1}" caused the module\'s version prefix to be '
                    'too long'.format(base_module, base_module_stream))
        return version
    return new_version


def validate_mmd(mmd):
    """Validate module metadata

    If everything is ok, just keep quiet, otherwise error is raised for
    specific problem.

    :param mmd: modulemd object representing module metadata.
    :type mmd: Modulemd.Module
    :raises Forbidden: if metadata contains module repository but it is not
        allowed.
    """
    for modname, mod in mmd.get_module_components().items():
        if mod.get_repository() and not conf.modules_allow_repository:
            raise Forbidden(
                "Custom module repositories aren't allowed.  "
                "%r bears repository %r" % (modname, mod.get_repository()))


def merge_included_mmd(mmd, included_mmd):
    """
    Merges two modulemds. This merges only metadata which are needed in
    the `main` when it includes another module defined by `included_mmd`
    """
    included_xmd = glib.from_variant_dict(included_mmd.get_xmd())
    if 'rpms' in included_xmd['mbs']:
        xmd = glib.from_variant_dict(mmd.get_xmd())
        if 'rpms' not in xmd['mbs']:
            xmd['mbs']['rpms'] = included_xmd['mbs']['rpms']
        else:
            xmd['mbs']['rpms'].update(included_xmd['mbs']['rpms'])
    # Set the modified xmd back to the modulemd
    mmd.set_xmd(glib.dict_values(xmd))


def get_module_srpm_overrides(module):
    """
    Make necessary preparations to use any provided custom SRPMs.

    :param module: ModuleBuild object representing the module being submitted.
    :type module: :class:`models.ModuleBuild`
    :return: mapping of package names to SRPM links for all packages which
             have custom SRPM overrides specified
    :rtype: dict[str, str]

    """
    overrides = {}

    if not module.srpms:
        return overrides

    try:
        # Make sure we can decode the custom SRPM list
        srpms = json.loads(module.srpms)
        assert isinstance(srpms, list)
    except Exception:
        raise ValueError("Invalid srpms list encountered: {}".format(module.srpms))

    for source in srpms:
        if source.startswith('cli-build/') and source.endswith('.src.rpm'):
            # This is a custom srpm that has been uploaded to koji by rpkg
            # using the package name as the basename suffixed with .src.rpm
            rpm_name = os.path.basename(source)[:-len('.src.rpm')]
        else:
            # This should be a local custom srpm path
            if not os.path.exists(source):
                raise IOError("Provided srpm is missing: {}".format(source))
            # Get package name from rpm headers
            try:
                rpm_hdr = kobo.rpmlib.get_rpm_header(source)
                rpm_name = kobo.rpmlib.get_header_field(rpm_hdr, 'name').decode('utf-8')
            except Exception:
                raise ValueError("Provided srpm is invalid: {}".format(source))

        if rpm_name in overrides:
            log.warning('Encountered duplicate custom SRPM "{0}"'
                        ' for package {1}'.format(source, rpm_name))
            continue

        log.debug('Using custom SRPM "{0}" for package {1}'.format(source, rpm_name))
        overrides[rpm_name] = source

    return overrides


def record_component_builds(mmd, module, initial_batch=1,
                            previous_buildorder=None, main_mmd=None, session=None):
    # Imported here to allow import of utils in GenericBuilder.
    import module_build_service.builder

    if not session:
        session = db.session

    # Format the modulemd by putting in defaults and replacing streams that
    # are branches with commit hashes
    format_mmd(mmd, module.scmurl, module, session)

    # When main_mmd is set, merge the metadata from this mmd to main_mmd,
    # otherwise our current mmd is main_mmd.
    if main_mmd:
        # Check for components that are in both MMDs before merging since MBS
        # currently can't handle that situation.
        duplicate_components = [rpm for rpm in main_mmd.get_rpm_components().keys()
                                if rpm in mmd.get_rpm_components()]
        if duplicate_components:
            error_msg = (
                'The included module "{0}" in "{1}" have the following '
                'conflicting components: {2}'.format(
                    mmd.get_name(), main_mmd.get_name(), ', '.join(duplicate_components)))
            raise UnprocessableEntity(error_msg)
        merge_included_mmd(main_mmd, mmd)
    else:
        main_mmd = mmd

    # If the modulemd yaml specifies components, then submit them for build
    rpm_components = mmd.get_rpm_components().values()
    module_components = mmd.get_module_components().values()
    all_components = list(rpm_components) + list(module_components)
    if not all_components:
        return

    # Get map of packages that have SRPM overrides
    srpm_overrides = get_module_srpm_overrides(module)

    rpm_weights = module_build_service.builder.GenericBuilder.get_build_weights(
        [c.get_name() for c in rpm_components])
    all_components.sort(key=lambda x: x.get_buildorder())
    # We do not start with batch = 0 here, because the first batch is
    # reserved for module-build-macros. First real components must be
    # planned for batch 2 and following.
    batch = initial_batch

    for component in all_components:
        # Increment the batch number when buildorder increases.
        if previous_buildorder != component.get_buildorder():
            previous_buildorder = component.get_buildorder()
            batch += 1

        # If the component is another module, we fetch its modulemd file
        # and record its components recursively with the initial_batch
        # set to our current batch, so the components of this module
        # are built in the right global order.
        if isinstance(component, Modulemd.ComponentModule):
            full_url = component.get_repository() + "?#" + component.get_ref()
            # It is OK to whitelist all URLs here, because the validity
            # of every URL have been already checked in format_mmd(...).
            included_mmd = _fetch_mmd(full_url, whitelist_url=True)[0]
            batch = record_component_builds(included_mmd, module, batch,
                                            previous_buildorder, main_mmd, session=session)
            continue

        package = component.get_name()
        if package in srpm_overrides:
            component_ref = None
            full_url = srpm_overrides[package]
            log.info('Building custom SRPM "{0}"'
                     ' for package {1}'.format(full_url, package))
        else:
            component_ref = mmd.get_xmd()['mbs']['rpms'][package]['ref']
            full_url = component.get_repository() + "?#" + component_ref

        # Skip the ComponentBuild if it already exists in database. This can happen
        # in case of module build resubmition.
        existing_build = models.ComponentBuild.from_component_name(
            db.session, package, module.id)
        if existing_build:
            # Check that the existing build has the same most important attributes.
            # This should never be a problem, but it's good to be defensive here so
            # we do not mess things during resubmition.
            if (existing_build.batch != batch or existing_build.scmurl != full_url or
                    existing_build.ref != component_ref):
                raise ValidationError(
                    "Module build %s already exists in database, but its attributes "
                    " are different from resubmitted one." % component.get_name())
            continue

        build = models.ComponentBuild(
            module_id=module.id,
            package=package,
            format="rpms",
            scmurl=full_url,
            batch=batch,
            ref=component_ref,
            weight=rpm_weights[package]
        )
        session.add(build)

    return batch


def submit_module_build_from_yaml(username, handle, params, stream=None, skiptests=False):
    yaml_file = to_text_type(handle.read())
    mmd = load_mmd(yaml_file)
    dt = datetime.utcfromtimestamp(int(time.time()))
    if hasattr(handle, 'filename'):
        def_name = str(os.path.splitext(os.path.basename(handle.filename))[0])
    elif not mmd.get_name():
        raise ValidationError(
            "The module's name was not present in the modulemd file. Please use the "
            "\"module_name\" parameter")
    def_version = int(dt.strftime("%Y%m%d%H%M%S"))
    mmd.set_name(mmd.get_name() or def_name)
    mmd.set_stream(stream or mmd.get_stream() or "master")
    mmd.set_version(mmd.get_version() or def_version)
    if skiptests:
        buildopts = mmd.get_rpm_buildopts()
        buildopts["macros"] = buildopts.get("macros", "") + "\n\n%__spec_check_pre exit 0\n"
        mmd.set_rpm_buildopts(buildopts)
    return submit_module_build(username, mmd, params)


_url_check_re = re.compile(r"^[^:/]+:.*$")


def submit_module_build_from_scm(username, params, allow_local_url=False):
    url = params['scmurl']
    branch = params['branch']
    # Translate local paths into file:// URL
    if allow_local_url and not _url_check_re.match(url):
        log.info(
            "'{}' is not a valid URL, assuming local path".format(url))
        url = os.path.abspath(url)
        url = "file://" + url
    mmd, scm = _fetch_mmd(url, branch, allow_local_url)

    return submit_module_build(username, mmd, params)


def _apply_dep_overrides(mmd, params):
    """
    Apply the dependency override parameters (if specified) on the input modulemd.

    :param Modulemd.Module mmd: the modulemd to apply the overrides on
    :param dict params: the API parameters passed in by the user
    :raises ValidationError: if one of the overrides doesn't apply
    """
    dep_overrides = {
        'buildrequires': copy.copy(params.get('buildrequire_overrides', {})),
        'requires': copy.copy(params.get('require_overrides', {}))
    }

    # Parse the module's branch to determine if it should override the stream of the buildrequired
    # module defined in conf.br_stream_override_module
    branch_search = None
    if params.get('branch') and conf.br_stream_override_module and conf.br_stream_override_regexes:
        # Only parse the branch for a buildrequire override if the user didn't manually specify an
        # override for the module specified in conf.br_stream_override_module
        if not dep_overrides['buildrequires'].get(conf.br_stream_override_module):
            branch_search = None
            for regex in conf.br_stream_override_regexes:
                branch_search = re.search(regex, params['branch'])
                if branch_search:
                    log.debug(
                        'The stream override regex `%s` matched the branch %s',
                        regex, params['branch'])
                    break
            else:
                log.debug('No stream override regexes matched the branch "%s"', params['branch'])

    # If a stream was parsed from the branch, then add it as a stream override for the module
    # specified in conf.br_stream_override_module
    if branch_search:
        # Concatenate all the groups that are not None together to get the desired stream.
        # This approach is taken in case there are sections to ignore.
        # For instance, if we need to parse `el8.0.0` from `rhel-8.0.0`.
        parsed_stream = ''.join(group for group in branch_search.groups() if group)
        if parsed_stream:
            dep_overrides['buildrequires'][conf.br_stream_override_module] = [parsed_stream]
            log.info(
                'The buildrequired stream of "%s" was overriden with "%s" based on the branch "%s"',
                conf.br_stream_override_module, parsed_stream, params['branch'])
        else:
            log.warning(
                ('The regex `%s` only matched empty capture groups on the branch "%s". The regex '
                 'is invalid and should be rewritten.'),
                regex, params['branch'])

    unused_dep_overrides = {
        'buildrequires': set(dep_overrides['buildrequires'].keys()),
        'requires': set(dep_overrides['requires'].keys())
    }

    deps = mmd.get_dependencies()
    for dep in deps:
        for dep_type, overrides in dep_overrides.items():
            overridden = False
            # Get the existing streams (e.g. dep.get_buildrequires())
            reqs = getattr(dep, 'get_' + dep_type)()
            for name, streams in dep_overrides[dep_type].items():
                if name in reqs:
                    reqs[name].set(streams)
                    unused_dep_overrides[dep_type].remove(name)
                    overridden = True
            if overridden:
                # Set the overridden streams (e.g. dep.set_buildrequires(reqs))
                getattr(dep, 'set_' + dep_type)(reqs)

    for dep_type in unused_dep_overrides.keys():
        # If a stream override was applied from parsing the branch and it wasn't applicable,
        # just ignore it
        if branch_search and conf.br_stream_override_module in unused_dep_overrides[dep_type]:
            unused_dep_overrides[dep_type].remove(conf.br_stream_override_module)
        if unused_dep_overrides[dep_type]:
            raise ValidationError(
                'The {} overrides for the following modules aren\'t applicable: {}'
                .format(dep_type[:-1], ', '.join(sorted(unused_dep_overrides[dep_type]))))

    mmd.set_dependencies(deps)


def submit_module_build(username, mmd, params):
    """
    Submits new module build.

    :param str username: Username of the build's owner.
    :param Modulemd.Module mmd: Modulemd defining the build.
    :param dict params: the API parameters passed in by the user
    :rtype: list with ModuleBuild
    :return: List with submitted module builds.
    """
    import koji  # Placed here to avoid py2/py3 conflicts...

    if mmd.get_name() in conf.base_module_names:
        raise ValidationError(
            'You cannot build a module named "{}" since it is a base module'.format(mmd.get_name()))

    raise_if_stream_ambigous = False
    default_streams = {}
    # For local builds, we want the user to choose the exact stream using the default_streams
    # in case there are multiple streams to choose from and raise an exception otherwise.
    if "local_build" in params:
        raise_if_stream_ambigous = True
    # Get the default_streams if set.
    if "default_streams" in params:
        default_streams = params["default_streams"]
    _apply_dep_overrides(mmd, params)

    validate_mmd(mmd)
    mmds = generate_expanded_mmds(db.session, mmd, raise_if_stream_ambigous, default_streams)
    if not mmds:
        raise ValidationError('No dependency combination was satisfied. Please verify the '
                              'buildrequires in your modulemd have previously been built.')
    modules = []

    # True if all module builds are skipped so MBS will actually not rebuild
    # anything. To keep the backward compatibility, we need to raise an exception
    # later in the end of this method.
    all_modules_skipped = True

    for mmd in mmds:
        # Prefix the version of the modulemd based on the base module it buildrequires
        version = get_prefixed_version(mmd)
        mmd.set_version(version)
        version_str = str(version)
        nsvc = ":".join([mmd.get_name(), mmd.get_stream(), version_str, mmd.get_context()])

        log.debug('Checking whether module build already exists: %s.', nsvc)
        module = models.ModuleBuild.get_build_from_nsvc(
            db.session, mmd.get_name(), mmd.get_stream(), version_str, mmd.get_context())
        if module:
            if module.state != models.BUILD_STATES['failed']:
                log.info("Skipping rebuild of %s, only rebuild of modules in failed state "
                         "is allowed.", nsvc)
                modules.append(module)
                continue

            rebuild_strategy = params.get('rebuild_strategy')
            if rebuild_strategy and module.rebuild_strategy != rebuild_strategy:
                raise ValidationError(
                    'You cannot change the module\'s "rebuild_strategy" when '
                    'resuming a module build')

            log.debug('Resuming existing module build %r' % module)
            # Reset all component builds that didn't complete
            for component in module.component_builds:
                if component.state and component.state != koji.BUILD_STATES['COMPLETE']:
                    component.state = None
                    component.state_reason = None
                    db.session.add(component)
            module.username = username
            prev_state = module.previous_non_failed_state
            if prev_state == models.BUILD_STATES['init']:
                transition_to = models.BUILD_STATES['init']
            else:
                transition_to = models.BUILD_STATES['wait']
                module.batch = 0
            module.transition(conf, transition_to, "Resubmitted by %s" % username)
            log.info("Resumed existing module build in previous state %s" % module.state)
        else:
            log.debug('Creating new module build')
            module = models.ModuleBuild.create(
                db.session,
                conf,
                name=mmd.get_name(),
                stream=mmd.get_stream(),
                version=version_str,
                modulemd=to_text_type(mmd.dumps()),
                scmurl=params.get('scmurl'),
                username=username,
                rebuild_strategy=params.get('rebuild_strategy'),
                scratch=params.get('scratch'),
                srpms=params.get('srpms')
            )
            (module.ref_build_context, module.build_context, module.runtime_context,
             module.context) = module.contexts_from_mmd(module.modulemd)

        all_modules_skipped = False
        db.session.add(module)
        db.session.commit()
        modules.append(module)
        log.info("%s submitted build of %s, stream=%s, version=%s, context=%s", username,
                 mmd.get_name(), mmd.get_stream(), version_str, mmd.get_context())

    if all_modules_skipped:
        err_msg = ('Module (state=%s) already exists. Only a new build, resubmission of '
                   'a failed build or build against new buildrequirements is '
                   'allowed.' % module.state)
        log.error(err_msg)
        raise Conflict(err_msg)

    return modules


def _is_eol_in_pdc(name, stream):
    """ Check PDC if the module name:stream is no longer active. """

    params = {'type': 'module', 'global_component': name, 'name': stream}
    url = conf.pdc_url + '/component-branches/'

    response = requests.get(url, params=params)
    if not response:
        raise ValidationError("Failed to talk to PDC {}{}".format(response, response.text))

    data = response.json()
    results = data['results']
    if not results:
        raise ValidationError("No such module {}:{} found at {}".format(
            name, stream, response.request.url))

    # If the module is active, then it is not EOL and vice versa.
    return not results[0]['active']


def _fetch_mmd(url, branch=None, allow_local_url=False, whitelist_url=False,
               mandatory_checks=True):
    # Import it here, because SCM uses utils methods
    # and fails to import them because of dep-chain.
    import module_build_service.scm

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
        if not whitelist_url and mandatory_checks:
            scm.verify()
        cofn = scm.get_module_yaml()
        mmd = load_mmd(cofn, is_file=True)
    finally:
        try:
            if td is not None:
                shutil.rmtree(td)
        except Exception as e:
            log.warning(
                "Failed to remove temporary directory {!r}: {}".format(
                    td, str(e)))

    if conf.check_for_eol:
        if _is_eol_in_pdc(scm.name, scm.branch):
            raise ValidationError(
                'Module {}:{} is marked as EOL in PDC.'.format(scm.name, scm.branch))

    if not mandatory_checks:
        return mmd, scm

    # If the name was set in the modulemd, make sure it matches what the scmurl
    # says it should be
    if mmd.get_name() and mmd.get_name() != scm.name:
        if not conf.allow_name_override_from_scm:
            raise ValidationError('The name "{0}" that is stored in the modulemd '
                                  'is not valid'.format(mmd.get_name()))
    else:
        mmd.set_name(scm.name)

    # If the stream was set in the modulemd, make sure it matches what the repo
    # branch is
    if mmd.get_stream() and mmd.get_stream() != scm.branch:
        if not conf.allow_stream_override_from_scm:
            raise ValidationError('The stream "{0}" that is stored in the modulemd '
                                  'does not match the branch "{1}"'.format(
                                      mmd.get_stream(), scm.branch))
    else:
        mmd.set_stream(scm.branch)

    # If the version is in the modulemd, throw an exception since the version
    # since the version is generated by MBS
    if mmd.get_version():
        raise ValidationError('The version "{0}" is already defined in the '
                              'modulemd but it shouldn\'t be since the version '
                              'is generated based on the commit time'.format(
                                  mmd.get_version()))
    else:
        mmd.set_version(int(scm.version))

    return mmd, scm


def load_mmd(yaml, is_file=False):
    try:
        if is_file:
            mmd = Modulemd.Module().new_from_file(yaml)
        else:
            mmd = Modulemd.Module().new_from_string(yaml)
        # If the modulemd was v1, it will be upgraded to v2
        mmd.upgrade()
    except Exception:
        if is_file:
            error = 'The modulemd {} is invalid. Please verify the syntax is correct'.format(
                os.path.basename(yaml)
            )
            if os.path.exists(yaml):
                with open(yaml, 'rt') as yaml_hdl:
                    log.debug('Modulemd content:\n%s', yaml_hdl.read())
            else:
                error = 'The modulemd file {} not found!'.format(os.path.basename(yaml))
                log.error('The modulemd file %s not found!', yaml)
        else:
            error = 'The modulemd is invalid. Please verify the syntax is correct'
            log.debug('Modulemd content:\n%s', yaml)
        log.exception(error)
        raise UnprocessableEntity(error)

    return mmd


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
    try:
        # py27
        builds.sort(lambda a, b: -cmp(a[2], b[2]))  # noqa: F821
    except TypeError:
        # py3
        builds.sort(key=lambda a: a[2], reverse=True)

    for nsv in local_build_nsvs:
        parts = nsv.split(':')
        if len(parts) < 1 or len(parts) > 3:
            raise RuntimeError(
                'The local build "{0}" couldn\'t be be parsed into '
                'NAME[:STREAM[:VERSION]]'.format(nsv))

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
                    nsv, conf.mock_resultsdir))

        # Load the modulemd metadata.
        path = os.path.join(conf.mock_resultsdir, found_build[3], 'results')
        mmd = load_mmd(os.path.join(path, 'modules.yaml'), is_file=True)

        # Create ModuleBuild in database.
        module = models.ModuleBuild.create(
            session,
            conf,
            name=mmd.get_name(),
            stream=mmd.get_stream(),
            version=str(mmd.get_version()),
            context=mmd.get_context(),
            modulemd=to_text_type(mmd.dumps()),
            scmurl="",
            username="mbs",
            publish_msg=False)
        module.koji_tag = path
        module.state = models.BUILD_STATES['ready']
        session.commit()

        if (found_build[0] != module.name or found_build[1] != module.stream or
                str(found_build[2]) != module.version):
            raise RuntimeError(
                'Parsed metadata results for "{0}" don\'t match the directory name'
                .format(found_build[3]))
        log.info("Loaded local module build %r", module)
