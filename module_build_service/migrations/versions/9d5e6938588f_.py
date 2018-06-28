"""Remove the COPR columns

Revision ID: 9d5e6938588f
Revises: 708ac8950f55
Create Date: 2018-06-28 13:57:08.977877

"""

revision = '9d5e6938588f'
down_revision = '708ac8950f55'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.drop_column('module_builds', 'copr_project')
    op.drop_column('module_builds', 'copr_owner')


def downgrade():
    op.add_column('module_builds', sa.Column('copr_owner', sa.VARCHAR(), nullable=True))
    op.add_column('module_builds', sa.Column('copr_project', sa.VARCHAR(), nullable=True))
