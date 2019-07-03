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

import textwrap

from mock import patch
import pytest
import requests

from module_build_service.models import ModuleBuild
from module_build_service.scheduler.default_modules import add_default_modules
from module_build_service.utils.general import load_mmd, mmd_to_str
from tests import clean_database, make_module, read_staged_data


@patch("module_build_service.scheduler.default_modules.requests_session")
def test_add_default_modules(mock_requests_session, db_session):
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
    add_default_modules(db_session, mmd)
    # Make sure that the default modules were added. ruby:2.6 will be ignored since it's not in
    # the database
    assert set(mmd.get_xmd()["mbs"]["buildrequires"].keys()) == {"nodejs", "platform", "python"}
    mock_requests_session.get.assert_called_once_with(default_modules_url, timeout=10)


@patch("module_build_service.scheduler.default_modules.requests_session")
def test_add_default_modules_not_linked(mock_requests_session, db_session):
    """
    Test that no default modules are added when they aren't linked from the base module.
    """
    clean_database()
    mmd = load_mmd(read_staged_data("formatted_testmodule.yaml"))
    assert set(mmd.get_xmd()["mbs"]["buildrequires"].keys()) == {"platform"}
    add_default_modules(db_session, mmd)
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
        add_default_modules(db_session, mmd)


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
        add_default_modules(db_session, mmd)
