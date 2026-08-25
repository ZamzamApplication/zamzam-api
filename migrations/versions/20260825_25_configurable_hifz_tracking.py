"""Add configurable, per-student Hifz tracking.

Revision ID: 20260825_25
Revises: 20260821_24
"""

import json

from alembic import op
import sqlalchemy as sa


revision = "20260825_25"
down_revision = "20260821_24"
branch_labels = None
depends_on = None


TRACKABLE_CATEGORIES = ("new_memorization", "recent_revision", "old_revision")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "tahfiz" in tables:
        columns = {column["name"] for column in inspector.get_columns("tahfiz")}
        if "progress_categories" not in columns:
            op.add_column(
                "tahfiz",
                sa.Column("progress_categories", sa.Text(), nullable=False, server_default='["new_memorization"]'),
            )

    inspector = sa.inspect(bind)
    if "students" in tables:
        columns = {column["name"] for column in inspector.get_columns("students")}
        if "quran_progress_enabled" not in columns:
            op.add_column(
                "students",
                sa.Column("quran_progress_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            )

    inspector = sa.inspect(bind)
    if "student_quran_plans" in tables:
        columns = {column["name"] for column in inspector.get_columns("student_quran_plans")}
        if "completed_at" not in columns:
            op.add_column("student_quran_plans", sa.Column("completed_at", sa.DateTime(), nullable=True))

    if "students" in tables:
        sources = []
        if "quran_progress_entries" in tables:
            sources.append("SELECT student_id FROM quran_progress_entries")
        if "student_quran_plans" in tables:
            sources.append("SELECT student_id FROM student_quran_plans")
        if sources:
            bind.execute(sa.text(
                "UPDATE students SET quran_progress_enabled = 1 "
                f"WHERE id IN ({' UNION '.join(sources)})"
            ))

    if "tahfiz" in tables:
        tahfiz_ids = [row[0] for row in bind.execute(sa.text("SELECT id FROM tahfiz"))]
        for tahfiz_id in tahfiz_ids:
            used: set[str] = set()
            if "quran_progress_entries" in tables:
                used.update(row[0] for row in bind.execute(sa.text(
                    "SELECT DISTINCT category FROM quran_progress_entries WHERE tahfiz_id = :tahfiz_id"
                ), {"tahfiz_id": tahfiz_id}))
            if "student_quran_plans" in tables:
                used.update(row[0] for row in bind.execute(sa.text(
                    "SELECT DISTINCT category FROM student_quran_plans WHERE tahfiz_id = :tahfiz_id"
                ), {"tahfiz_id": tahfiz_id}))
            categories = [category for category in TRACKABLE_CATEGORIES if category == "new_memorization" or category in used]
            bind.execute(sa.text(
                "UPDATE tahfiz SET progress_categories = :categories WHERE id = :tahfiz_id"
            ), {
                "categories": json.dumps(categories),
                "tahfiz_id": tahfiz_id,
            })


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "student_quran_plans" in tables and "completed_at" in {column["name"] for column in inspector.get_columns("student_quran_plans")}:
        with op.batch_alter_table("student_quran_plans") as batch:
            batch.drop_column("completed_at")
    inspector = sa.inspect(bind)
    if "students" in tables and "quran_progress_enabled" in {column["name"] for column in inspector.get_columns("students")}:
        with op.batch_alter_table("students") as batch:
            batch.drop_column("quran_progress_enabled")
    inspector = sa.inspect(bind)
    if "tahfiz" in tables and "progress_categories" in {column["name"] for column in inspector.get_columns("tahfiz")}:
        with op.batch_alter_table("tahfiz") as batch:
            batch.drop_column("progress_categories")
