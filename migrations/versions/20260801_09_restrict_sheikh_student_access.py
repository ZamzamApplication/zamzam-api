"""Restrict sheikhs to their assigned students by default."""

from alembic import op
import sqlalchemy as sa


revision = "20260801_09"
down_revision = "20260729_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("tahfiz")}
    if "restrict_sheikh_student_access" not in columns:
        with op.batch_alter_table("tahfiz") as batch:
            batch.add_column(sa.Column(
                "restrict_sheikh_student_access",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ))


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("tahfiz")}
    if "restrict_sheikh_student_access" in columns:
        with op.batch_alter_table("tahfiz") as batch:
            batch.drop_column("restrict_sheikh_student_access")
