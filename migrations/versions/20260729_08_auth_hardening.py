"""Add durable authentication rate limits and token revocation versions."""

from alembic import op
import sqlalchemy as sa


revision = "20260729_08"
down_revision = "20260728_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "auth_version" not in user_columns:
        with op.batch_alter_table("users") as batch:
            batch.add_column(
                sa.Column("auth_version", sa.Integer(), nullable=False, server_default="0")
            )

    if "auth_rate_limits" not in inspector.get_table_names():
        op.create_table(
            "auth_rate_limits",
            sa.Column("key_hash", sa.String(length=64), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("window_started_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("key_hash"),
        )
        op.create_index(
            "ix_auth_rate_limits_expires_at",
            "auth_rate_limits",
            ["expires_at"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index("ix_auth_rate_limits_expires_at", table_name="auth_rate_limits")
    op.drop_table("auth_rate_limits")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("auth_version")
