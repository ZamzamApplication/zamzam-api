"""Add the configured default absence status.

Revision ID: 20260811_19
Revises: 20260811_18
"""

from alembic import op
import sqlalchemy as sa


revision = "20260811_19"
down_revision = "20260811_18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("tahfiz")}
    if "absent_status" not in columns:
        op.add_column(
            "tahfiz",
            sa.Column("absent_status", sa.String(length=50), nullable=False, server_default="غياب"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("tahfiz")}
    if "absent_status" in columns:
        with op.batch_alter_table("tahfiz") as batch_op:
            batch_op.drop_column("absent_status")
