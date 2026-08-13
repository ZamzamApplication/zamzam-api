"""Add configurable session name options.

Revision ID: 20260813_21
Revises: 20260811_20
"""

from alembic import op
import sqlalchemy as sa


revision = "20260813_21"
down_revision = "20260811_20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("tahfiz")}
    if "session_name_options" not in columns:
        op.add_column(
            "tahfiz",
            sa.Column(
                "session_name_options",
                sa.Text(),
                nullable=False,
                server_default='["الصباحية", "المسائية"]',
            ),
        )


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("tahfiz")}
    if "session_name_options" in columns:
        with op.batch_alter_table("tahfiz") as batch:
            batch.drop_column("session_name_options")
