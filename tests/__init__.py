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
import tarfile
import module_build_service

from datetime import datetime, timedelta
from module_build_service import db
from module_build_service.config import init_config
from module_build_service.models import ModuleBuild, ComponentBuild, make_session
import modulemd
import module_build_service.pdc

base_dir = os.path.dirname(__file__)
app = module_build_service.app
conf = init_config(app)


def uncompress_vcrpy_cassette():
    cassette_dir = base_dir + '/vcr-request-data/'
    if not os.path.exists(cassette_dir):
        archive = cassette_dir.rstrip('/') + ".tar.gz"
        with tarfile.open(archive, mode='r:gz') as t:
            t.extractall(base_dir)


uncompress_vcrpy_cassette()


def clean_database():
    db.session.remove()
    db.drop_all()
    db.create_all()


def init_data():
    clean_database()
    for index in range(10):
        build_one = ModuleBuild()
        build_one.name = 'nginx'
        build_one.stream = '1'
        build_one.version = 2
        build_one.state = 3
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

        component_one_build_one = ComponentBuild()
        component_one_build_one.package = 'nginx'
        component_one_build_one.scmurl = \
            ('git://pkgs.domain.local/rpms/nginx?'
             '#ga95886c8a443b36a9ce31abda1f9bed22f2f8c3')
        component_one_build_one.format = 'rpms'
        component_one_build_one.task_id = 12312345 + index
        component_one_build_one.state = 1
        component_one_build_one.nvr = 'nginx-1.10.1-2.module_nginx_1_2'
        component_one_build_one.batch = 1
        component_one_build_one.module_id = 1 + index * 3
        component_one_build_one.tagged = True
        component_one_build_one.tagged_in_final = True

        component_two_build_one = ComponentBuild()
        component_two_build_one.package = 'module-build-macros'
        component_two_build_one.scmurl = \
            ('/tmp/module_build_service-build-macrosWZUPeK/SRPMS/'
             'module-build-macros-0.1-1.module_nginx_1_2.src.rpm')
        component_two_build_one.format = 'rpms'
        component_two_build_one.task_id = 12312321 + index
        component_two_build_one.state = 1
        component_two_build_one.nvr = \
            'module-build-macros-01-1.module_nginx_1_2'
        component_two_build_one.batch = 2
        component_two_build_one.module_id = 1 + index * 3
        component_two_build_one.tagged = True
        component_two_build_one.tagged_in_final = True

        build_two = ModuleBuild()
        build_two.name = 'postgressql'
        build_two.stream = '1'
        build_two.version = 2
        build_two.state = 3
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

        component_one_build_two = ComponentBuild()
        component_one_build_two.package = 'postgresql'
        component_one_build_two.scmurl = \
            ('git://pkgs.domain.local/rpms/postgresql?'
             '#dc95586c4a443b26a9ce38abda1f9bed22f2f8c3')
        component_one_build_two.format = 'rpms'
        component_one_build_two.task_id = 2433433 + index
        component_one_build_two.state = 1
        component_one_build_two.nvr = 'postgresql-9.5.3-4.module_postgresql_1_2'
        component_one_build_two.batch = 2
        component_one_build_two.module_id = 2 + index * 3
        component_one_build_two.tagged = True
        component_one_build_two.tagged_in_final = True

        component_two_build_two = ComponentBuild()
        component_two_build_two.package = 'module-build-macros'
        component_two_build_two.scmurl = \
            ('/tmp/module_build_service-build-macrosWZUPeK/SRPMS/'
             'module-build-macros-0.1-1.module_postgresql_1_2.src.rpm')
        component_two_build_two.format = 'rpms'
        component_two_build_two.task_id = 47383993 + index
        component_two_build_two.state = 1
        component_two_build_two.nvr = \
            'module-build-macros-01-1.module_postgresql_1_2'
        component_two_build_two.batch = 1
        component_two_build_two.module_id = 2 + index * 3
        component_one_build_two.tagged = True
        component_one_build_two.build_time_only = True

        build_three = ModuleBuild()
        build_three.name = 'testmodule'
        build_three.stream = '4.3.43'
        build_three.version = 6
        build_three.state = 1
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

        component_one_build_three = ComponentBuild()
        component_one_build_three.package = 'rubygem-rails'
        component_one_build_three.scmurl = \
            ('git://pkgs.domain.local/rpms/rubygem-rails?'
             '#dd55886c4a443b26a9ce38abda1f9bed22f2f8c3')
        component_one_build_three.format = 'rpms'
        component_one_build_three.task_id = 2433433 + index
        component_one_build_three.state = 3
        component_one_build_three.nvr = 'postgresql-9.5.3-4.module_postgresql_1_2'
        component_one_build_three.batch = 2
        component_one_build_three.module_id = 3 + index * 3

        component_two_build_three = ComponentBuild()
        component_two_build_three.package = 'module-build-macros'
        component_two_build_three.scmurl = \
            ('/tmp/module_build_service-build-macrosWZUPeK/SRPMS/'
             'module-build-macros-0.1-1.module_testmodule_1_2.src.rpm')
        component_two_build_three.format = 'rpms'
        component_two_build_three.task_id = 47383993 + index
        component_two_build_three.state = 1
        component_two_build_three.nvr = \
            'module-build-macros-01-1.module_postgresql_1_2'
        component_two_build_three.batch = 1
        component_two_build_three.module_id = 3 + index * 3
        component_two_build_three.tagged = True
        component_two_build_three.build_time_only = True

        with make_session(conf) as session:
            session.add(build_one)
            session.add(component_one_build_one)
            session.add(component_two_build_one)
            session.add(component_one_build_two)
            session.add(component_two_build_two)
            session.add(component_one_build_three)
            session.add(component_two_build_three)
            session.add(build_two)
            session.add(build_three)
            session.commit()


def scheduler_init_data(communicator_state=None):
    clean_database()

    current_dir = os.path.dirname(__file__)
    star_command_yml_path = os.path.join(
        current_dir, 'staged_data', 'formatted_starcommand.yaml')
    with open(star_command_yml_path, 'r') as f:
        yaml = f.read()

    build_one = module_build_service.models.ModuleBuild()
    build_one.name = 'starcommand'
    build_one.stream = '1'
    build_one.version = 3
    build_one.state = 2
    build_one.modulemd = yaml
    build_one.koji_tag = 'module-starcommand-1.3'
    build_one.scmurl = ('git://pkgs.domain.local/modules/star-command?'
                        '#da95886b7a443b36a9ce31abda1f9bef22f2f8c6')
    build_one.batch = 2
    # https://www.youtube.com/watch?v=iOKymYVSaJE
    build_one.owner = 'Buzz Lightyear'
    build_one.time_submitted = datetime(2016, 12, 9, 11, 23, 20)
    build_one.time_modified = datetime(2016, 12, 9, 11, 25, 32)
    build_one.rebuild_strategy = 'changed-and-after'

    component_one_build_one = module_build_service.models.ComponentBuild()
    component_one_build_one.package = 'communicator'
    component_one_build_one.scmurl = \
        ('git://pkgs.domain.local/rpms/communicator?'
         '#da95886c8a443b36a9ce31abda1f9bed22f2f9c2')
    component_one_build_one.format = 'rpms'
    component_one_build_one.task_id = 12312345
    component_one_build_one.state = communicator_state
    if component_one_build_one.state == 1:
        component_one_build_one.tagged = True
        component_one_build_one.tagged_in_final = True
    component_one_build_one.nvr = 'communicator-1.10.1-2.module_starcommand_1_3'
    component_one_build_one.batch = 2
    component_one_build_one.module_id = 1

    component_two_build_one = module_build_service.models.ComponentBuild()
    component_two_build_one.package = 'module-build-macros'
    component_two_build_one.scmurl = \
        ('/tmp/module_build_service-build-macrosWZUPeK/SRPMS/'
         'module-build-macros-0.1-1.module_starcommand_1_3.src.rpm')
    component_two_build_one.format = 'rpms'
    component_two_build_one.task_id = 12312321
    component_two_build_one.state = 1
    if component_two_build_one.state == 1:
        component_two_build_one.tagged = True
        component_two_build_one.tagged_in_final = True
    component_two_build_one.nvr = \
        'module-build-macros-01-1.module_starcommand_1_3'
    component_two_build_one.batch = 2
    component_two_build_one.module_id = 1

    with make_session(conf) as session:
        session.add(build_one)
        session.add(component_one_build_one)
        session.add(component_two_build_one)
        session.commit()


def test_reuse_component_init_data():
    clean_database()

    current_dir = os.path.dirname(__file__)
    formatted_testmodule_yml_path = os.path.join(
        current_dir, 'staged_data', 'formatted_testmodule.yaml')
    with open(formatted_testmodule_yml_path, 'r') as f:
        yaml = f.read()

    build_one = module_build_service.models.ModuleBuild()
    build_one.name = 'testmodule'
    build_one.stream = 'master'
    build_one.version = 20170109091357
    build_one.state = 5
    build_one.modulemd = yaml
    build_one.koji_tag = 'module-testmodule-master-20170109091357'
    build_one.scmurl = ('git://pkgs.stg.fedoraproject.org/modules/testmodule.'
                        'git?#7fea453')
    build_one.batch = 3
    build_one.owner = 'Tom Brady'
    build_one.time_submitted = datetime(2017, 2, 15, 16, 8, 18)
    build_one.time_modified = datetime(2017, 2, 15, 16, 19, 35)
    build_one.time_completed = datetime(2017, 2, 15, 16, 19, 35)
    build_one.rebuild_strategy = 'changed-and-after'

    component_one_build_one = module_build_service.models.ComponentBuild()
    component_one_build_one.package = 'perl-Tangerine'
    component_one_build_one.scmurl = \
        ('git://pkgs.fedoraproject.org/rpms/perl-Tangerine'
         '?#4ceea43add2366d8b8c5a622a2fb563b625b9abf')
    component_one_build_one.format = 'rpms'
    component_one_build_one.task_id = 90276227
    component_one_build_one.state = 1
    component_one_build_one.nvr = \
        'perl-Tangerine-0.23-1.module_testmodule_master_20170109091357'
    component_one_build_one.batch = 2
    component_one_build_one.module_id = 1
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
    component_two_build_one.state = 1
    component_two_build_one.nvr = \
        'perl-List-Compare-0.53-5.module_testmodule_master_20170109091357'
    component_two_build_one.batch = 2
    component_two_build_one.module_id = 1
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
    component_three_build_one.state = 1
    component_three_build_one.nvr = \
        'tangerine-0.22-3.module_testmodule_master_20170109091357'
    component_three_build_one.batch = 3
    component_three_build_one.module_id = 1
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
    component_four_build_one.state = 1
    component_four_build_one.nvr = \
        'module-build-macros-0.1-1.module_testmodule_master_20170109091357'
    component_four_build_one.batch = 1
    component_four_build_one.module_id = 1
    component_four_build_one.tagged = True
    component_four_build_one.build_time_only = True

    mmd = modulemd.ModuleMetadata()
    mmd.loads(yaml)
    mmd.xmd['mbs']['commit'] = '55f4a0a2e6cc255c88712a905157ab39315b8fd8'
    build_two = module_build_service.models.ModuleBuild()
    build_two.name = 'testmodule'
    build_two.stream = 'master'
    build_two.version = 20170219191323
    build_two.state = 2
    build_two.modulemd = mmd.dumps()
    build_two.koji_tag = 'module-testmodule'
    build_two.scmurl = ('git://pkgs.stg.fedoraproject.org/modules/testmodule.'
                        'git?#55f4a0a')
    build_two.batch = 1
    build_two.owner = 'Tom Brady'
    build_two.time_submitted = datetime(2017, 2, 19, 16, 8, 18)
    build_two.time_modified = datetime(2017, 2, 19, 16, 8, 18)
    build_two.rebuild_strategy = 'changed-and-after'

    component_one_build_two = module_build_service.models.ComponentBuild()
    component_one_build_two.package = 'perl-Tangerine'
    component_one_build_two.scmurl = \
        ('git://pkgs.fedoraproject.org/rpms/perl-Tangerine'
         '?#4ceea43add2366d8b8c5a622a2fb563b625b9abf')
    component_one_build_two.format = 'rpms'
    component_one_build_two.batch = 2
    component_one_build_two.module_id = 2
    component_one_build_two.ref = '4ceea43add2366d8b8c5a622a2fb563b625b9abf'

    component_two_build_two = module_build_service.models.ComponentBuild()
    component_two_build_two.package = 'perl-List-Compare'
    component_two_build_two.scmurl = \
        ('git://pkgs.fedoraproject.org/rpms/perl-List-Compare'
         '?#76f9d8c8e87eed0aab91034b01d3d5ff6bd5b4cb')
    component_two_build_two.format = 'rpms'
    component_two_build_two.batch = 2
    component_two_build_two.module_id = 2
    component_two_build_two.ref = '76f9d8c8e87eed0aab91034b01d3d5ff6bd5b4cb'

    component_three_build_two = module_build_service.models.ComponentBuild()
    component_three_build_two.package = 'tangerine'
    component_three_build_two.scmurl = \
        ('git://pkgs.fedoraproject.org/rpms/tangerine'
         '?#fbed359411a1baa08d4a88e0d12d426fbf8f602c')
    component_three_build_two.format = 'rpms'
    component_three_build_two.batch = 3
    component_three_build_two.module_id = 2
    component_three_build_two.ref = 'fbed359411a1baa08d4a88e0d12d426fbf8f602c'

    component_four_build_two = module_build_service.models.ComponentBuild()
    component_four_build_two.package = 'module-build-macros'
    component_four_build_two.scmurl = \
        ('/tmp/module_build_service-build-macrosqr4AWH/SRPMS/module-build-'
         'macros-0.1-1.module_testmodule_master_20170219191323.src.rpm')
    component_four_build_two.format = 'rpms'
    component_four_build_two.task_id = 90276186
    component_four_build_two.state = 1
    component_four_build_two.nvr = \
        'module-build-macros-0.1-1.module_testmodule_master_20170219191323'
    component_four_build_two.batch = 1
    component_four_build_two.module_id = 2
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


def test_reuse_shared_userspace_init_data():
    clean_database()

    with make_session(conf) as session:
        mmd = modulemd.ModuleMetadata()

        # Create shared-userspace-570, state is COMPLETE, all components
        # are properly built.
        current_dir = os.path.dirname(__file__)
        formatted_testmodule_yml_path = os.path.join(
            current_dir, 'staged_data', 'shared-userspace-570.yaml')
        with open(formatted_testmodule_yml_path, 'r') as f:
            yaml = f.read()
            mmd.loads(yaml)

        build_one = module_build_service.models.ModuleBuild()
        build_one.name = mmd.name
        build_one.stream = mmd.stream
        build_one.version = mmd.version
        build_one.state = 5
        build_one.modulemd = yaml
        build_one.koji_tag = 'module-testmodule-master-20170109091357'
        build_one.scmurl = ('git://pkgs.stg.fedoraproject.org/modules/testmodule.'
                            'git?#7fea453')
        build_one.batch = 16
        build_one.owner = 'Tom Brady'
        build_one.time_submitted = datetime(2017, 2, 15, 16, 8, 18)
        build_one.time_modified = datetime(2017, 2, 15, 16, 19, 35)
        build_one.time_completed = datetime(2017, 2, 15, 16, 19, 35)
        build_one.rebuild_strategy = 'changed-and-after'

        session.add(build_one)

        components = mmd.components.all
        components.sort(key=lambda x: x.buildorder)
        previous_buildorder = None
        batch = 1
        for pkg in components:
            # Increment the batch number when buildorder increases.
            if previous_buildorder != pkg.buildorder:
                previous_buildorder = pkg.buildorder
                batch += 1

            pkgref = mmd.xmd['mbs']['rpms'][pkg.name]['ref']
            full_url = pkg.repository + "?#" + pkgref
            build = module_build_service.models.ComponentBuild(
                module_id=1,
                package=pkg.name,
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
        with open(formatted_testmodule_yml_path, 'r') as f:
            yaml = f.read()
            mmd.loads(yaml)

        build_one = module_build_service.models.ModuleBuild()
        build_one.name = mmd.name
        build_one.stream = mmd.stream
        build_one.version = mmd.version
        build_one.state = 3
        build_one.modulemd = yaml
        build_one.koji_tag = 'module-testmodule-master-20170109091357'
        build_one.scmurl = ('git://pkgs.stg.fedoraproject.org/modules/testmodule.'
                            'git?#7fea453')
        build_one.batch = 0
        build_one.owner = 'Tom Brady'
        build_one.time_submitted = datetime(2017, 2, 15, 16, 8, 18)
        build_one.time_modified = datetime(2017, 2, 15, 16, 19, 35)
        build_one.time_completed = datetime(2017, 2, 15, 16, 19, 35)
        build_one.rebuild_strategy = 'changed-and-after'

        session.add(build_one)

        components = mmd.components.all
        # Store components to database in different order than for 570 to
        # reproduce the reusing issue.
        components.sort(key=lambda x: len(x.name))
        components.sort(key=lambda x: x.buildorder)
        previous_buildorder = None
        batch = 1
        for pkg in components:
            # Increment the batch number when buildorder increases.
            if previous_buildorder != pkg.buildorder:
                previous_buildorder = pkg.buildorder
                batch += 1

            pkgref = mmd.xmd['mbs']['rpms'][pkg.name]['ref']
            full_url = pkg.repository + "?#" + pkgref
            build = module_build_service.models.ComponentBuild(
                module_id=2,
                package=pkg.name,
                format="rpms",
                scmurl=full_url,
                batch=batch,
                ref=pkgref
            )
            session.add(build)
