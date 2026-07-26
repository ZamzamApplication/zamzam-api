"""Generalize attendance streak alerts and optional integrations.

Revision ID: 20260726_05
Revises: 20260726_04
Create Date: 2026-07-26
"""

import sqlalchemy as sa
from alembic import op


revision = "20260726_05"
down_revision = "20260726_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("tahfiz")}
    if "attendance_streak_alert_enabled" not in columns:
        op.add_column("tahfiz", sa.Column("attendance_streak_alert_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    if "attendance_streak_status" not in columns:
        op.add_column("tahfiz", sa.Column("attendance_streak_status", sa.String(length=50), nullable=False, server_default="غياب بعذر"))
    if "whatsend_enabled" not in columns:
        op.add_column("tahfiz", sa.Column("whatsend_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    with op.batch_alter_table("tahfiz") as batch:
        batch.drop_column("whatsend_enabled")
        batch.drop_column("attendance_streak_status")
        batch.drop_column("attendance_streak_alert_enabled")
