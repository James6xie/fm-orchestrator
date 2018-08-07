# Copyright (c) 2016  Red Hat, Inc.
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
# Written by Matt Prahl <mprahl@redhat.com

import os
from datetime import datetime, timedelta
from mock import patch
import time
import hashlib
from traceback import extract_stack

import koji
import module_build_service
from module_build_service import db
from module_build_service.utils import get_rpm_release, import_mmd, load_mmd
from module_build_service.config import init_config
from module_build_service.models import ModuleBuild, ComponentBuild, make_session, BUILD_STATES
from module_build_service import glib, Modulemd


base_dir = os.path.dirname(__file__)
app = module_build_service.app
conf = init_config(app)


def patch_config():
    # add test builders for all resolvers
    with_test_builders = dict()
    for k, v in module_build_service.config.SUPPORTED_RESOLVERS.items():
        v['builders'].extend(['test', 'testlocal'])
        with_test_builders[k] = v
    patch("module_build_service.config.SUPPORTED_RESOLVERS", with_test_builders)


patch_config()


def patch_zeromq_time_sleep():
    """
    We use moksha.hub in some tests. We used dummy zerombq backend which
    connects to /dev/null, but zeromq.py contains time.sleep(1) to ensure
    that sockets are listening properly. This is not needed for our dummy
    use-case and it slows down tests.

    This method patches time.sleep called from "zeromq.py" file to be noop,
    but calls the real time.sleep otherwise.
    """
    global _orig_time_sleep
    _orig_time_sleep = time.sleep

    def mocked_time_sleep(n):
        global _orig_time_sleep
        if n == 1:
            tb = extract_stack()
            try:
                if tb[-4][0].endswith("zeromq.py"):
                    return
            except IndexError:
                pass
        _orig_time_sleep(n)

    ts = patch("time.sleep").start()
    ts.side_effect = mocked_time_sleep


patch_zeromq_time_sleep()


def clean_database(add_platform_module=True):
    db.session.commit()
    db.drop_all()
    db.create_all()
    if add_platform_module:
        mmd = load_mmd(os.path.join(base_dir, 'staged_data', 'platform.yaml'), True)
        import_mmd(db.session, mmd)


def init_data(data_size=10, contexts=False):
    """
    Creates data_size * 3 modules in database in different states and
    with different component builds. See _populate_data for more info.

    :param bool contexts: If True, multiple streams and contexts in each stream
        are generated for 'nginx' module.
    """
    clean_database()
    with make_session(conf) as session:
        _populate_data(session, data_size, contexts=contexts)


def _populate_data(session, data_size=10, contexts=False):
    num_contexts = 2 if contexts else 1
    for index in range(data_size):
        for context in range(num_contexts):
            build_one = ModuleBuild()
            build_one.name = 'nginx'
            build_one.stream = '1'
            build_one.version = 2 + index
            build_one.state = BUILD_STATES['ready']
            if contexts:
                build_one.stream = str(index)
                unique_hash = hashlib.sha1("%s:%s:%d:%d" % (
                    build_one.name, build_one.stream, build_one.version, context)).hexdigest()
                build_one.build_context = unique_hash
                build_one.runtime_context = unique_hash
                build_one.ref_build_context = unique_hash
                combined_hashes = '{0}:{1}'.format(unique_hash, unique_hash)
                build_one.context = hashlib.sha1(combined_hashes).hexdigest()[:8]
            with open(os.path.join(base_dir, "staged_data", "nginx_mmd.yaml")) as mmd:
                build_one.modulemd = mmd.read()
            build_one.koji_tag = 'module-nginx-1.2'
            build_one.scmurl = ('git://pkgs.domain.local/modules/nginx?'
                                '#ba95886c7a443b36a9ce31abda1f9bef22f2f8c9')
            build_one.batch = 2
            # https://www.youtube.com/watch?v=iQGwrK_yDEg
            build_one.owner = 'Moe Szyslak'
            build_one.time_submitted = \
                datetime(2016, 9, 3, 11, 23, 20) + timedelta(minutes=(index * 10))
            build_one.time_modified = \
                datetime(2016, 9, 3, 11, 25, 32) + timedelta(minutes=(index * 10))
            build_one.time_completed = \
                datetime(2016, 9, 3, 11, 25, 32) + timedelta(minutes=(index * 10))
            build_one.rebuild_strategy = 'changed-and-after'
            session.add(build_one)
            session.commit()
            build_one_component_release = get_rpm_release(build_one)

            component_one_build_one = ComponentBuild()
            component_one_build_one.package = 'nginx'
            component_one_build_one.scmurl = \
                ('git://pkgs.domain.local/rpms/nginx?'
                 '#ga95886c8a443b36a9ce31abda1f9bed22f2f8c3')
            component_one_build_one.format = 'rpms'
            component_one_build_one.task_id = 12312345 + index
            component_one_build_one.state = koji.BUILD_STATES['COMPLETE']
            component_one_build_one.nvr = 'nginx-1.10.1-2.{0}'.format(build_one_component_release)
            component_one_build_one.batch = 1
            component_one_build_one.module_id = 2 + index * 3
            component_one_build_one.tagged = True
            component_one_build_one.tagged_in_final = True

            component_two_build_one = ComponentBuild()
            component_two_build_one.package = 'module-build-macros'
            component_two_build_one.scmurl = \
                ('/tmp/module_build_service-build-macrosWZUPeK/SRPMS/'
                 'module-build-macros-0.1-1.module_nginx_1_2.src.rpm')
            component_two_build_one.format = 'rpms'
            component_two_build_one.task_id = 12312321 + index
            component_two_build_one.state = koji.BUILD_STATES['COMPLETE']
            component_two_build_one.nvr = \
                'module-build-macros-01-1.{0}'.format(build_one_component_release)
            component_two_build_one.batch = 2
            component_two_build_one.module_id = 2 + index * 3
            component_two_build_one.tagged = True
            component_two_build_one.tagged_in_final = True

        build_two = ModuleBuild()
        build_two.name = 'postgressql'
        build_two.stream = '1'
        build_two.version = 2 + index
        build_two.state = BUILD_STATES['done']
        build_two.modulemd = ''  # Skipping since no tests rely on it
        build_two.koji_tag = 'module-postgressql-1.2'
        build_two.scmurl = ('git://pkgs.domain.local/modules/postgressql?'
                            '#aa95886c7a443b36a9ce31abda1f9bef22f2f8c9')
        build_two.batch = 2
        build_two.owner = 'some_user'
        build_two.time_submitted = \
            datetime(2016, 9, 3, 12, 25, 33) + timedelta(minutes=(index * 10))
        build_two.time_modified = \
            datetime(2016, 9, 3, 12, 27, 19) + timedelta(minutes=(index * 10))
        build_two.time_completed = \
            datetime(2016, 9, 3, 11, 27, 19) + timedelta(minutes=(index * 10))
        build_two.rebuild_strategy = 'changed-and-after'
        session.add(build_two)
        session.commit()
        build_two_component_release = get_rpm_release(build_two)

        component_one_build_two = ComponentBuild()
        component_one_build_two.package = 'postgresql'
        component_one_build_two.scmurl = \
            ('git://pkgs.domain.local/rpms/postgresql?'
             '#dc95586c4a443b26a9ce38abda1f9bed22f2f8c3')
        component_one_build_two.format = 'rpms'
        component_one_build_two.task_id = 2433433 + index
        component_one_build_two.state = koji.BUILD_STATES['COMPLETE']
        component_one_build_two.nvr = 'postgresql-9.5.3-4.{0}'.format(build_two_component_release)
        component_one_build_two.batch = 2
        component_one_build_two.module_id = 3 + index * 3
        component_one_build_two.tagged = True
        component_one_build_two.tagged_in_final = True

        component_two_build_two = ComponentBuild()
        component_two_build_two.package = 'module-build-macros'
        component_two_build_two.scmurl = \
            ('/tmp/module_build_service-build-macrosWZUPeK/SRPMS/'
             'module-build-macros-0.1-1.module_postgresql_1_2.src.rpm')
        component_two_build_two.format = 'rpms'
        component_two_build_two.task_id = 47383993 + index
        component_two_build_two.state = koji.BUILD_STATES['COMPLETE']
        component_two_build_two.nvr = \
            'module-build-macros-01-1.{0}'.format(build_two_component_release)
        component_two_build_two.batch = 1
        component_two_build_two.module_id = 3 + index * 3
        component_one_build_two.tagged = True
        component_one_build_two.build_time_only = True

        build_three = ModuleBuild()
        build_three.name = 'testmodule'
        build_three.stream = '4.3.43'
        build_three.version = 6 + index
        build_three.state = BUILD_STATES['wait']
        build_three.modulemd = ''  # Skipping because no tests rely on it
        build_three.koji_tag = None
        build_three.scmurl = ('git://pkgs.domain.local/modules/testmodule?'
                              '#ca95886c7a443b36a9ce31abda1f9bef22f2f8c9')
        build_three.batch = 0
        build_three.owner = 'some_other_user'
        build_three.time_submitted = \
            datetime(2016, 9, 3, 12, 28, 33) + timedelta(minutes=(index * 10))
        build_three.time_modified = \
            datetime(2016, 9, 3, 12, 28, 40) + timedelta(minutes=(index * 10))
        build_three.time_completed = None
        build_three.rebuild_strategy = 'changed-and-after'
        session.add(build_three)
        session.commit()
        build_three_component_release = get_rpm_release(build_three)

        component_one_build_three = ComponentBuild()
        component_one_build_three.package = 'rubygem-rails'
        component_one_build_three.scmurl = \
            ('git://pkgs.domain.local/rpms/rubygem-rails?'
             '#dd55886c4a443b26a9ce38abda1f9bed22f2f8c3')
        component_one_build_three.format = 'rpms'
        component_one_build_three.task_id = 2433433 + index
        component_one_build_three.state = koji.BUILD_STATES['FAILED']
        component_one_build_three.nvr = \
            'postgresql-9.5.3-4.{0}'.format(build_three_component_release)
        component_one_build_three.batch = 2
        component_one_build_three.module_id = 4 + index * 3

        component_two_build_three = ComponentBuild()
        component_two_build_three.package = 'module-build-macros'
        component_two_build_three.scmurl = \
            ('/tmp/module_build_service-build-macrosWZUPeK/SRPMS/'
             'module-build-macros-0.1-1.module_testmodule_1_2.src.rpm')
        component_two_build_three.format = 'rpms'
        component_two_build_three.task_id = 47383993 + index
        component_two_build_three.state = koji.BUILD_STATES['COMPLETE']
        component_two_build_three.nvr = \
            'module-build-macros-01-1.{0}'.format(build_three_component_release)
        component_two_build_three.batch = 1
        component_two_build_three.module_id = 4 + index * 3
        component_two_build_three.tagged = True
        component_two_build_three.build_time_only = True

        session.add(component_one_build_one)
        session.add(component_two_build_one)
        session.add(component_one_build_two)
        session.add(component_two_build_two)
        session.add(component_one_build_three)
        session.add(component_two_build_three)
        session.commit()


def scheduler_init_data(tangerine_state=None):
    """ Creates a testmodule in the building state with all the components in the same batch
    """
    clean_database()

    current_dir = os.path.dirname(__file__)
    formatted_testmodule_yml_path = os.path.join(
        current_dir, 'staged_data', 'formatted_testmodule.yaml')
    mmd = Modulemd.Module().new_from_file(formatted_testmodule_yml_path)
    mmd.upgrade()
    mmd.get_rpm_components()['tangerine'].set_buildorder(0)

    build_one = module_build_service.models.ModuleBuild()
    build_one.name = 'testmodule'
    build_one.stream = 'master'
    build_one.version = 20170109091357
    build_one.state = BUILD_STATES['build']
    build_one.build_context = 'ac4de1c346dcf09ce77d38cd4e75094ec1c08eb0'
    build_one.runtime_context = 'ac4de1c346dcf09ce77d38cd4e75094ec1c08eb0'
    build_one.context = '7c29193d'
    build_one.koji_tag = 'module-testmodule-master-20170109091357-7c29193d'
    build_one.scmurl = 'git://pkgs.stg.fedoraproject.org/modules/testmodule.git?#ff1ea79'
    if tangerine_state:
        build_one.batch = 3
    else:
        build_one.batch = 2
    # https://www.youtube.com/watch?v=iOKymYVSaJE
    build_one.owner = 'Buzz Lightyear'
    build_one.time_submitted = datetime(2017, 2, 15, 16, 8, 18)
    build_one.time_modified = datetime(2017, 2, 15, 16, 19, 35)
    build_one.rebuild_strategy = 'changed-and-after'
    build_one.modulemd = mmd.dumps()
    build_one_component_release = get_rpm_release(build_one)

    component_one_build_one = module_build_service.models.ComponentBuild()
    component_one_build_one.package = 'perl-Tangerine'
    component_one_build_one.scmurl = \
        ('git://pkgs.fedoraproject.org/rpms/perl-Tangerine'
         '?#4ceea43add2366d8b8c5a622a2fb563b625b9abf')
    component_one_build_one.format = 'rpms'
    component_one_build_one.task_id = 90276227
    component_one_build_one.state = koji.BUILD_STATES['COMPLETE']
    component_one_build_one.nvr = \
        'perl-Tangerine-0.23-1.{0}'.format(build_one_component_release)
    component_one_build_one.batch = 2
    component_one_build_one.module_id = 2
    component_one_build_one.ref = '4ceea43add2366d8b8c5a622a2fb563b625b9abf'
    component_one_build_one.tagged = True
    component_one_build_one.tagged_in_final = True

    component_two_build_one = module_build_service.models.ComponentBuild()
    component_two_build_one.package = 'perl-List-Compare'
    component_two_build_one.scmurl = \
        ('git://pkgs.fedoraproject.org/rpms/perl-List-Compare'
         '?#76f9d8c8e87eed0aab91034b01d3d5ff6bd5b4cb')
    component_two_build_one.format = 'rpms'
    component_two_build_one.task_id = 90276228
    component_two_build_one.state = koji.BUILD_STATES['COMPLETE']
    component_two_build_one.nvr = \
        'perl-List-Compare-0.53-5.{0}'.format(build_one_component_release)
    component_two_build_one.batch = 2
    component_two_build_one.module_id = 2
    component_two_build_one.ref = '76f9d8c8e87eed0aab91034b01d3d5ff6bd5b4cb'
    component_two_build_one.tagged = True
    component_two_build_one.tagged_in_final = True

    component_three_build_one = module_build_service.models.ComponentBuild()
    component_three_build_one.package = 'tangerine'
    component_three_build_one.scmurl = \
        ('git://pkgs.fedoraproject.org/rpms/tangerine'
         '?#fbed359411a1baa08d4a88e0d12d426fbf8f602c')
    component_three_build_one.format = 'rpms'
    component_three_build_one.batch = 3
    component_three_build_one.module_id = 2
    component_three_build_one.ref = 'fbed359411a1baa08d4a88e0d12d426fbf8f602c'
    component_three_build_one.state = tangerine_state
    if tangerine_state:
        component_three_build_one.task_id = 90276315
        component_three_build_one.nvr = \
            'tangerine-0.22-3.{0}'.format(build_one_component_release)
    if tangerine_state == koji.BUILD_STATES['COMPLETE']:
        component_three_build_one.tagged = True
        component_three_build_one.tagged_in_final = True

    component_four_build_one = module_build_service.models.ComponentBuild()
    component_four_build_one.package = 'module-build-macros'
    component_four_build_one.scmurl = \
        ('/tmp/module_build_service-build-macrosqr4AWH/SRPMS/module-build-'
         'macros-0.1-1.module_testmodule_master_20170109091357.src.rpm')
    component_four_build_one.format = 'rpms'
    component_four_build_one.task_id = 90276181
    component_four_build_one.state = koji.BUILD_STATES['COMPLETE']
    component_four_build_one.nvr = \
        'module-build-macros-0.1-1.{0}'.format(build_one_component_release)
    component_four_build_one.batch = 1
    component_four_build_one.module_id = 2
    component_four_build_one.tagged = True
    component_four_build_one.build_time_only = True

    with make_session(conf) as session:
        session.add(build_one)
        session.add(component_one_build_one)
        session.add(component_two_build_one)
        session.add(component_three_build_one)
        session.add(component_four_build_one)
        session.commit()


def reuse_component_init_data():
    clean_database()

    current_dir = os.path.dirname(__file__)
    formatted_testmodule_yml_path = os.path.join(
        current_dir, 'staged_data', 'formatted_testmodule.yaml')
    mmd = Modulemd.Module().new_from_file(formatted_testmodule_yml_path)
    mmd.upgrade()

    build_one = module_build_service.models.ModuleBuild()
    build_one.name = 'testmodule'
    build_one.stream = 'master'
    build_one.version = 20170109091357
    build_one.state = BUILD_STATES['ready']
    build_one.ref_build_context = 'ac4de1c346dcf09ce77d38cd4e75094ec1c08eb0'
    build_one.runtime_context = 'ac4de1c346dcf09ce77d38cd4e75094ec1c08eb0'
    build_one.build_context = 'ac4de1c346dcf09ce77d38cd4e75094ec1c08eb1'
    build_one.context = '78e4a6fd'
    build_one.koji_tag = 'module-testmodule-master-20170109091357-78e4a6fd'
    build_one.scmurl = 'git://pkgs.stg.fedoraproject.org/modules/testmodule.git?#ff1ea79'
    build_one.batch = 3
    build_one.owner = 'Tom Brady'
    build_one.time_submitted = datetime(2017, 2, 15, 16, 8, 18)
    build_one.time_modified = datetime(2017, 2, 15, 16, 19, 35)
    build_one.time_completed = datetime(2017, 2, 15, 16, 19, 35)
    build_one.rebuild_strategy = 'changed-and-after'
    build_one_component_release = get_rpm_release(build_one)
    mmd.set_version(build_one.version)
    xmd = glib.from_variant_dict(mmd.get_xmd())
    xmd['mbs']['scmurl'] = build_one.scmurl
    xmd['mbs']['commit'] = 'ff1ea79fc952143efeed1851aa0aa006559239ba'
    mmd.set_xmd(glib.dict_values(xmd))
    build_one.modulemd = mmd.dumps()

    component_one_build_one = module_build_service.models.ComponentBuild()
    component_one_build_one.package = 'perl-Tangerine'
    component_one_build_one.scmurl = \
        ('git://pkgs.fedoraproject.org/rpms/perl-Tangerine'
         '?#4ceea43add2366d8b8c5a622a2fb563b625b9abf')
    component_one_build_one.format = 'rpms'
    component_one_build_one.task_id = 90276227
    component_one_build_one.state = koji.BUILD_STATES['COMPLETE']
    component_one_build_one.nvr = \
        'perl-Tangerine-0.23-1.{0}'.format(build_one_component_release)
    component_one_build_one.batch = 2
    component_one_build_one.module_id = 2
    component_one_build_one.ref = '4ceea43add2366d8b8c5a622a2fb563b625b9abf'
    component_one_build_one.tagged = True
    component_one_build_one.tagged_in_final = True
    component_two_build_one = module_build_service.models.ComponentBuild()
    component_two_build_one.package = 'perl-List-Compare'
    component_two_build_one.scmurl = \
        ('git://pkgs.fedoraproject.org/rpms/perl-List-Compare'
         '?#76f9d8c8e87eed0aab91034b01d3d5ff6bd5b4cb')
    component_two_build_one.format = 'rpms'
    component_two_build_one.task_id = 90276228
    component_two_build_one.state = koji.BUILD_STATES['COMPLETE']
    component_two_build_one.nvr = \
        'perl-List-Compare-0.53-5.{0}'.format(build_one_component_release)
    component_two_build_one.batch = 2
    component_two_build_one.module_id = 2
    component_two_build_one.ref = '76f9d8c8e87eed0aab91034b01d3d5ff6bd5b4cb'
    component_two_build_one.tagged = True
    component_two_build_one.tagged_in_final = True
    component_three_build_one = module_build_service.models.ComponentBuild()
    component_three_build_one.package = 'tangerine'
    component_three_build_one.scmurl = \
        ('git://pkgs.fedoraproject.org/rpms/tangerine'
         '?#fbed359411a1baa08d4a88e0d12d426fbf8f602c')
    component_three_build_one.format = 'rpms'
    component_three_build_one.task_id = 90276315
    component_three_build_one.state = koji.BUILD_STATES['COMPLETE']
    component_three_build_one.nvr = \
        'tangerine-0.22-3.{0}'.format(build_one_component_release)
    component_three_build_one.batch = 3
    component_three_build_one.module_id = 2
    component_three_build_one.ref = 'fbed359411a1baa08d4a88e0d12d426fbf8f602c'
    component_three_build_one.tagged = True
    component_three_build_one.tagged_in_final = True
    component_four_build_one = module_build_service.models.ComponentBuild()
    component_four_build_one.package = 'module-build-macros'
    component_four_build_one.scmurl = \
        ('/tmp/module_build_service-build-macrosqr4AWH/SRPMS/module-build-'
         'macros-0.1-1.module_testmodule_master_20170109091357.src.rpm')
    component_four_build_one.format = 'rpms'
    component_four_build_one.task_id = 90276181
    component_four_build_one.state = koji.BUILD_STATES['COMPLETE']
    component_four_build_one.nvr = \
        'module-build-macros-0.1-1.{0}'.format(build_one_component_release)
    component_four_build_one.batch = 1
    component_four_build_one.module_id = 2
    component_four_build_one.tagged = True
    component_four_build_one.build_time_only = True

    build_two = module_build_service.models.ModuleBuild()
    build_two.name = 'testmodule'
    build_two.stream = 'master'
    build_two.version = 20170219191323
    build_two.state = BUILD_STATES['build']
    build_two.ref_build_context = 'ac4de1c346dcf09ce77d38cd4e75094ec1c08eb0'
    build_two.runtime_context = 'ac4de1c346dcf09ce77d38cd4e75094ec1c08eb0'
    build_two.build_context = 'ac4de1c346dcf09ce77d38cd4e75094ec1c08eb1'
    build_two.context = 'c40c156c'
    build_two.koji_tag = 'module-testmodule-master-20170219191323-c40c156c'
    build_two.scmurl = 'git://pkgs.stg.fedoraproject.org/modules/testmodule.git?#55f4a0a'
    build_two.batch = 1
    build_two.owner = 'Tom Brady'
    build_two.time_submitted = datetime(2017, 2, 19, 16, 8, 18)
    build_two.time_modified = datetime(2017, 2, 19, 16, 8, 18)
    build_two.rebuild_strategy = 'changed-and-after'
    build_two_component_release = get_rpm_release(build_two)
    mmd.set_version(build_one.version)
    xmd = glib.from_variant_dict(mmd.get_xmd())
    xmd['mbs']['scmurl'] = build_one.scmurl
    xmd['mbs']['commit'] = '55f4a0a2e6cc255c88712a905157ab39315b8fd8'
    mmd.set_xmd(glib.dict_values(xmd))
    build_two.modulemd = mmd.dumps()

    component_one_build_two = module_build_service.models.ComponentBuild()
    component_one_build_two.package = 'perl-Tangerine'
    component_one_build_two.scmurl = \
        ('git://pkgs.fedoraproject.org/rpms/perl-Tangerine'
         '?#4ceea43add2366d8b8c5a622a2fb563b625b9abf')
    component_one_build_two.format = 'rpms'
    component_one_build_two.batch = 2
    component_one_build_two.module_id = 3
    component_one_build_two.ref = '4ceea43add2366d8b8c5a622a2fb563b625b9abf'
    component_two_build_two = module_build_service.models.ComponentBuild()
    component_two_build_two.package = 'perl-List-Compare'
    component_two_build_two.scmurl = \
        ('git://pkgs.fedoraproject.org/rpms/perl-List-Compare'
         '?#76f9d8c8e87eed0aab91034b01d3d5ff6bd5b4cb')
    component_two_build_two.format = 'rpms'
    component_two_build_two.batch = 2
    component_two_build_two.module_id = 3
    component_two_build_two.ref = '76f9d8c8e87eed0aab91034b01d3d5ff6bd5b4cb'
    component_three_build_two = module_build_service.models.ComponentBuild()
    component_three_build_two.package = 'tangerine'
    component_three_build_two.scmurl = \
        ('git://pkgs.fedoraproject.org/rpms/tangerine'
         '?#fbed359411a1baa08d4a88e0d12d426fbf8f602c')
    component_three_build_two.format = 'rpms'
    component_three_build_two.batch = 3
    component_three_build_two.module_id = 3
    component_three_build_two.ref = 'fbed359411a1baa08d4a88e0d12d426fbf8f602c'
    component_four_build_two = module_build_service.models.ComponentBuild()
    component_four_build_two.package = 'module-build-macros'
    component_four_build_two.scmurl = \
        ('/tmp/module_build_service-build-macrosqr4AWH/SRPMS/module-build-'
         'macros-0.1-1.module_testmodule_master_20170219191323.src.rpm')
    component_four_build_two.format = 'rpms'
    component_four_build_two.task_id = 90276186
    component_four_build_two.state = koji.BUILD_STATES['COMPLETE']
    component_four_build_two.nvr = \
        'module-build-macros-0.1-1.{0}'.format(build_two_component_release)
    component_four_build_two.batch = 1
    component_four_build_two.module_id = 3
    component_four_build_two.tagged = True
    component_four_build_two.build_time_only = True

    with make_session(conf) as session:
        session.add(build_one)
        session.add(component_one_build_one)
        session.add(component_two_build_one)
        session.add(component_three_build_one)
        session.add(component_four_build_one)
        session.add(build_two)
        session.add(component_one_build_two)
        session.add(component_two_build_two)
        session.add(component_three_build_two)
        session.add(component_four_build_two)
        session.commit()


def reuse_shared_userspace_init_data():
    clean_database()

    with make_session(conf) as session:
        # Create shared-userspace-570, state is COMPLETE, all components
        # are properly built.
        current_dir = os.path.dirname(__file__)
        formatted_testmodule_yml_path = os.path.join(
            current_dir, 'staged_data', 'shared-userspace-570.yaml')
        mmd = Modulemd.Module().new_from_file(formatted_testmodule_yml_path)
        mmd.upgrade()

        build_one = module_build_service.models.ModuleBuild()
        build_one.name = mmd.get_name()
        build_one.stream = mmd.get_stream()
        build_one.version = mmd.get_version()
        build_one.build_context = 'e046b867a400a06a3571f3c71142d497895fefbe'
        build_one.runtime_context = '50dd3eb5dde600d072e45d4120e1548ce66bc94a'
        build_one.state = BUILD_STATES['ready']
        build_one.modulemd = mmd.dumps()
        build_one.koji_tag = 'module-shared-userspace-f26-20170601141014-75f92abb'
        build_one.scmurl = ('git://pkgs.stg.fedoraproject.org/modules/testmodule.'
                            'git?#7fea453')
        build_one.batch = 16
        build_one.owner = 'Tom Brady'
        build_one.time_submitted = datetime(2017, 2, 15, 16, 8, 18)
        build_one.time_modified = datetime(2017, 2, 15, 16, 19, 35)
        build_one.time_completed = datetime(2017, 2, 15, 16, 19, 35)
        build_one.rebuild_strategy = 'changed-and-after'

        session.add(build_one)

        components = mmd.get_rpm_components().values()
        components.sort(key=lambda x: x.get_buildorder())
        previous_buildorder = None
        batch = 1
        for pkg in components:
            # Increment the batch number when buildorder increases.
            if previous_buildorder != pkg.get_buildorder():
                previous_buildorder = pkg.get_buildorder()
                batch += 1

            pkgref = mmd.get_xmd()['mbs']['rpms'][pkg.get_name()]['ref']
            full_url = pkg.get_repository() + "?#" + pkgref
            build = module_build_service.models.ComponentBuild(
                module_id=2,
                package=pkg.get_name(),
                format="rpms",
                scmurl=full_url,
                batch=batch,
                ref=pkgref,
                state=1,
                tagged=True,
                tagged_in_final=True
            )
            session.add(build)

        # Create shared-userspace-577, state is WAIT, no component built
        formatted_testmodule_yml_path = os.path.join(
            current_dir, 'staged_data', 'shared-userspace-577.yaml')
        mmd2 = Modulemd.Module().new_from_file(formatted_testmodule_yml_path)
        mmd2.upgrade()

        build_one = module_build_service.models.ModuleBuild()
        build_one.name = mmd2.get_name()
        build_one.stream = mmd2.get_stream()
        build_one.version = mmd2.get_version()
        build_one.build_context = 'e046b867a400a06a3571f3c71142d497895fefbe'
        build_one.runtime_context = '50dd3eb5dde600d072e45d4120e1548ce66bc94a'
        build_one.state = BUILD_STATES['done']
        build_one.modulemd = mmd2.dumps()
        build_one.koji_tag = 'module-shared-userspace-f26-20170605091544-75f92abb'
        build_one.scmurl = ('git://pkgs.stg.fedoraproject.org/modules/testmodule.'
                            'git?#7fea453')
        build_one.batch = 0
        build_one.owner = 'Tom Brady'
        build_one.time_submitted = datetime(2017, 2, 15, 16, 8, 18)
        build_one.time_modified = datetime(2017, 2, 15, 16, 19, 35)
        build_one.time_completed = datetime(2017, 2, 15, 16, 19, 35)
        build_one.rebuild_strategy = 'changed-and-after'

        session.add(build_one)

        components2 = mmd2.get_rpm_components().values()
        # Store components to database in different order than for 570 to
        # reproduce the reusing issue.
        components2.sort(key=lambda x: len(x.get_name()))
        components2.sort(key=lambda x: x.get_buildorder())
        previous_buildorder = None
        batch = 1
        for pkg in components2:
            # Increment the batch number when buildorder increases.
            if previous_buildorder != pkg.get_buildorder():
                previous_buildorder = pkg.get_buildorder()
                batch += 1

            pkgref = mmd2.get_xmd()['mbs']['rpms'][pkg.get_name()]['ref']
            full_url = pkg.get_repository() + "?#" + pkgref
            build = module_build_service.models.ComponentBuild(
                module_id=3,
                package=pkg.get_name(),
                format="rpms",
                scmurl=full_url,
                batch=batch,
                ref=pkgref
            )
            session.add(build)
