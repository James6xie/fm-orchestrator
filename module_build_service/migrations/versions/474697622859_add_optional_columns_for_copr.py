"""Add optional columns for copr

Revision ID: 474697622859
Revises: 0ef60c3ed440
Create Date: 2017-02-21 11:18:22.304038

"""

# revision identifiers, used by Alembic.
revision = '474697622859'
down_revision = '0ef60c3ed440'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('module_builds', sa.Column('copr_owner', sa.String(), nullable=True))
    op.add_column('module_builds', sa.Column('copr_project', sa.String(), nullable=True))


def downgrade():
    op.drop_column('module_builds', 'copr_owner')
    op.drop_column('module_builds', 'copr_project')
