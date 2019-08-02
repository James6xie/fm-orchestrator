"""Add the missing foreign key constraint for reused_module_id

Revision ID: d5188b4a7bf1
Revises: 0b00036c540f
Create Date: 2019-08-02 13:22:14.257869
"""

# revision identifiers, used by Alembic.
revision = "d5188b4a7bf1"
down_revision = "0b00036c540f"

from alembic import op
import sqlalchemy as sa


def upgrade():
    with op.batch_alter_table("module_builds", schema=None) as batch_op:
        batch_op.create_foreign_key("reused_module", "module_builds", ["reused_module_id"], ["id"])


def downgrade():
    with op.batch_alter_table("module_builds", schema=None) as batch_op:
        batch_op.drop_constraint("reused_module", type_="foreignkey")
