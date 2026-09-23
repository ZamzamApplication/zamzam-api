"""Allow tenant-defined Quran progress categories.

Revision ID: 20260923_26
Revises: 20260825_25
"""

import json

from alembic import op
import sqlalchemy as sa


revision = "20260923_26"
down_revision = "20260825_25"
branch_labels = None
depends_on = None


TABLES = ("quran_progress_entries", "student_quran_plans", "quran_progress_revisions")


def upgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        if bind.dialect.name == "postgresql":
            op.execute(sa.text(
                f"ALTER TABLE {table} ALTER COLUMN category TYPE varchar(50) USING category::text"
            ))
        else:
            with op.batch_alter_table(table) as batch:
                batch.alter_column("category", existing_type=sa.String(30), type_=sa.String(50), existing_nullable=False)

    rows = bind.execute(sa.text("SELECT id, progress_categories FROM tahfiz")).all()
    for tahfiz_id, raw_categories in rows:
        try:
            categories = json.loads(raw_categories)
        except (TypeError, ValueError):
            categories = None
        if categories == ["new_memorization"]:
            bind.execute(sa.text(
                "UPDATE tahfiz SET progress_categories = :categories WHERE id = :tahfiz_id"
            ), {"categories": json.dumps(["new_memorization", "recent_revision"]), "tahfiz_id": tahfiz_id})


def downgrade() -> None:
    bind = op.get_bind()
    allowed = {"new_memorization", "recent_revision", "old_revision", "test"}
    for table in TABLES:
        values = {row[0] for row in bind.execute(sa.text(f"SELECT DISTINCT category FROM {table}"))}
        if values - allowed:
            raise RuntimeError("Cannot downgrade while custom Quran progress records exist")
    for raw_categories, in bind.execute(sa.text("SELECT progress_categories FROM tahfiz")):
        if set(json.loads(raw_categories)) - allowed:
            raise RuntimeError("Cannot downgrade while custom Quran progress categories are configured")
    for table in TABLES:
        if bind.dialect.name == "postgresql":
            op.execute(sa.text(
                f"ALTER TABLE {table} ALTER COLUMN category TYPE progresscategory USING category::progresscategory"
            ))
        else:
            with op.batch_alter_table(table) as batch:
                batch.alter_column("category", existing_type=sa.String(50), type_=sa.String(16), existing_nullable=False)
