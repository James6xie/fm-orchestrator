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
    sa.ForeignKeyConstraint(['reused_module_id'], ['module_builds.id'], ),


def downgrade():
    op.drop_column('module_builds', 'reused_module_id')
