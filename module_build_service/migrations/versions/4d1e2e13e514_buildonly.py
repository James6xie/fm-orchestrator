"""Add buildonly column

Revision ID: 4d1e2e13e514
Revises: a87264eeb49f
Create Date: 2019-10-01 13:49:20.446641

"""

# revision identifiers, used by Alembic.
revision = '4d1e2e13e514'
down_revision = 'a87264eeb49f'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column("component_builds", sa.Column("buildonly", sa.Boolean(), nullable=True))


def downgrade():
    with op.batch_alter_table("component_builds", schema=None) as batch_op:
        batch_op.drop_column("buildonly")
