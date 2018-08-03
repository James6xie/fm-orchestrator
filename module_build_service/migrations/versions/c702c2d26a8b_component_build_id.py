"""Add the component build_id column

Revision ID: c702c2d26a8b
Revises: 9d5e6938588f
Create Date: 2018-08-03 15:28:38.493950

"""

# revision identifiers, used by Alembic.
revision = 'c702c2d26a8b'
down_revision = '9d5e6938588f'

from alembic import op
import sqlalchemy as sa


def upgrade():
    with op.batch_alter_table('component_builds') as b:
        b.add_column(sa.Column('build_id', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('component_builds') as b:
        b.drop_column('build_id')
