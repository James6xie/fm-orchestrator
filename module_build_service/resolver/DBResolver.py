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
# Written by Matt Prahl <mprahl@redhat.com>

import hashlib

from module_build_service import log
from module_build_service.resolver.base import GenericResolver
from module_build_service import models
from module_build_service.errors import UnprocessableEntity


class DBResolver(GenericResolver):
    """
    Resolver using the MBS database
    """
    backend = 'db'

    def __init__(self, config):
        self.config = config

    def get_module_tag(self, name, stream, version, context, strict=False):
        """
        Gets the module tag from the resolver. Since the resolver is the DB, it is just generated
        here.
        :param name: a string of the module's name
        :param stream: a string of the module's stream
        :param version: a string or int of the module's version
        :param context: a string of the module's context
        :kwarg strict: Here solely for compatibility with the base class' function signature
        :return: a string of the tag to use
        """
        # This algorithm mimicks what pdc-updater does
        tag_str = '.'.join([name, stream, str(version), context])
        return 'module-{0}'.format(hashlib.sha1(tag_str).hexdigest()[:16])

    def _get_recursively_required_modules(self, build, session, modules=None, strict=False):
        """
        Returns a dictionary of modulemds by recursively querying the DB based on the
        depdendencies of the input module. The returned dictionary is a key of koji_tag
        and value of Modulemd object. Note that if there are some modules loaded by
        utils.load_local_builds(...), these local modules will be used instead of generically
        querying the DB.
        :param build: models.ModuleBuild object of the module to resolve
        :param modules: dictionary of koji_tag:modulemd found by previous iteration
            of this method. Used by recursion only.
        :param session: SQLAlchemy database sesion to query from
        :param strict: Normally this function returns an empty dictionary if no module can
            be found. If strict=True, then an UnprocessableEntity is raised instead.
        :return: a dictionary
        """
        modules = modules or {}
        koji_tag = build.koji_tag
        mmd = build.mmd()

        # Check if it's already been examined
        if koji_tag in modules:
            return modules

        modules.update({build.koji_tag: mmd})
        # We want to use the same stream as the one used in the time this
        # module was built. But we still should fallback to plain mmd.requires
        # in case this module depends on some older module for which we did
        # not populate mmd.xmd['mbs']['requires'].
        mbs_xmd = mmd.get_xmd().get('mbs')
        if 'requires' in mbs_xmd.keys():
            requires = {name: data['stream'] for name, data in mbs_xmd['requires'].items()}
        else:
            # Since MBS doesn't support v2 modulemds submitted by a user, we will
            # always only have one stream per require. That way it's safe to just take the first
            # element of the list.
            # TODO: Change this once module stream expansion is implemented
            requires = {
                name: deps.get()[0]
                for name, deps in mmd.get_dependencies()[0].get_requires().items()}

        for name, stream in requires.items():
            local_modules = models.ModuleBuild.local_modules(session, name, stream)
            if local_modules:
                dep = local_modules[0]
            else:
                dep = models.ModuleBuild.get_last_build_in_stream(session, name, stream)
            if dep:
                modules = self._get_recursively_required_modules(dep, session, modules, strict)
            elif strict:
                raise UnprocessableEntity(
                    'The module {0}:{1} was not found'.format(name, stream))

        return modules

    def resolve_profiles(self, mmd, keys):
        """
        Returns a dictionary with keys set according the `keys` parameters and values
        set to the union of all components defined in all installation profiles matching
        the key in all buildrequires. If there are some modules loaded by
        utils.load_local_builds(...), these local modules will be considered when returning
        the profiles.
        :param mmd: Modulemd.Module instance representing the module
        :param keys: list of modulemd installation profiles to include in the result
        :return: a dictionary
        """
        results = {}
        for key in keys:
            results[key] = set()
        with models.make_session(self.config) as session:
            for module_name, module_info in mmd.get_xmd()['mbs']['buildrequires'].items():
                local_modules = models.ModuleBuild.local_modules(
                    session, module_name, module_info['stream'])
                if local_modules:
                    local_module = local_modules[0]
                    log.info('Using local module {0!r} to resolve profiles.'.format(local_module))
                    dep_mmd = local_module.mmd()
                    for key in keys:
                        if key in dep_mmd.get_profiles().keys():
                            results[key] |= set(dep_mmd.get_profiles()[key].get_rpms().get())
                    continue

                build = session.query(models.ModuleBuild).filter_by(
                    name=module_name, stream=module_info['stream'],
                    version=module_info['version'], state=models.BUILD_STATES['ready']).first()
                if not build:
                    raise UnprocessableEntity('The module {}:{}:{} was not found'.format(
                        module_name, module_info['stream'], module_info['version']))

                modules = self._get_recursively_required_modules(build, session, strict=True)
                for name, dep_mmd in modules.items():
                    # Take note of what rpms are in this dep's profile
                    for key in keys:
                        if key in dep_mmd.get_profiles().keys():
                            results[key] |= set(dep_mmd.get_profiles()[key].get_rpms().get())

        # Return the union of all rpms in all profiles of the given keys
        return results

    def get_module_build_dependencies(self, name=None, stream=None, version=None, context=None,
                                      mmd=None, strict=False):
        """
        Returns a dictionary of koji_tag:mmd of all the dependencies
        :kwarg name: a string of a module's name (required if mmd is not set)
        :kwarg stream: a string of a module's stream (required if mmd is not set)
        :kwarg version: a string of a module's version (required if mmd is not set)
        :kwarg context: a string of a module's context (required if mmd is not set)
        :kwarg mmd: Modulemd.Module object. If this is set, the mmd will be used instead of
            querying the DB with the name, stream, version, and context.
        :kwarg strict: Normally this function returns None if no module can be
            found.  If strict=True, then an UnprocessableEntity is raised.
        :return: a dictionary
        """
        if mmd:
            log.debug('get_module_build_dependencies(mmd={0!r} strict={1!r})'.format(mmd, strict))
        elif any(x is None for x in [name, stream, version, context]):
            raise RuntimeError('The name, stream, version, and/or context weren\'t specified')
        else:
            version = str(version)
            log.debug('get_module_build_dependencies({0}, strict={1!r})'.format(
                ', '.join([name, stream, str(version), context]), strict))

        module_tags = {}
        with models.make_session(self.config) as session:
            if mmd:
                queried_mmd = mmd
                nsvc = ':'.join([
                    mmd.get_name(), mmd.get_stream(), str(mmd.get_version()),
                    mmd.get_context() or '00000000'])
            else:
                build = None
                for _build in session.query(models.ModuleBuild).filter_by(
                        name=name, stream=stream, version=version).all():
                    # Figure out how to query by context directly
                    if _build.context == context:
                        build = _build
                        break
                if not build:
                    raise UnprocessableEntity('The module {} was not found'.format(
                        ':'.join([name, stream, version, context])))
                queried_mmd = build.mmd()
                nsvc = ':'.join([name, stream, version, context])

            xmd_mbs = queried_mmd.get_xmd().get('mbs')
            if not xmd_mbs or 'buildrequires' not in xmd_mbs.keys():
                raise RuntimeError(
                    'The module {} did not contain its modulemd or did not have '
                    'its xmd attribute filled out in PDC'.format(nsvc))

            buildrequires = xmd_mbs['buildrequires']
            for br_name, details in buildrequires.items():
                build = session.query(models.ModuleBuild).filter_by(
                    name=br_name, stream=details['stream'], version=details['version'],
                    state=models.BUILD_STATES['ready']).first()
                if not build:
                    raise UnprocessableEntity('The module {} was not found'.format(
                        ':'.join([br_name, details['stream'], details['version']])))
                module_tags.update(
                    self._get_recursively_required_modules(build, session, strict=strict))

        return module_tags

    def resolve_requires(self, requires):
        """
        Resolves the requires dictionary to a dictionary with keys as the module name and the
        values as a dictionary with keys of ref, stream, version, filtered_rpms.
        If there are some modules loaded by utils.load_local_builds(...), these
        local modules will be considered when resolving the requires. A RuntimeError
        is raised on DB lookup errors.
        :param requires: a dictionary with the module name as the key and the stream as the value
        :return: a dictionary
        """
        new_requires = {}
        with models.make_session(self.config) as session:
            for module_name, module_stream in requires.items():
                local_modules = models.ModuleBuild.local_modules(
                    session, module_name, module_stream)
                if local_modules:
                    local_build = local_modules[0]
                    new_requires[module_name] = {
                        'ref': None,
                        'stream': local_build.stream,
                        'version': local_build.version,
                        # No need to set filtered_rpms for local builds, because MBS
                        # filters the RPMs automatically when the module build is
                        # done.
                        'filtered_rpms': []
                    }
                    continue

                build = models.ModuleBuild.get_last_build_in_stream(
                    session, module_name, module_stream)
                if not build:
                    raise UnprocessableEntity('The module {}:{} was not found'.format(
                        module_name, module_stream))
                commit_hash = None
                filtered_rpms = []
                mmd = build.mmd()
                mbs_xmd = mmd.get_xmd().get('mbs')
                if mbs_xmd and 'commit' in mbs_xmd.keys():
                    commit_hash = mbs_xmd['commit']
                else:
                    raise RuntimeError(
                        'The module "{0}" didn\'t contain a commit hash in its xmd'
                        .format(module_name))

                # Find out the particular NVR of filtered packages
                rpm_filter = mmd.get_rpm_filter()
                if rpm_filter:
                    for rpm in build.component_builds:
                        if rpm.package in rpm_filter:
                            filtered_rpms.append(rpm.nvr)

                new_requires[module_name] = {
                    'ref': commit_hash,
                    'stream': module_stream,
                    'version': build.version,
                    'filtered_rpms': filtered_rpms,
                }

        return new_requires
