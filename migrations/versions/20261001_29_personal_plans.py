"""Persist personal plan builder output and scoped sharing permissions."""

from alembic import op
import sqlalchemy as sa

revision = "20261001_29"
down_revision = "20260923_28"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "personal_plans" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "personal_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("configuration", sa.Text(), nullable=False),
        sa.Column("study_dates", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("completed_dates", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("share_mode", sa.String(16), nullable=False, server_default="private"),
        sa.Column("share_token", sa.String(64), nullable=True, unique=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_personal_plans_owner_user_id", "personal_plans", ["owner_user_id"])


def downgrade() -> None:
    op.drop_table("personal_plans")
