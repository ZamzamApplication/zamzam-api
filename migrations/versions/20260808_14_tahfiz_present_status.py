"""Add configurable present attendance status to tahfiz."""

from alembic import op
import sqlalchemy as sa


revision = "20260808_14"
down_revision = "20260803_13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("tahfiz")}
    if "present_status" not in columns:
        with op.batch_alter_table("tahfiz") as batch:
            batch.add_column(sa.Column(
                "present_status",
                sa.String(length=50),
                nullable=False,
                server_default="حاضر",
            ))


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("tahfiz")}
    if "present_status" in columns:
        with op.batch_alter_table("tahfiz") as batch:
            batch.drop_column("present_status")
