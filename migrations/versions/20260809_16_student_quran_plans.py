"""Add persistent per-student Qur'an ward plans.

Revision ID: 20260809_16
Revises: 20260808_17
"""

from alembic import op
import sqlalchemy as sa


revision = "20260809_16"
down_revision = "20260808_17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "student_quran_plans" in inspector.get_table_names():
        return
    op.create_table(
        "student_quran_plans",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tahfiz_id", sa.Integer(), sa.ForeignKey("tahfiz.id"), nullable=False),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id"), nullable=False),
        sa.Column("category", sa.String(length=19), nullable=False),
        sa.Column("increment_unit", sa.String(length=5), nullable=False),
        sa.Column("increment_amount", sa.Integer(), nullable=False),
        sa.Column("next_surah", sa.Integer(), nullable=True),
        sa.Column("next_ayah", sa.Integer(), nullable=True),
        sa.Column("next_page", sa.Integer(), nullable=True),
        sa.Column("last_advanced_session_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("increment_amount > 0", name="ck_student_quran_plan_positive_increment"),
        sa.UniqueConstraint("tahfiz_id", "student_id", "category", name="uq_student_quran_plan_category"),
    )
    op.create_index(
        "ix_student_quran_plans_tenant_student",
        "student_quran_plans",
        ["tahfiz_id", "student_id"],
    )
    op.create_index(
        "ix_student_quran_plans_tahfiz_id",
        "student_quran_plans",
        ["tahfiz_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "student_quran_plans" not in sa.inspect(bind).get_table_names():
        return
    op.drop_index("ix_student_quran_plans_tahfiz_id", table_name="student_quran_plans")
    op.drop_index("ix_student_quran_plans_tenant_student", table_name="student_quran_plans")
    op.drop_table("student_quran_plans")
