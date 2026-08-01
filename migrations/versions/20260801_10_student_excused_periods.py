"""Add temporary student excused-absence periods."""

from alembic import op
import sqlalchemy as sa


revision = "20260801_10"
down_revision = "20260801_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "student_excused_periods" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "student_excused_periods",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id"), nullable=False),
        sa.Column("tahfiz_id", sa.Integer(), sa.ForeignKey("tahfiz.id"), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("cancelled_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("start_date <= end_date", name="ck_student_excused_period_dates"),
    )
    op.create_index(
        "ix_student_excused_periods_tenant_student_dates",
        "student_excused_periods",
        ["tahfiz_id", "student_id", "start_date", "end_date"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "student_excused_periods" not in sa.inspect(bind).get_table_names():
        return
    op.drop_index("ix_student_excused_periods_tenant_student_dates", table_name="student_excused_periods")
    op.drop_table("student_excused_periods")
