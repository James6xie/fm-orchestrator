# Copyright (c) 2019 Red Hat, Inc.
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
from collections import namedtuple
import errno
import textwrap

import dnf
from mock import call, Mock, patch
import pytest
import requests

from module_build_service.models import ModuleBuild
from module_build_service.scheduler import default_modules
from module_build_service.utils.general import load_mmd, mmd_to_str
from tests import clean_database, make_module, read_staged_data


@patch("module_build_service.scheduler.default_modules._handle_collisions")
@patch("module_build_service.scheduler.default_modules.requests_session")
def test_add_default_modules(mock_requests_session, mock_hc, db_session):
    """
    Test that default modules present in the database are added, and the others are ignored.
    """
    clean_database()
    make_module(db_session, "python:3:12345:1")
    make_module(db_session, "nodejs:11:2345:2")
    mmd = load_mmd(read_staged_data("formatted_testmodule.yaml"))
    xmd_brs = mmd.get_xmd()["mbs"]["buildrequires"]
    assert set(xmd_brs.keys()) == {"platform"}

    platform = ModuleBuild.get_build_from_nsvc(
        db_session,
        "platform",
        xmd_brs["platform"]["stream"],
        xmd_brs["platform"]["version"],
        xmd_brs["platform"]["context"],
    )
    assert platform
    platform_mmd = platform.mmd()
    platform_xmd = mmd.get_xmd()
    default_modules_url = "http://domain.local/default_modules.txt"
    platform_xmd["mbs"]["default_modules_url"] = default_modules_url
    platform_mmd.set_xmd(platform_xmd)
    platform.modulemd = mmd_to_str(platform_mmd)
    db_session.commit()

    mock_requests_session.get.return_value.ok = True
    # Also ensure that if there's an invalid line, it's just ignored
    mock_requests_session.get.return_value.text = textwrap.dedent("""\
        nodejs:11
        python:3
        ruby:2.6
        some invalid stuff
    """)
    default_modules.add_default_modules(db_session, mmd, ["x86_64"])
    # Make sure that the default modules were added. ruby:2.6 will be ignored since it's not in
    # the database
    assert set(mmd.get_xmd()["mbs"]["buildrequires"].keys()) == {"nodejs", "platform", "python"}
    mock_requests_session.get.assert_called_once_with(default_modules_url, timeout=10)
    mock_hc.assert_called_once()


@patch("module_build_service.scheduler.default_modules.requests_session")
def test_add_default_modules_not_linked(mock_requests_session, db_session):
    """
    Test that no default modules are added when they aren't linked from the base module.
    """
    clean_database()
    mmd = load_mmd(read_staged_data("formatted_testmodule.yaml"))
    assert set(mmd.get_xmd()["mbs"]["buildrequires"].keys()) == {"platform"}
    default_modules.add_default_modules(db_session, mmd, ["x86_64"])
    assert set(mmd.get_xmd()["mbs"]["buildrequires"].keys()) == {"platform"}
    mock_requests_session.get.assert_not_called()


@patch("module_build_service.scheduler.default_modules.requests_session")
def test_add_default_modules_platform_not_available(mock_requests_session, db_session):
    """
    Test that an exception is raised when the platform module that is buildrequired is missing.

    This error should never occur in practice.
    """
    clean_database(False, False)
    mmd = load_mmd(read_staged_data("formatted_testmodule.yaml"))

    expected_error = "Failed to retrieve the module platform:f28:3:00000000 from the database"
    with pytest.raises(RuntimeError, match=expected_error):
        default_modules.add_default_modules(db_session, mmd, ["x86_64"])


@pytest.mark.parametrize("connection_error", (True, False))
@patch("module_build_service.scheduler.default_modules.requests_session")
def test_add_default_modules_request_failed(mock_requests_session, connection_error, db_session):
    """
    Test that an exception is raised when the request to get the default modules failed.
    """
    clean_database()
    make_module(db_session, "python:3:12345:1")
    make_module(db_session, "nodejs:11:2345:2")
    mmd = load_mmd(read_staged_data("formatted_testmodule.yaml"))
    xmd_brs = mmd.get_xmd()["mbs"]["buildrequires"]
    assert set(xmd_brs.keys()) == {"platform"}

    platform = ModuleBuild.get_build_from_nsvc(
        db_session,
        "platform",
        xmd_brs["platform"]["stream"],
        xmd_brs["platform"]["version"],
        xmd_brs["platform"]["context"],
    )
    assert platform
    platform_mmd = platform.mmd()
    platform_xmd = mmd.get_xmd()
    default_modules_url = "http://domain.local/default_modules.txt"
    platform_xmd["mbs"]["default_modules_url"] = default_modules_url
    platform_mmd.set_xmd(platform_xmd)
    platform.modulemd = mmd_to_str(platform_mmd)
    db_session.commit()

    if connection_error:
        mock_requests_session.get.side_effect = requests.ConnectionError("some error")
        expected_error = (
            "The connection failed when getting the default modules associated with "
            "platform:f28:3:00000000"
        )
    else:
        mock_requests_session.get.return_value.ok = False
        mock_requests_session.get.return_value.text = "some error"
        expected_error = "Failed to retrieve the default modules for platform:f28:3:00000000"

    with pytest.raises(RuntimeError, match=expected_error):
        default_modules.add_default_modules(db_session, mmd, ["x86_64"])


@patch("module_build_service.scheduler.default_modules.KojiModuleBuilder.get_session")
@patch("module_build_service.scheduler.default_modules._get_rpms_from_tags")
def test_handle_collisions(mock_grft, mock_get_session):
    """
    Test that _handle_collisions will add conflicts for NEVRAs in the modulemd.
    """
    mmd = load_mmd(read_staged_data("formatted_testmodule.yaml"))
    xmd = mmd.get_xmd()
    xmd["mbs"]["buildrequires"]["platform"]["koji_tag"] = "module-el-build"
    xmd["mbs"]["buildrequires"]["python"] = {"koji_tag": "module-python27"}
    xmd["mbs"]["buildrequires"]["bash"] = {"koji_tag": "module-bash"}
    mmd.set_xmd(xmd)

    bm_rpms = {
        "bash-completion-1:2.7-5.el8.noarch",
        "bash-0:4.4.19-7.el8.aarch64",
        "python2-tools-0:2.7.16-11.el8.aarch64",
        "python2-tools-0:2.7.16-11.el8.x86_64",
        "python3-ldap-0:3.1.0-4.el8.aarch64",
        "python3-ldap-0:3.1.0-4.el8.x86_64",
    }
    non_bm_rpms = {
        "bash-0:4.4.20-1.el8.aarch64",
        "python2-tools-0:2.7.18-1.module+el8.1.0+3568+bbd875cb.aarch64",
        "python2-tools-0:2.7.18-1.module+el8.1.0+3568+bbd875cb.x86_64",
    }
    mock_grft.side_effect = [bm_rpms, non_bm_rpms]

    default_modules._handle_collisions(mmd, ["aarch64", "x86_64"])

    mock_get_session.assert_called_once()
    xmd_mbs = mmd.get_xmd()["mbs"]
    assert set(xmd_mbs["ursine_rpms"]) == set([
        "bash-0:4.4.19-7.el8.aarch64",
        "python2-tools-0:2.7.16-11.el8.aarch64",
        "python2-tools-0:2.7.16-11.el8.x86_64",
    ])
    mock_grft.mock_calls == [
        call(
            mock_get_session.return_value,
            {"module-el-build"},
            ["aarch64", "x86_64"],
        ),
        call(
            mock_get_session.return_value,
            {"module-bash", "module-python27"},
            ["aarch64", "x86_64"],
        ),
    ]


@patch("module_build_service.scheduler.default_modules.koji_retrying_multicall_map")
@patch("module_build_service.scheduler.default_modules._get_rpms_in_external_repo")
def test_get_rpms_from_tags(mock_grier, mock_multicall_map):
    """
    Test the function queries Koji for the tags' and the tags' external repos' for RPMs.
    """
    mock_session = Mock()
    bash_tagged = [
        [
            {
                "arch": "aarch64",
                "epoch": 0,
                "name": "bash",
                "version": "4.4.20",
                "release": "1.module+el8.1.0+123+bbd875cb",
            },
            {
                "arch": "x86_64",
                "epoch": 0,
                "name": "bash",
                "version": "4.4.20",
                "release": "1.module+el8.1.0+123+bbd875cb",
            }
        ],
        None,
    ]
    python_tagged = [
        [
            {
                "arch": "aarch64",
                "epoch": 0,
                "name": "python2-tools",
                "version": "2.7.18",
                "release": "1.module+el8.1.0+3568+bbd875cb",
            },
            {
                "arch": "x86_64",
                "epoch": 0,
                "name": "python2-tools",
                "version": "2.7.18",
                "release": "1.module+el8.1.0+3568+bbd875cb",
            }
        ],
        None,
    ]
    bash_repos = []
    external_repo_url = "http://domain.local/repo/latest/$arch/"
    python_repos = [{
        "external_repo_id": "12",
        "tag_name": "module-python27",
        "url": external_repo_url,
    }]
    mock_multicall_map.side_effect = [
        [bash_tagged, python_tagged],
        [bash_repos, python_repos],
    ]
    mock_grier.return_value = {
        "python2-test-0:2.7.16-11.module+el8.1.0+3568+bbd875cb.aarch64",
        "python2-test-0:2.7.16-11.module+el8.1.0+3568+bbd875cb.x86_64",
    }

    tags = ["module-bash", "module-python27"]
    arches = ["aarch64", "x86_64"]
    rv = default_modules._get_rpms_from_tags(mock_session, tags, arches)

    expected = {
        "bash-0:4.4.20-1.module+el8.1.0+123+bbd875cb.aarch64",
        "bash-0:4.4.20-1.module+el8.1.0+123+bbd875cb.x86_64",
        "python2-tools-0:2.7.18-1.module+el8.1.0+3568+bbd875cb.aarch64",
        "python2-tools-0:2.7.18-1.module+el8.1.0+3568+bbd875cb.x86_64",
        "python2-test-0:2.7.16-11.module+el8.1.0+3568+bbd875cb.aarch64",
        "python2-test-0:2.7.16-11.module+el8.1.0+3568+bbd875cb.x86_64",
    }
    assert rv == expected
    assert mock_multicall_map.call_count == 2
    mock_grier.assert_called_once_with(external_repo_url, arches, "module-python27-12")


@patch("module_build_service.scheduler.default_modules.koji_retrying_multicall_map")
def test_get_rpms_from_tags_error_listTaggedRPMS(mock_multicall_map):
    """
    Test that an exception is raised if the listTaggedRPMS Koji query fails.
    """
    mock_session = Mock()
    mock_multicall_map.return_value = None

    tags = ["module-bash", "module-python27"]
    arches = ["aarch64", "x86_64"]
    expected = (
        "Getting the tagged RPMs of the following Koji tags failed: module-bash, module-python27"
    )
    with pytest.raises(RuntimeError, match=expected):
        default_modules._get_rpms_from_tags(mock_session, tags, arches)


@patch("module_build_service.scheduler.default_modules.koji_retrying_multicall_map")
def test_get_rpms_from_tags_error_getExternalRepoList(mock_multicall_map):
    """
    Test that an exception is raised if the getExternalRepoList Koji query fails.
    """
    mock_session = Mock()
    mock_multicall_map.side_effect = [[[[], []]], None]

    tags = ["module-bash", "module-python27"]
    arches = ["aarch64", "x86_64"]
    expected = (
        "Getting the external repos of the following Koji tags failed: module-bash, module-python27"
    )
    with pytest.raises(RuntimeError, match=expected):
        default_modules._get_rpms_from_tags(mock_session, tags, arches)


@patch("dnf.Base")
@patch("os.makedirs")
def test_get_rpms_in_external_repo(mock_makedirs, mock_dnf_base):
    """
    Test that DNF can query the external repos for the available packages.
    """
    RPM = namedtuple("RPM", ["arch", "epoch", "name", "release", "version"])
    mock_dnf_base.return_value.sack.query.return_value.available.return_value = [
        RPM("aarch64", 0, "python", "1.el8", "2.7"),
        RPM("aarch64", 0, "python", "1.el8", "3.7"),
        RPM("x86_64", 0, "python", "1.el8", "2.7"),
        RPM("x86_64", 0, "python", "1.el8", "3.7"),
    ]

    external_repo_url = "http://domain.local/repo/latest/$arch/"
    arches = ["aarch64", "x86_64"]
    cache_dir_name = "module-el-build-12"
    rv = default_modules._get_rpms_in_external_repo(external_repo_url, arches, cache_dir_name)

    expected = {
        "python-0:2.7-1.el8.aarch64",
        "python-0:3.7-1.el8.aarch64",
        "python-0:2.7-1.el8.x86_64",
        "python-0:3.7-1.el8.x86_64",
    }
    assert rv == expected


def test_get_rpms_in_external_repo_invalid_repo_url():
    """
    Test that an exception is raised when an invalid repo URL is passed in.
    """
    external_repo_url = "http://domain.local/repo/latest/"
    arches = ["aarch64", "x86_64"]
    cache_dir_name = "module-el-build-12"
    expected = (
        r"The external repo http://domain.local/repo/latest/ does not contain the \$arch variable"
    )
    with pytest.raises(ValueError, match=expected):
        default_modules._get_rpms_in_external_repo(external_repo_url, arches, cache_dir_name)


@patch("dnf.Base")
@patch("os.makedirs")
def test_get_rpms_in_external_repo_failed_to_load(mock_makedirs, mock_dnf_base):
    """
    Test that an exception is raised when an external repo can't be loaded.
    """
    class FakeRepo(dict):
        @staticmethod
        def add_new_repo(*args, **kwargs):
            pass

    mock_repo = Mock()
    mock_repo.load.side_effect = dnf.exceptions.RepoError("Failed")
    mock_dnf_base.return_value.repos = FakeRepo(repo_aarch64=mock_repo)

    external_repo_url = "http://domain.local/repo/latest/$arch/"
    arches = ["aarch64", "x86_64"]
    cache_dir_name = "module-el-build-12"
    expected = "Failed to load the external repo http://domain.local/repo/latest/aarch64/"
    with pytest.raises(RuntimeError, match=expected):
        default_modules._get_rpms_in_external_repo(external_repo_url, arches, cache_dir_name)


@patch("os.makedirs")
def test_get_rpms_in_external_repo_failed_to_create_cache(mock_makedirs):
    """
    Test that an exception is raised when the cache can't be created.
    """
    exc = OSError()
    exc.errno = errno.EACCES
    mock_makedirs.side_effect = exc

    external_repo_url = "http://domain.local/repo/latest/$arch/"
    arches = ["aarch64", "x86_64"]
    cache_dir_name = "module-el-build-12"
    expected = "The MBS cache is not writeable."
    with pytest.raises(RuntimeError, match=expected):
        default_modules._get_rpms_in_external_repo(external_repo_url, arches, cache_dir_name)
