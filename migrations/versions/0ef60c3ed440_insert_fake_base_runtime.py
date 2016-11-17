"""Insert fake base-runtime.

Revision ID: 0ef60c3ed440
Revises: 145347916a56
Create Date: 2016-11-17 15:39:22.984051

"""


# revision identifiers, used by Alembic.
revision = '0ef60c3ed440'
down_revision = '145347916a56'

from alembic import op
import sqlalchemy as sa

import os
import modulemd

yaml = """
document: modulemd
version: 1
data:
    name: base-runtime
    stream: master
    version: 3
    summary: A fake base-runtime module, used to bootstrap the infrastructure.
    description: ...
    profiles:
        buildroot:
            rpms:
                - bash
                - bzip2
                - coreutils
                - cpio
                - diffutils
                - fedora-release
                - findutils
                - gawk
                - gcc
                - gcc-c++
                - grep
                - gzip
                - info
                - make
                - patch
                - redhat-rpm-config
                - rpm-build
                - sed
                - shadow-utils
                - tar
                - unzip
                - util-linux
                - which
                - xz
        srpm-buildroot:
            rpms:
                - bash
                - fedora-release
                - fedpkg-minimal
                - gnupg2
                - redhat-rpm-config
                - rpm-build
                - shadow-utils
"""

def upgrade():
    from module_build_service import models, conf
    engine = op.get_bind().engine
    session = sa.orm.scoped_session(sa.orm.sessionmaker(bind=engine))

    mmd = modulemd.ModuleMetadata()
    mmd.loads(yaml)
    module = models.ModuleBuild.create(
        session,
        conf,
        name=mmd.name,
        stream=mmd.stream,
        version=mmd.version,
        modulemd=yaml,
        scmurl='...',
        username='modularity',
    )
    module.state = models.BUILD_STATES['done']
    module.state_reason = 'Artificially created.'
    session.commit()

def downgrade():
    pass
