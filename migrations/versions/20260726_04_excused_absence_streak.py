"""Add configurable excused-absence streak settings.

Revision ID: 20260726_04
Revises: 20260724_03
Create Date: 2026-07-26
"""

import sqlalchemy as sa
from alembic import op


revision = "20260726_04"
down_revision = "20260724_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("tahfiz")}
    if "excused_absence_streak_limit" not in columns:
        op.add_column(
            "tahfiz",
            sa.Column(
                "excused_absence_streak_limit",
                sa.Integer(),
                nullable=False,
                server_default="3",
            ),
        )
    if "excused_absence_reset_statuses" not in columns:
        op.add_column(
            "tahfiz",
            sa.Column(
                "excused_absence_reset_statuses",
                sa.Text(),
                nullable=False,
                server_default='["حاضر"]',
            ),
        )
    if "attendance_status_colors" not in columns:
        op.add_column(
            "tahfiz",
            sa.Column(
                "attendance_status_colors",
                sa.Text(),
                nullable=False,
                server_default='{"حاضر":"green","غياب":"slate","غياب بعذر":"amber","لا ينطبق":"sky"}',
            ),
        )


def downgrade() -> None:
    with op.batch_alter_table("tahfiz") as batch:
        batch.drop_column("attendance_status_colors")
        batch.drop_column("excused_absence_reset_statuses")
        batch.drop_column("excused_absence_streak_limit")
