# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT

import re

from kobo import rpmlib
import koji
import yaml
import requests
from sh import Command


class Koji:
    """Wrapper class to work with Koji

    :attribute string _server: URL of the Koji hub
    :attribute string _topurl: URL of the top-level Koji download location
    :attribute koji.ClientSession _session: Koji session
    """

    def __init__(self, server, topurl):
        self._server = server
        self._topurl = topurl
        self._session = koji.ClientSession(self._server)

    def get_build(self, nvr_dict):
        """Koji build data for NVR

        :param dict nvr_dict: NVR dictionary as expected by kobo.rpmlib.make_nvr()
        :return: Dictionary with Koji build data or None, if build is not found
        :rtype: dict or None
        """
        nvr_string = rpmlib.make_nvr(nvr_dict)
        return self._session.getBuild(nvr_string)


class Repo:
    """Wrapper class to work with module git repositories

    :attribute string module_name: name of the module stored in this repo
    :attribute dict _modulemd: Modulemd file as read from the repo
    """

    def __init__(self, module_name):
        self.module_name = module_name
        self._modulemd = None

    @property
    def modulemd(self):
        """Modulemd file as read from the repo

        :return: Modulemd file as read from the repo
        :rtype: dict
        """
        if self._modulemd is None:
            modulemd_file = self.module_name + ".yaml"
            with open(modulemd_file, "r") as f:
                self._modulemd = yaml.safe_load(f)
        return self._modulemd

    @property
    def components(self):
        """List of components as defined in the modulemd file

        :return: List of components as defined in the modulemd file
        :rtype: list of strings
        """
        return list(self.modulemd["data"]["components"]["rpms"])


class Build:
    """Wrapper class to work with module builds

    :attribute sh.Command _packaging_utility: packaging utility command used to
        kick off this build
    :attribute string _mbs_api: URL of the MBS API (including trailing '/')
    :attribute string _url: URL of this MBS module build
    :attribute string _data: Module build data cache for this build fetched from MBS
    """

    def __init__(self, packaging_utility, mbs_api):
        self._packaging_utility = Command(packaging_utility)
        self._mbs_api = mbs_api
        self._url = None
        self._data = None

    def run(self, *args):
        """Run a module build

        :param args: Options and arguments for the build command
        :return: MBS API URL for the build created
        :rtype: string
        """
        stdout = self._packaging_utility("module-build", *args).stdout.decode("utf-8")
        self._url = re.search(self._mbs_api + r"module-builds/\d+", stdout).group(0)
        return self._url

    @property
    def data(self):
        """Module build data cache for this build fetched from MBS"""
        if self._data is None:
            r = requests.get(self._url)
            r.raise_for_status()
            self._data = r.json()
        return self._data

    @property
    def state_name(self):
        """Name of the state of this module build"""
        return self.data["state_name"]

    def components(self, state="COMPLETE"):
        """Components of this module build which are in some state

        :param string state: Koji build state the components should be in
        :return: List of components
        :rtype: list of strings
        """
        comps = []
        for rpm, info in self.data["tasks"]["rpms"].items():
            if info["state"] == koji.BUILD_STATES[state]:
                comps.append(rpm)
        return comps

    def nvr(self, name_suffix=""):
        """NVR dictionary of this module build

        :param string name_suffix: an optional suffix for the name component of the NVR
        :return: dictionary with NVR components
        :rtype: dict
        """
        return {
            "name": f'{self.data["name"]}{name_suffix}',
            "version": self.data["stream"].replace("-", "_"),
            "release": f'{self.data["version"]}.{self.data["context"]}',
        }