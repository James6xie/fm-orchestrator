"""add log_messages table

Revision ID: 0b00036c540f
Revises: 40b2c7d988d7
Create Date: 2019-07-14 07:24:21.059144

"""

# revision identifiers, used by Alembic.
revision = "0b00036c540f"
down_revision = "40b2c7d988d7"

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table(
        "log_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("component_build_id", sa.Integer(), nullable=True),
        sa.Column("module_build_id", sa.Integer(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("time_created", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["component_build_id"], ["component_builds.id"], ),
        sa.ForeignKeyConstraint(["module_build_id"], ["module_builds.id"], ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("log_messages")
