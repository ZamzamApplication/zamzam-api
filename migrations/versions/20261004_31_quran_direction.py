"""Persist the traversal direction of student wards and progress records."""

from alembic import op
import sqlalchemy as sa

revision = "20261004_31"
down_revision = "20261002_30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("student_quran_plans", "quran_progress_entries"):
        columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}
        if "direction" not in columns:
            op.add_column(table, sa.Column("direction", sa.String(8), nullable=False, server_default="forward"))


def downgrade() -> None:
    for table in ("quran_progress_entries", "student_quran_plans"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("direction")
