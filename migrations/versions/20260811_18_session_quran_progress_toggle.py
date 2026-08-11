"""Add a per-session Qur'an progress toggle.

Revision ID: 20260811_18
Revises: 20260809_16
"""

from alembic import op
import sqlalchemy as sa


revision = "20260811_18"
down_revision = "20260809_16"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("sessions")}
    if "quran_progress_enabled" not in columns:
        op.add_column(
            "sessions",
            sa.Column("quran_progress_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("sessions")}
    if "quran_progress_enabled" in columns:
        with op.batch_alter_table("sessions") as batch_op:
            batch_op.drop_column("quran_progress_enabled")
