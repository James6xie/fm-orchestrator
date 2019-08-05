"""add reused_module_id column

Revision ID: 40b2c7d988d7
Revises: bf861b6af29a
Create Date: 2019-06-21 13:41:06.041269

"""

# revision identifiers, used by Alembic.
revision = '40b2c7d988d7'
down_revision = 'bf861b6af29a'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('module_builds', sa.Column('reused_module_id', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('module_builds', schema=None) as batch_op:
        batch_op.drop_column('reused_module_id')
