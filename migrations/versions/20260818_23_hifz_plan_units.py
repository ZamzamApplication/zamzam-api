"""Allow named Hifz plan units.

Revision ID: 20260818_23
Revises: 20260813_22
"""

from alembic import op
import sqlalchemy as sa


revision = "20260818_23"
down_revision = "20260813_22"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "student_quran_plans" not in sa.inspect(bind).get_table_names():
        return
    with op.batch_alter_table("student_quran_plans") as batch:
        batch.alter_column(
            "increment_unit",
            existing_type=sa.String(length=5),
            type_=sa.String(length=16),
            existing_nullable=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "student_quran_plans" not in sa.inspect(bind).get_table_names():
        return
    plans = sa.table("student_quran_plans", sa.column("increment_unit", sa.String()))
    op.execute(
        plans.update()
        .where(plans.c.increment_unit.in_(("juz", "hizb", "quarter", "half_page")))
        .values(increment_unit="lines")
    )
    with op.batch_alter_table("student_quran_plans") as batch:
        batch.alter_column(
            "increment_unit",
            existing_type=sa.String(length=16),
            type_=sa.String(length=5),
            existing_nullable=False,
        )
