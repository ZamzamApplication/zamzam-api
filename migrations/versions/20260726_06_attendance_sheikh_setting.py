"""Add optional attendance Sheikh selector setting.

Revision ID: 20260726_06
Revises: 20260726_05
"""

from alembic import op
import sqlalchemy as sa


revision = "20260726_06"
down_revision = "20260726_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("tahfiz")}
    if "attendance_sheikh_selection_enabled" not in columns:
        op.add_column(
            "tahfiz",
            sa.Column(
                "attendance_sheikh_selection_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
        )


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("tahfiz")}
    if "attendance_sheikh_selection_enabled" in columns:
        with op.batch_alter_table("tahfiz") as batch:
            batch.drop_column("attendance_sheikh_selection_enabled")
