"""Allow selected sheikhs to take attendance for all students.

Revision ID: 20260821_24
Revises: 20260818_23
"""

from alembic import op
import sqlalchemy as sa


revision = "20260821_24"
down_revision = "20260818_23"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("sheikhs")}
    if "attendance_all_students_access" not in columns:
        op.add_column(
            "sheikhs",
            sa.Column(
                "attendance_all_students_access",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("sheikhs")}
    if "attendance_all_students_access" in columns:
        with op.batch_alter_table("sheikhs") as batch:
            batch.drop_column("attendance_all_students_access")
