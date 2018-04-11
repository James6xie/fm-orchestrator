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
import os
import math
import copy

import six
import pytest
import mock
import pdc_client.test_helpers

from module_build_service import glib, Modulemd


BASE_DIR = os.path.dirname(__file__)
STAGED_DATA_DIR = os.path.join(BASE_DIR, 'staged_data')

_mmd = Modulemd.Module().new_from_file(
    os.path.join(STAGED_DATA_DIR, 'platform.yaml'))
_mmd.upgrade()
PLATFORM_MODULEMD = _mmd.dumps()

_mmd2 = Modulemd.Module().new_from_file(
    os.path.join(STAGED_DATA_DIR, 'formatted_testmodule.yaml'))
_mmd2.upgrade()
TESTMODULE_MODULEMD = _mmd2.dumps()

_mmd3 = Modulemd.Module().new_from_file(
    os.path.join(STAGED_DATA_DIR, 'formatted_testmodule.yaml'))
_mmd3.upgrade()
_mmd3.set_context("c2c572ed")
TESTMODULE_MODULEMD_SECOND_CONTEXT = _mmd3.dumps()


class MockPDCFilterAPI(pdc_client.test_helpers.MockAPI):
    """ A modified pdc_client.test_helpers.MockAPI that supports basic filtering on GET requests
    """
    def _handle_get(self, filters):
        # Code taken from pdc_client/test_helpers.py
        data = self.endpoints[self.will_call]['GET']
        if callable(data):
            data = data()
        self.calls.setdefault(self.will_call, []).append(('GET', filters))
        page_size = filters.get('page_size', 20)
        # End of code taken from pdc_client/test_helpers.py

        if not isinstance(data, list):
            return data

        # Keep track of indexes to pop since we can't pop them during the loop
        indexes_to_pop = []
        for index, result in enumerate(data):
            for filter_key, filter_value in filters.items():
                if filter_key in ('page', 'page_size'):
                    continue
                if filter_key not in result:
                    raise ValueError('An unsupported filter was specified')
                # If it's a string, do a case insensitive match like the API does
                if isinstance(filter_value, six.string_types) and \
                        isinstance(result[filter_key], six.string_types):
                    if result[filter_key].lower() != filter_value.lower():
                        indexes_to_pop.append(index)
                        break
                else:
                    if result[filter_key] != filter_value:
                        indexes_to_pop.append(index)
                        break
        # Only copy the data if we need to modify it based on the filters
        if indexes_to_pop:
            rv_data = copy.deepcopy(data)
        else:
            rv_data = data
        # Remove all the results that didn't match the filter. This is reversed so the index
        # values remain valid as we pop them.
        for index in sorted(indexes_to_pop, reverse=True):
            rv_data.pop(index)

        if page_size <= 0:
            return rv_data

        # Code taken from pdc_client/test_helpers.py
        page = filters.get('page', 1)
        pages = int(math.ceil(float(len(rv_data)) / page_size))
        rv_data = rv_data[(page - 1) * page_size:(page - 1) * page_size + page_size]
        return {
            'count': len(rv_data),
            'next': None if (page == pages or not pages) else self._fmt_url(page + 1),
            'previous': None if (page == 1 or not pages) else self._fmt_url(page - 1),
            'results': rv_data
        }
        # End of code taken from pdc_client/test_helpers.py


# This is scoped to the function in case certain tests must alter PDC
@pytest.fixture
def pdc():
    # Mock the PDC client
    pdc = MockPDCFilterAPI()
    # TODO: change this to the modules API when PDC > 1.9.0 is released
    pdc.add_endpoint('unreleasedvariants', 'GET', [{
        'variant_id': 'platform',
        'variant_uid': 'platform-f28-3',
        'variant_name': 'platform',
        'variant_type': 'module',
        'variant_version': 'f28',
        'variant_release': '3',
        'variant_context': '00000000',
        'koji_tag': 'module-f28-build',
        'modulemd': PLATFORM_MODULEMD,
        'runtime_deps': [],
        'build_deps': [],
        'active': True,
        'rpms': []
    }])
    pdc_patcher = mock.patch('pdc_client.PDCClient', return_value=pdc)
    pdc_patcher.start()
    yield pdc
    pdc_patcher.stop()


@pytest.fixture(scope='function')
def pdc_module_inactive(pdc):
    pdc.endpoints['unreleasedvariants']['GET'].append({
        'variant_id': 'testmodule',
        'variant_uid': 'testmodule:master:20180205135154',
        'variant_name': 'testmodule',
        'variant_type': 'module',
        'variant_version': 'master',
        'variant_release': '20180205135154',
        'variant_context': '9c690d0e',
        'koji_tag': 'module-95b214a704c984be',
        'modulemd': TESTMODULE_MODULEMD,
        'runtime_deps': [
            {
                'dependency': 'platform',
                'stream': 'f28'
            }
        ],
        'build_deps': [
            {
                'dependency': 'platform',
                'stream': 'f28'
            }
        ],
        'rpms': [],
        'active': False,
    })
    return pdc


@pytest.fixture(scope='function')
def pdc_module_active(pdc_module_inactive):
    # Rename it for clarity
    pdc_module_active = pdc_module_inactive
    pdc_module_active.endpoints['unreleasedvariants']['GET'][-1].update({
        'active': True,
        'rpms': [
            'tangerine-0:0.22-6.module+0+814cfa39.noarch.rpm',
            'tangerine-0:0.22-6.module+0+814cfa39.src.rpm',
            'perl-Tangerine-0:0.22-2.module+0+814cfa39.noarch.rpm',
            'perl-Tangerine-0:0.22-2.module+0+814cfa39.src.rpm',
            'perl-List-Compare-0:0.53-8.module+0+814cfa39.noarch.rpm',
            'perl-List-Compare-0:0.53-8.module+0+814cfa39.src.rpm'
        ]
    })
    return pdc_module_active


@pytest.fixture(scope='function')
def pdc_module_active_two_contexts(pdc_module_active):
    # Rename it for clarity
    pdc_module_active_two_contexts = pdc_module_active
    pdc_module_active_two_contexts.endpoints['unreleasedvariants']['GET'][-1].update({
        'active': True,
        'rpms': [
            'tangerine-0:0.22-6.module+0+814cfa39.noarch.rpm',
            'tangerine-0:0.22-6.module+0+814cfa39.src.rpm',
            'perl-Tangerine-0:0.22-2.module+0+814cfa39.noarch.rpm',
            'perl-Tangerine-0:0.22-2.module+0+814cfa39.src.rpm',
            'perl-List-Compare-0:0.53-8.module+0+814cfa39.noarch.rpm',
            'perl-List-Compare-0:0.53-8.module+0+814cfa39.src.rpm'
        ]
    })
    pdc_module_active_two_contexts.endpoints['unreleasedvariants']['GET'].append(
        dict(pdc_module_active.endpoints['unreleasedvariants']['GET'][-1]))
    pdc_module_active_two_contexts.endpoints['unreleasedvariants']['GET'][-1].update({
        "variant_context": "c2c572ed",
        "modulemd": TESTMODULE_MODULEMD_SECOND_CONTEXT})
    return pdc_module_active_two_contexts


@pytest.fixture(scope='function')
def pdc_module_reuse(pdc_module_active):
    # Rename it for clarity
    pdc_module_reuse = pdc_module_active
    mmd = Modulemd.Module().new_from_string(TESTMODULE_MODULEMD)
    mmd.upgrade()
    mmd.set_version(20170219191323)
    xmd = glib.from_variant_dict(mmd.get_xmd())
    xmd['mbs']['scmurl'] = 'git://pkgs.stg.fedoraproject.org/modules/testmodule.git?#ff1ea79'
    xmd['mbs']['commit'] = 'ff1ea79fc952143efeed1851aa0aa006559239ba'
    mmd.set_xmd(glib.dict_values(xmd))
    pdc_module_reuse.endpoints['unreleasedvariants']['GET'].append(
        copy.deepcopy(pdc_module_reuse.endpoints['unreleasedvariants']['GET'][-1]))
    pdc_module_reuse.endpoints['unreleasedvariants']['GET'][-1].update({
        'variant_uid': 'testmodule:master:{0}'.format(mmd.get_version()),
        'variant_release': str(mmd.get_version()),
        'variant_context': '7c29193d',
        'modulemd': mmd.dumps(),
        'koji_tag': 'module-de3adf79caf3e1b8'
    })

    mmd.set_version(20180205135154)
    xmd = glib.from_variant_dict(mmd.get_xmd())
    xmd['mbs']['scmurl'] = 'git://pkgs.stg.fedoraproject.org/modules/testmodule.git?#55f4a0a'
    xmd['mbs']['commit'] = '55f4a0a2e6cc255c88712a905157ab39315b8fd8'
    mmd.set_xmd(glib.dict_values(xmd))
    pdc_module_reuse.endpoints['unreleasedvariants']['GET'].append(
        copy.deepcopy(pdc_module_reuse.endpoints['unreleasedvariants']['GET'][-1]))
    pdc_module_reuse.endpoints['unreleasedvariants']['GET'][-1].update({
        'variant_uid': 'testmodule:master:{0}'.format(mmd.get_version()),
        'variant_release': str(mmd.get_version()),
        'modulemd': mmd.dumps(),
        'koji_tag': 'module-fe3adf73caf3e1b7',
        'rpms': [],
        'active': False
    })
    return pdc_module_reuse
