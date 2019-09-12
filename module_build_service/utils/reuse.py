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
import kobo.rpmlib

import module_build_service.messaging
from module_build_service import log, models, conf
from module_build_service.utils.mse import get_base_module_mmds


def reuse_component(component, previous_component_build, change_state_now=False):
    """
    Reuses component build `previous_component_build` instead of building
    component `component`

    Returns the list of BaseMessage instances to be handled later by the
    scheduler.
    """

    import koji

    log.info(
        'Reusing component "{0}" from a previous module '
        'build with the nvr "{1}"'.format(component.package, previous_component_build.nvr)
    )
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
        component.state = koji.BUILD_STATES["BUILDING"]
    component.state_reason = "Reused component from previous module build"
    component.nvr = previous_component_build.nvr
    nvr_dict = kobo.rpmlib.parse_nvr(component.nvr)
    # Add this message to further_work so that the reused
    # component will be tagged properly
    return [
        module_build_service.messaging.KojiBuildChange(
            msg_id="reuse_component: fake msg",
            build_id=None,
            task_id=component.task_id,
            build_new_state=previous_component_build.state,
            build_name=nvr_dict["name"],
            build_version=nvr_dict["version"],
            build_release=nvr_dict["release"],
            module_build_id=component.module_id,
            state_reason=component.state_reason,
        )
    ]


def get_reusable_module(db_session, module):
    """
    Returns previous module build of the module `module` in case it can be
    used as a source module to get the components to reuse from.

    In case there is no such module, returns None.

    :param db_session: SQLAlchemy database session
    :param module: the ModuleBuild object of module being built.
    :return: ModuleBuild object which can be used for component reuse.
    """

    if module.reused_module:
        return module.reused_module

    mmd = module.mmd()
    previous_module_build = None

    if conf.allow_only_compatible_base_modules:
        log.debug("Checking for compatible base modules")
        base_mmds = get_base_module_mmds(db_session, mmd)["ready"]
        # Sort the base_mmds based on the stream version, higher version first.
        base_mmds.sort(
            key=lambda mmd: models.ModuleBuild.get_stream_version(mmd.get_stream_name(), False),
            reverse=True)
    else:
        log.debug("Skipping the check for compatible base modules")
        base_mmds = []
        for br in module.buildrequires:
            if br.name in conf.base_module_names:
                base_mmds.append(br.mmd())

    for base_mmd in base_mmds:
        mbs_xmd = mmd.get_xmd()["mbs"]
        if base_mmd.get_module_name() not in mbs_xmd["buildrequires"]:
            continue
        mbs_xmd["buildrequires"][base_mmd.get_module_name()]["stream"] \
            = base_mmd.get_stream_name()
        build_context = module.calculate_build_context(mbs_xmd["buildrequires"])
        # Find the latest module that is in the ready state
        previous_module_build = (
            db_session.query(models.ModuleBuild)
                      .filter_by(name=mmd.get_module_name())
                      .filter_by(stream=mmd.get_stream_name())
                      .filter_by(state=models.BUILD_STATES["ready"])
                      .filter(models.ModuleBuild.scmurl.isnot(None))
                      .filter_by(build_context=build_context)
                      .order_by(models.ModuleBuild.time_completed.desc()))

        # If we are rebuilding with the "changed-and-after" option, then we can't reuse
        # components from modules that were built more liberally
        if module.rebuild_strategy == "changed-and-after":
            previous_module_build = previous_module_build.filter(
                models.ModuleBuild.rebuild_strategy.in_(["all", "changed-and-after"])
            )

        previous_module_build = previous_module_build.first()

        if previous_module_build:
            break

    # The component can't be reused if there isn't a previous build in the done
    # or ready state
    if not previous_module_build:
        log.info("Cannot re-use.  %r is the first module build." % module)
        return None

    module.reused_module_id = previous_module_build.id
    db_session.commit()

    return previous_module_build


def attempt_to_reuse_all_components(builder, db_session, module):
    """
    Tries to reuse all the components in a build. The components are also
    tagged to the tags using the `builder`.

    Returns True if all components could be reused, otherwise False. When
    False is returned, no component has been reused.
    """

    previous_module_build = get_reusable_module(db_session, module)
    if not previous_module_build:
        return False

    mmd = module.mmd()
    old_mmd = previous_module_build.mmd()

    # [(component, component_to_reuse), ...]
    component_pairs = []

    # Find out if we can reuse all components and cache component and
    # component to reuse pairs.
    for c in module.component_builds:
        if c.package == "module-build-macros":
            continue
        component_to_reuse = get_reusable_component(
            db_session,
            module,
            c.package,
            previous_module_build=previous_module_build,
            mmd=mmd,
            old_mmd=old_mmd,
        )
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
    builder.tag_artifacts(components_to_tag, dest_tag=True)

    return True


def get_reusable_components(db_session, module, component_names, previous_module_build=None):
    """
    Returns the list of ComponentBuild instances belonging to previous module
    build which can be reused in the build of module `module`.

    The ComponentBuild instances in returned list are in the same order as
    their names in the component_names input list.

    In case some component cannot be reused, None is used instead of a
    ComponentBuild instance in the returned list.

    :param db_session: SQLAlchemy database session
    :param module: the ModuleBuild object of module being built.
    :param component_names: List of component names to be reused.
    :kwarg previous_module_build: the ModuleBuild instance of a module build
        which contains the components to reuse. If not passed, get_reusable_module
        is called to get the ModuleBuild instance.
    :return: List of ComponentBuild instances to reuse in the same
             order as `component_names`
    """
    # We support components reusing only for koji and test backend.
    if conf.system not in ["koji", "test"]:
        return [None] * len(component_names)

    if not previous_module_build:
        previous_module_build = get_reusable_module(db_session, module)
    if not previous_module_build:
        return [None] * len(component_names)

    mmd = module.mmd()
    old_mmd = previous_module_build.mmd()

    ret = []
    for component_name in component_names:
        ret.append(
            get_reusable_component(
                db_session, module, component_name, previous_module_build, mmd, old_mmd)
        )

    return ret


def get_reusable_component(
    db_session, module, component_name, previous_module_build=None, mmd=None, old_mmd=None
):
    """
    Returns the component (RPM) build of a module that can be reused
    instead of needing to rebuild it
    :param db_session: SQLAlchemy database session
    :param module: the ModuleBuild object of module being built with a formatted
        mmd
    :param component_name: the name of the component (RPM) that you'd like to
        reuse a previous build of
    :param previous_module_build: the ModuleBuild instances of a module build
        which contains the components to reuse. If not passed, get_reusable_module
        is called to get the ModuleBuild instance. Consider passing the ModuleBuild
        instance in case you plan to call get_reusable_component repeatedly for the
        same module to make this method faster.
    :param mmd: Modulemd.ModuleStream of `module`. If not passed, it is taken from
        module.mmd(). Consider passing this arg in case you plan to call
        get_reusable_component repeatedly for the same module to make this method faster.
    :param old_mmd: Modulemd.ModuleStream of `previous_module_build`. If not passed,
        it is taken from previous_module_build.mmd(). Consider passing this arg in
        case you plan to call get_reusable_component repeatedly for the same
        module to make this method faster.
    :return: the component (RPM) build SQLAlchemy object, if one is not found,
        None is returned
    """

    # We support component reusing only for koji and test backend.
    if conf.system not in ["koji", "test"]:
        return None

    # If the rebuild strategy is "all", that means that nothing can be reused
    if module.rebuild_strategy == "all":
        message = ("Cannot reuse the component {component_name} because the module "
                   "rebuild strategy is \"all\".").format(
                       component_name=component_name)
        module.log_message(db_session, message)
        return None

    if not previous_module_build:
        previous_module_build = get_reusable_module(db_session, module)
        if not previous_module_build:
            message = ("Cannot reuse because no previous build of "
                       "module {module_name} found!").format(
                module_name=module.name)
            module.log_message(db_session, message)
            return None

    if not mmd:
        mmd = module.mmd()
    if not old_mmd:
        old_mmd = previous_module_build.mmd()

    # If the chosen component for some reason was not found in the database,
    # or the ref is missing, something has gone wrong and the component cannot
    # be reused
    new_module_build_component = models.ComponentBuild.from_component_name(
        db_session, component_name, module.id)
    if (
        not new_module_build_component
        or not new_module_build_component.batch
        or not new_module_build_component.ref
    ):
        message = ("Cannot reuse the component {} because it can't be found in the "
                   "database").format(component_name)
        module.log_message(db_session, message)
        return None

    prev_module_build_component = models.ComponentBuild.from_component_name(
        db_session, component_name, previous_module_build.id
    )
    # If the component to reuse for some reason was not found in the database,
    # or the ref is missing, something has gone wrong and the component cannot
    # be reused
    if (
        not prev_module_build_component
        or not prev_module_build_component.batch
        or not prev_module_build_component.ref
    ):
        message = ("Cannot reuse the component {} because a previous build of "
                   "it can't be found in the database").format(component_name)
        new_module_build_component.log_message(db_session, message)
        return None

    # Make sure the ref for the component that is trying to be reused
    # hasn't changed since the last build
    if prev_module_build_component.ref != new_module_build_component.ref:
        message = ("Cannot reuse the component because the commit hash changed"
                   " since the last build")
        new_module_build_component.log_message(db_session, message)
        return None

    # At this point we've determined that both module builds contain the component
    # and the components share the same commit hash
    if module.rebuild_strategy == "changed-and-after":
        # Make sure the batch number for the component that is trying to be reused
        # hasn't changed since the last build
        if prev_module_build_component.batch != new_module_build_component.batch:
            message = ("Cannot reuse the component because it is being built in "
                       "a different batch than in the compatible module build")
            new_module_build_component.log_message(db_session, message)
            return None

        # If the mmd.buildopts.macros.rpms changed, we cannot reuse
        buildopts = mmd.get_buildopts()
        if buildopts:
            modulemd_macros = buildopts.get_rpm_macros()
        else:
            modulemd_macros = None

        old_buildopts = old_mmd.get_buildopts()
        if old_buildopts:
            old_modulemd_macros = old_buildopts.get_rpm_macros()
        else:
            old_modulemd_macros = None

        if modulemd_macros != old_modulemd_macros:
            message = ("Cannot reuse the component because the modulemd's macros are"
                       " different than those of the compatible module build")
            new_module_build_component.log_message(db_session, message)
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

            new_module_build_components.append({
                (value.package, value.ref)
                for value in new_component_builds
                if value.batch == i + 1
            })

            previous_module_build_components.append({
                (value.package, value.ref)
                for value in prev_component_builds
                if value.batch == i + 1
            })

        # If the previous batches don't have the same ordering and hashes, then the
        # component can't be reused
        if previous_module_build_components != new_module_build_components:
            message = ("Cannot reuse the component because a component in a previous"
                       " batch has been rebuilt")
            new_module_build_component.log_message(db_session, message)
            return None

    for pkg_name in mmd.get_rpm_component_names():
        pkg = mmd.get_rpm_component(pkg_name)
        if pkg_name not in old_mmd.get_rpm_component_names():
            message = ("Cannot reuse the component because a component was added or "
                       "removed since the compatible module")
            new_module_build_component.log_message(db_session, message)
            return None
        if set(pkg.get_arches()) != set(old_mmd.get_rpm_component(pkg_name).get_arches()):
            message = ("Cannot reuse the component because the architectures for the package {}"
                       " have changed since the compatible module build").format(pkg_name)
            new_module_build_component.log_message(db_session, message)
            return None

    reusable_component = db_session.query(models.ComponentBuild).filter_by(
        package=component_name, module_id=previous_module_build.id).one()
    log.debug("Found reusable component!")
    return reusable_component
