# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
from __future__ import absolute_import

from module_build_service.common import conf, log, models
from module_build_service.common.errors import StreamAmbigous, UnprocessableEntity, ValidationError
from module_build_service.common.modulemd import Modulemd
from module_build_service.common.resolve import expand_single_mse_streams, get_base_module_mmds
from module_build_service.common.utils import mmd_to_str
from module_build_service.resolver import GenericResolver
from module_build_service.web.mmd_resolver import MMDResolver
from module_build_service.web.utils import deps_to_dict


def expand_mse_streams(db_session, mmd, default_streams=None, raise_if_stream_ambigous=False):
    """
    Expands streams in both buildrequires/requires sections of MMD.

    :param db_session: SQLAlchemy DB session.
    :param Modulemd.ModuleStream mmd: Modulemd metadata with original unexpanded module.
    :param dict default_streams: Dict in {module_name: module_stream, ...} format defining
        the default stream to choose for module in case when there are multiple streams to
        choose from.
    :param bool raise_if_stream_ambigous: When True, raises a StreamAmbigous exception in case
        there are multiple streams for some dependency of module and the module name is not
        defined in `default_streams`, so it is not clear which stream should be used.
    """
    for deps in mmd.get_dependencies():
        new_deps = Modulemd.Dependencies()
        for name in deps.get_runtime_modules():
            streams = deps.get_runtime_streams(name)
            new_streams = expand_single_mse_streams(
                db_session, name, streams, default_streams, raise_if_stream_ambigous)

            if not new_streams:
                new_deps.set_empty_runtime_dependencies_for_module(name)
            else:
                for stream in new_streams:
                    new_deps.add_runtime_stream(name, stream)

        for name in deps.get_buildtime_modules():
            streams = deps.get_buildtime_streams(name)
            new_streams = expand_single_mse_streams(
                db_session, name, streams, default_streams, raise_if_stream_ambigous)

            if not new_streams:
                new_deps.set_empty_buildtime_dependencies_for_module(name)
            else:
                for stream in new_streams:
                    new_deps.add_buildtime_stream(name, stream)

        # Replace the Dependencies object
        mmd.remove_dependencies(deps)
        mmd.add_dependencies(new_deps)


def _get_mmds_from_requires(
    db_session,
    requires,
    mmds,
    recursive=False,
    default_streams=None,
    raise_if_stream_ambigous=False,
    base_module_mmds=None,
):
    """
    Helper method for get_mmds_required_by_module_recursively returning
    the list of module metadata objects defined by `requires` dict.

    :param db_session: SQLAlchemy database session.
    :param dict requires: requires or buildrequires in the form {module: [streams]}
    :param mmds: Dictionary with already handled name:streams as a keys and lists
        of resulting mmds as values.
    :param recursive: If True, the requires are checked recursively.
    :param dict default_streams: Dict in {module_name: module_stream, ...} format defining
        the default stream to choose for module in case when there are multiple streams to
        choose from.
    :param bool raise_if_stream_ambigous: When True, raises a StreamAmbigous exception in case
        there are multiple streams for some dependency of module and the module name is not
        defined in `default_streams`, so it is not clear which stream should be used.
    :param list base_module_mmds: List of modulemd metadata instances. When set, the
        returned list contains MMDs build against each base module defined in
        `base_module_mmds` list.
    :return: Dict with name:stream as a key and list with mmds as value.
    """
    default_streams = default_streams or {}
    # To be able to call itself recursively, we need to store list of mmds
    # we have added to global mmds list in this particular call.
    added_mmds = {}
    resolver = GenericResolver.create(db_session, conf)

    for name, streams in requires.items():
        # Base modules are already added to `mmds`.
        if name in conf.base_module_names:
            continue

        streams_to_try = streams
        if name in default_streams:
            streams_to_try = [default_streams[name]]
        elif len(streams_to_try) > 1 and raise_if_stream_ambigous:
            raise StreamAmbigous(
                "There are multiple streams %r to choose from for module %s."
                % (streams_to_try, name)
            )

        # For each valid stream, find the last build in a stream and also all
        # its contexts and add mmds of these builds to `mmds` and `added_mmds`.
        # Of course only do that if we have not done that already in some
        # previous call of this method.
        for stream in streams:
            ns = "%s:%s" % (name, stream)
            if ns not in mmds:
                mmds[ns] = []
            if ns not in added_mmds:
                added_mmds[ns] = []

            if base_module_mmds:
                base_module_streams = {}
                for base_module_mmd in base_module_mmds:
                    # Group base module streams by major version
                    base_stream = base_module_mmd.get_stream_name()
                    base_stream_version = int(models.ModuleBuild.get_stream_version(base_stream))
                    x = base_stream_version // 10000
                    # tuple (base_stream_version, mmd) used for sorting
                    base_module_streams.setdefault(x, []).append(
                        (base_stream_version, base_module_mmd))
                for x in sorted(base_module_streams, reverse=True):
                    # Get latest builds that buildrequires the most recent
                    # base module stream, for each base module major version.
                    for base_stream_version, base_module_mmd in sorted(
                            base_module_streams[x], reverse=True):
                        builds = resolver.get_buildrequired_modulemds(
                            name, stream, base_module_mmd)
                        if builds != []:
                            mmds[ns] += builds
                            break
            else:
                mmds[ns] = resolver.get_module_modulemds(name, stream, strict=True)
            added_mmds[ns] += mmds[ns]

    # Get the requires recursively.
    if recursive:
        for mmd_list in added_mmds.values():
            for mmd in mmd_list:
                for deps in mmd.get_dependencies():
                    deps_dict = deps_to_dict(deps, 'runtime')
                    mmds = _get_mmds_from_requires(
                        db_session, deps_dict, mmds, True, base_module_mmds=base_module_mmds)

    return mmds


def get_mmds_required_by_module_recursively(
    db_session, mmd, default_streams=None, raise_if_stream_ambigous=False
):
    """
    Returns the list of Module metadata objects of all modules required while
    building the module defined by `mmd` module metadata. This presumes the
    module metadata streams are expanded using `expand_mse_streams(...)`
    method.

    This method finds out latest versions of all the build-requires of
    the `mmd` module and then also all contexts of these latest versions.

    For each build-required name:stream:version:context module, it checks
    recursively all the "requires" and finds the latest version of each
    required module and also all contexts of these latest versions.

    :param db_session: SQLAlchemy database session.
    :param dict default_streams: Dict in {module_name: module_stream, ...} format defining
        the default stream to choose for module in case when there are multiple streams to
        choose from.
    :param bool raise_if_stream_ambigous: When True, raises a StreamAmbigous exception in case
        there are multiple streams for some dependency of module and the module name is not
        defined in `default_streams`, so it is not clear which stream should be used.
    :rtype: list of Modulemd metadata
    :return: List of all modulemd metadata of all modules required to build
        the module `mmd`.
    """
    # We use dict with name:stream as a key and list with mmds as value.
    # That way, we can ensure we won't have any duplicate mmds in a resulting
    # list and we also don't waste resources on getting the modules we already
    # handled from DB.
    mmds = {}

    # Get the MMDs of all compatible base modules based on the buildrequires.
    base_module_mmds = get_base_module_mmds(db_session, mmd)
    if not base_module_mmds["ready"]:
        base_module_choices = " or ".join(conf.base_module_names)
        raise UnprocessableEntity(
            "None of the base module ({}) streams in the buildrequires section could be found"
            .format(base_module_choices)
        )

    # Add base modules to `mmds`.
    for base_module in base_module_mmds["ready"]:
        ns = ":".join([base_module.get_module_name(), base_module.get_stream_name()])
        mmds.setdefault(ns, [])
        mmds[ns].append(base_module)

    # The currently submitted module build must be built only against "ready" base modules,
    # but its dependencies might have been built against some old platform which is already
    # EOL ("garbage" state). In order to find such old module builds, we need to include
    # also EOL platform streams.
    all_base_module_mmds = base_module_mmds["ready"] + base_module_mmds["garbage"]

    # Get all the buildrequires of the module of interest.
    for deps in mmd.get_dependencies():
        deps_dict = deps_to_dict(deps, 'buildtime')
        mmds = _get_mmds_from_requires(
            db_session, deps_dict, mmds, False, default_streams, raise_if_stream_ambigous,
            all_base_module_mmds)

    # Now get the requires of buildrequires recursively.
    for mmd_key in list(mmds.keys()):
        for mmd in mmds[mmd_key]:
            for deps in mmd.get_dependencies():
                deps_dict = deps_to_dict(deps, 'runtime')
                mmds = _get_mmds_from_requires(
                    db_session, deps_dict, mmds, True, default_streams,
                    raise_if_stream_ambigous, all_base_module_mmds)

    # Make single list from dict of lists.
    res = []
    for ns, mmds_list in mmds.items():
        if len(mmds_list) == 0:
            raise UnprocessableEntity("Cannot find any module builds for %s" % (ns))
        res += mmds_list
    return res


def generate_expanded_mmds(db_session, mmd, raise_if_stream_ambigous=False, default_streams=None,
                           static_context=False):
    """
    Returns list with MMDs with buildrequires and requires set according
    to module stream expansion rules. These module metadata can be directly
    built using MBS.

    :param db_session: SQLAlchemy DB session.
    :param Modulemd.ModuleStream mmd: Modulemd metadata with original unexpanded module.
    :param bool raise_if_stream_ambigous: When True, raises a StreamAmbigous exception in case
        there are multiple streams for some dependency of module and the module name is not
        defined in `default_streams`, so it is not clear which stream should be used.
    :param dict default_streams: Dict in {module_name: module_stream, ...} format defining
        the default stream to choose for module in case when there are multiple streams to
        choose from.
    :param bool static_context: When True will use a predefined context from the mmd yaml file
        and will not generate a new one. Also it will set `static_context` property in the `mbs`
        property to True.
    """
    if not default_streams:
        default_streams = {}

    # Create local copy of mmd, because we will expand its dependencies,
    # which would change the module.
    current_mmd = mmd.copy()

    # if a static context is set the generated context will be overridden by the one
    # defined in the mmd of the module.
    if static_context:
        context = current_mmd.get_context()
    # MMDResolver expects the input MMD to have no context.
    current_mmd.set_context(None)

    # Expands the MSE streams. This mainly handles '-' prefix in MSE streams.
    expand_mse_streams(db_session, current_mmd, default_streams, raise_if_stream_ambigous)

    # Get the list of all MMDs which this module can be possibly built against
    # and add them to MMDResolver.
    mmd_resolver = MMDResolver()
    mmds_for_resolving = get_mmds_required_by_module_recursively(
        db_session, current_mmd, default_streams, raise_if_stream_ambigous)
    for m in mmds_for_resolving:
        mmd_resolver.add_modules(m)

    # Show log.info message with the NSVCs we have added to mmd_resolver.
    nsvcs_to_solve = [m.get_nsvc() for m in mmds_for_resolving]
    log.info("Starting resolving with following input modules: %r", nsvcs_to_solve)

    # Resolve the dependencies between modules and get the list of all valid
    # combinations in which we can build this module.
    requires_combinations = mmd_resolver.solve(current_mmd)
    log.info("Resolving done, possible requires: %r", requires_combinations)

    # This is where we are going to store the generated MMDs.
    mmds = []
    for requires in requires_combinations:
        # Each generated MMD must be new Module object...
        mmd_copy = mmd.copy()
        xmd = mmd_copy.get_xmd()

        # Requires contain the NSVC representing the input mmd.
        # The 'context' of this NSVC defines the id of buildrequires/requires
        # pair in the mmd.get_dependencies().
        dependencies_id = None

        # We don't want to depend on ourselves, so store the NSVC of the current_mmd
        # to be able to ignore it later.
        self_nsvca = None

        # Dict to store name:stream pairs from nsvca, so we are able to access it
        # easily later.
        req_name_stream = {}

        # Get the values for dependencies_id, self_nsvca and req_name_stream variables.
        for nsvca in requires:
            req_name, req_stream, _, req_context, req_arch = nsvca.split(":")
            if req_arch == "src":
                assert req_name == current_mmd.get_module_name()
                assert req_stream == current_mmd.get_stream_name()
                assert dependencies_id is None
                assert self_nsvca is None
                dependencies_id = int(req_context)
                self_nsvca = nsvca
                continue
            req_name_stream[req_name] = req_stream
        if dependencies_id is None or self_nsvca is None:
            raise RuntimeError(
                "%s:%s not found in requires %r"
                % (current_mmd.get_module_name(), current_mmd.get_stream_name(), requires)
            )

        # The name:[streams, ...] pairs do not have to be the same in both
        # buildrequires/requires. In case they are the same, we replace the streams
        # in requires section with a single stream against which we will build this MMD.
        # In case they are not the same, we have to keep the streams as they are in requires
        # section.  We always replace stream(s) for build-requirement with the one we
        # will build this MMD against.
        new_deps = Modulemd.Dependencies()
        deps = mmd_copy.get_dependencies()[dependencies_id]
        deps_requires = deps_to_dict(deps, 'runtime')
        deps_buildrequires = deps_to_dict(deps, 'buildtime')
        for req_name, req_streams in deps_requires.items():
            if req_name not in deps_buildrequires:
                # This require is not a buildrequire so just copy this runtime requirement to
                # new_dep and don't touch buildrequires
                if not req_streams:
                    new_deps.set_empty_runtime_dependencies_for_module(req_name)
                else:
                    for req_stream in req_streams:
                        new_deps.add_runtime_stream(req_name, req_stream)
            elif set(req_streams) != set(deps_buildrequires[req_name]):
                # Streams in runtime section are not the same as in buildtime section,
                # so just copy this runtime requirement to new_dep.
                if not req_streams:
                    new_deps.set_empty_runtime_dependencies_for_module(req_name)
                else:
                    for req_stream in req_streams:
                        new_deps.add_runtime_stream(req_name, req_stream)

                new_deps.add_buildtime_stream(req_name, req_name_stream[req_name])
            else:
                # This runtime requirement has the same streams in both runtime/buildtime
                # requires sections, so replace streams in both sections by the one we
                # really used in this resolved variant.
                new_deps.add_runtime_stream(req_name, req_name_stream[req_name])
                new_deps.add_buildtime_stream(req_name, req_name_stream[req_name])

        # There might be buildrequires which are not in runtime requires list.
        # Such buildrequires must be copied to expanded MMD.
        for req_name, req_streams in deps_buildrequires.items():
            if req_name not in deps_requires:
                new_deps.add_buildtime_stream(req_name, req_name_stream[req_name])

        # Set the new dependencies.
        mmd_copy.remove_dependencies(deps)
        mmd_copy.add_dependencies(new_deps)

        # The Modulemd.Dependencies() stores only streams, but to really build this
        # module, we need NSVC of buildrequires, so we have to store this data in XMD.
        # We also need additional data like for example list of filtered_rpms. We will
        # get them using module_build_service.resolver.GenericResolver.resolve_requires,
        # so prepare list with NSVCs of buildrequires as an input for this method.
        br_list = []
        for nsvca in requires:
            if nsvca == self_nsvca:
                continue
            # Remove the arch from nsvca
            nsvc = ":".join(nsvca.split(":")[:-1])
            br_list.append(nsvc)

        # Resolve the buildrequires and store the result in XMD.
        if "mbs" not in xmd:
            xmd["mbs"] = {}
        resolver = GenericResolver.create(db_session, conf)
        xmd["mbs"]["buildrequires"] = resolver.resolve_requires(br_list)

        xmd["mbs"]["mse"] = True
        # if static context is used the mse is expanded beforehand. This means that the
        # mmd set as a parameter to this function has only one context per stream.
        # we set a `static_context` property to True to mark module streams with static contexts.
        if static_context:
            xmd["mbs"]["static_context"] = True

        mmd_copy.set_xmd(xmd)

        # we only compute the context if static context is False
        if not static_context:
            # Now we have all the info to actually compute context of this module.
            context = models.ModuleBuild.contexts_from_mmd(mmd_to_str(mmd_copy)).context

        mmd_copy.set_context(context)

        mmds.append(mmd_copy)

    return mmds


def generate_mmds_from_static_contexts(mmd):
    """
    This function preexpands the MSE when static contexts which are defined by the `contexts`
    property under `mbs_options` in the `xmd` property of the initial modulemd file.

    :param Modulemd.ModuleStream mmd: Modulemd metadata with the `contexts` property.
    :return list mmds: list of distinct mmds identified by context.
    """

    xmd = mmd.get_xmd()
    if not xmd:
        raise ValidationError("The 'xmd' property of the modulemd yaml file is empty!")

    if not xmd["mbs_options"].get("contexts"):
        raise ValidationError(("The 'xmd' property of the modulemd yaml file does not contain the"
                               " 'contexts' key."))

    contexts = xmd["mbs_options"].get("contexts")
    if not type(contexts) is dict:
        raise ValidationError("The value of the 'contexts' property needs to be a dict.")

    # remove the information about the `contexts` property from the `mbs_options` as we do not
    # needed anymore
    xmd["mbs_options"].pop("contexts")

    # we check if the `mbs_options` dict is empty after we remove the `contexts` key.
    # if yes we remove `the mbs_options`.
    if not xmd["mbs_options"]:
        xmd.pop("mbs_options")

    mmd.set_xmd(xmd)

    mmds = []
    for context, dependencies in contexts.items():
        # we copy the mmd so we a get a fresh module for each context.
        mmd_copy = mmd.copy()
        mmd_copy.set_context(context)

        if "buildrequires" not in dependencies:
            raise ValidationError(("The  context '{context}' is missing the"
                                   " 'buildrequires' key!").format(context=context))

        if "requires" not in dependencies:
            raise ValidationError("The context '{context}' is missing the 'requires' key!".format(
                context=context))

        # remove the old deps from the mmd
        old_module_deps = mmd_copy.get_dependencies()
        for deps in old_module_deps:
            mmd_copy.remove_dependencies(deps)

        module_deps = Modulemd.Dependencies.new()

        # populate the new requires and buildrequires according to the `contexts` property
        for module, stream in dependencies["buildrequires"].items():
            _validate_stream_name_for_static_context(module, stream, context, "buildrequires")
            module_deps.add_buildtime_stream(module, stream)

        for module, stream in dependencies["requires"].items():
            _validate_stream_name_for_static_context(module, stream, context, "requires")
            module_deps.add_runtime_stream(module, stream)

        mmd_copy.add_dependencies(module_deps)

        mmds.append(mmd_copy)

    return mmds


def _validate_stream_name_for_static_context(module, stream, context, dep_type):
    """
    Validates the the streams of static contexts.

    :param str module: name of the module
    :param str stream: name of the stream
    :param str context: name of the context
    :param str dep_type: type of the dependencies the module stream belongs to i. e. requires,
        buildrequires.
    :return None
    """

    if not stream:
        raise ValidationError(("The '{module}' module in '{dep_type}' of the '{context}' static "
                               "context has no stream defined.").format(module=module,
                                                                        dep_type=dep_type,
                                                                        context=context))

    stream_type = type(stream)
    if stream_type is not str:
        raise ValidationError(("The module '{module}' in '{dep_type}' of the '{context}' "
                               "static context is of type '{stream_type}' should be "
                               "'str' type.").format(stream=stream,
                                                     module=module,
                                                     dep_type=dep_type,
                                                     context=context,
                                                     stream_type=stream_type))

    if stream.startswith("-"):
        raise ValidationError(("The '{stream}' stream of module '{module}' in '{dep_type}' of the"
                               "'{context}' static contexts is using stream expansion. Usage of "
                               "stream expansion with static context is forbidden."
                               ).format(stream=stream,
                                        module=module,
                                        dep_type=dep_type,
                                        context=context))
