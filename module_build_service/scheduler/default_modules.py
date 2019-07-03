# -*- coding: utf-8 -*-
# Copyright (c) 2019  Red Hat, Inc.
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
import requests

from module_build_service import conf, log, models
from module_build_service.errors import UnprocessableEntity
from module_build_service.utils.request_utils import requests_session
from module_build_service.resolver import system_resolver as resolver


def add_default_modules(db_session, mmd):
    """
    Add default modules as buildrequires to the input modulemd.

    The base modules that are buildrequired can optionally link their default modules by specifying
    a URL to a text file in xmd.mbs.default_modules_url. Any default module that isn't in the
    database will be logged and ignored.

    :param db_session: a SQLAlchemy database session
    :param Modulemd.ModuleStream mmd: the modulemd of the module to add the module defaults to
    :raises RuntimeError: if the buildrequired base module isn't in the database or the default
        modules list can't be downloaded
    """
    log.info("Finding the default modules to include as buildrequires")
    xmd = mmd.get_xmd()
    buildrequires = xmd["mbs"]["buildrequires"]

    for module_name in conf.base_module_names:
        bm_info = buildrequires.get(module_name)
        if bm_info is None:
            log.debug(
                "The base module %s is not a buildrequire of the submitted module %s",
                module_name, mmd.get_nsvc(),
            )
            continue

        bm = models.ModuleBuild.get_build_from_nsvc(
            db_session, module_name, bm_info["stream"], bm_info["version"], bm_info["context"],
        )
        bm_nsvc = ":".join([
            module_name, bm_info["stream"], bm_info["version"], bm_info["context"],
        ])
        if not bm:
            raise RuntimeError("Failed to retrieve the module {} from the database".format(bm_nsvc))

        bm_mmd = bm.mmd()
        bm_xmd = bm_mmd.get_xmd()
        default_modules_url = bm_xmd.get("mbs", {}).get("default_modules_url")
        if not default_modules_url:
            log.debug("The base module %s does not have any default modules", bm_nsvc)
            continue

        try:
            rv = requests_session.get(default_modules_url, timeout=10)
        except requests.RequestException:
            msg = (
                "The connection failed when getting the default modules associated with {}"
                .format(bm_nsvc)
            )
            log.exception(msg)
            raise RuntimeError(msg)

        if not rv.ok:
            log.error(
                "The request to get the default modules associated with %s failed with the status "
                'code %d and error "%s"',
                bm_nsvc, rv.status_code, rv.text,
            )
            raise RuntimeError(
                "Failed to retrieve the default modules for {}".format(bm_mmd.get_nsvc())
            )

        default_modules = [m.strip() for m in rv.text.strip().split("\n")]
        for default_module in default_modules:
            try:
                name, stream = default_module.split(":")
            except ValueError:
                log.error(
                    'The default module "%s" from %s is in an invalid format',
                    default_module, rv.url,
                )
                continue

            if name in buildrequires:
                conflicting_stream = buildrequires[name]["stream"]
                if stream == conflicting_stream:
                    log.info("The default module %s is already a buildrequire", default_module)
                    continue

                log.info(
                    "The default module %s will not be added as a buildrequire since %s:%s "
                    "is already a buildrequire",
                    default_module, name, conflicting_stream,
                )
                continue

            try:
                # We are reusing resolve_requires instead of directly querying the database since it
                # provides the exact format that is needed for mbs.xmd.buildrequires.
                #
                # Only one default module is processed at a time in resolve_requires so that we
                # are aware of which modules are not in the database, and can add those that are as
                # buildrequires.
                resolved = resolver.resolve_requires([default_module])
            except UnprocessableEntity:
                log.warning(
                    "The default module %s from %s is not in the database and couldn't be added as "
                    "a buildrequire",
                    default_module, bm_nsvc
                )
                continue

            nsvc = ":".join([name, stream, resolved[name]["version"], resolved[name]["context"]])
            log.info("Adding the default module %s as a buildrequire", nsvc)
            buildrequires.update(resolved)

    mmd.set_xmd(xmd)
