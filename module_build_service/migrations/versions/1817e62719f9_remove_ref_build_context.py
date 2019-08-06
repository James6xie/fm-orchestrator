"""Remove the ref_build_context column

Revision ID: 1817e62719f9
Revises: d5188b4a7bf1
Create Date: 2019-08-02 12:31:00.707314

"""

# revision identifiers, used by Alembic.
revision = "1817e62719f9"
down_revision = "d5188b4a7bf1"

from alembic import op
import sqlalchemy as sa


def upgrade():
    with op.batch_alter_table("module_builds", schema=None) as batch_op:
        batch_op.drop_column("ref_build_context")


def downgrade():
    with op.batch_alter_table("module_builds", schema=None) as batch_op:
        batch_op.add_column(sa.Column("ref_build_context", sa.VARCHAR(), nullable=True))
