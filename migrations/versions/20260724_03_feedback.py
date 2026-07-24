"""Add user feedback reports.

Revision ID: 20260724_03
Revises: 20260724_02
Create Date: 2026-07-24
"""

import sqlalchemy as sa
from alembic import op

revision = "20260724_03"
down_revision = "20260724_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feedback_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "reporter_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reporter_username", sa.String(length=50), nullable=False),
        sa.Column(
            "tahfiz_id",
            sa.Integer(),
            sa.ForeignKey("tahfiz.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "category",
            sa.Enum("bug", "suggestion", "other", name="feedbackcategory"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("page_url", sa.String(length=500), nullable=True),
        sa.Column(
            "status",
            sa.Enum("open", "in_review", "resolved", "not_an_issue", name="feedbackstatus"),
            nullable=False,
            server_default="open",
        ),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column(
            "reviewed_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_feedback_reports_reporter_user_id", "feedback_reports", ["reporter_user_id"])
    op.create_index("ix_feedback_reports_tahfiz_id", "feedback_reports", ["tahfiz_id"])
    op.create_index("ix_feedback_reports_status", "feedback_reports", ["status"])
    op.create_index(
        "ix_feedback_reports_status_created",
        "feedback_reports",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_feedback_reports_tahfiz_created",
        "feedback_reports",
        ["tahfiz_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("feedback_reports")
