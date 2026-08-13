"""Add student categories and selective multiple daily sessions.

Revision ID: 20260811_20
Revises: 20260811_19
"""

from alembic import op
import sqlalchemy as sa


revision = "20260811_20"
down_revision = "20260811_19"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tahfiz_columns = {column["name"] for column in inspector.get_columns("tahfiz")}
    if "multiple_sessions_per_day_enabled" not in tahfiz_columns:
        op.add_column(
            "tahfiz",
            sa.Column("multiple_sessions_per_day_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        )

    tables = set(inspector.get_table_names())
    if "student_categories" not in tables:
        op.create_table(
            "student_categories",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("tahfiz_id", sa.Integer(), sa.ForeignKey("tahfiz.id"), nullable=False),
            sa.Column("name", sa.String(length=50), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("tahfiz_id", "name", name="uq_student_category_tenant_name"),
        )
        op.create_index("ix_student_categories_tahfiz_id", "student_categories", ["tahfiz_id"])
        op.create_index("ix_student_categories_tenant_name", "student_categories", ["tahfiz_id", "name"])

    if "student_category_memberships" not in tables:
        op.create_table(
            "student_category_memberships",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("tahfiz_id", sa.Integer(), sa.ForeignKey("tahfiz.id"), nullable=False),
            sa.Column("category_id", sa.Integer(), sa.ForeignKey("student_categories.id", ondelete="CASCADE"), nullable=False),
            sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("tahfiz_id", "category_id", "student_id", name="uq_student_category_membership"),
        )
        op.create_index("ix_student_category_memberships_tahfiz_id", "student_category_memberships", ["tahfiz_id"])
        op.create_index("ix_student_category_memberships_tenant_student", "student_category_memberships", ["tahfiz_id", "student_id"])

    session_columns = {column["name"] for column in sa.inspect(bind).get_columns("sessions")}
    if "name" not in session_columns:
        op.add_column("sessions", sa.Column("name", sa.String(length=100), nullable=True))
    if "daily_sequence" not in session_columns:
        op.add_column("sessions", sa.Column("daily_sequence", sa.Integer(), nullable=False, server_default="1"))
    if "explicit_membership" not in session_columns:
        op.add_column(
            "sessions",
            sa.Column("explicit_membership", sa.Boolean(), nullable=False, server_default=sa.false()),
        )

    rows = bind.execute(sa.text("SELECT id, tahfiz_id, date FROM sessions ORDER BY tahfiz_id, date, id")).fetchall()
    current_key = None
    sequence = 0
    for row in rows:
        key = (row.tahfiz_id, row.date)
        sequence = sequence + 1 if key == current_key else 1
        current_key = key
        bind.execute(
            sa.text("UPDATE sessions SET daily_sequence = :sequence WHERE id = :session_id"),
            {"sequence": sequence, "session_id": row.id},
        )
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("sessions")}
    uniques = {constraint["name"] for constraint in sa.inspect(bind).get_unique_constraints("sessions")}
    if "uq_sessions_tenant_date_sequence" not in indexes | uniques:
        op.create_index(
            "uq_sessions_tenant_date_sequence",
            "sessions",
            ["tahfiz_id", "date", "daily_sequence"],
            unique=True,
        )

    plan_columns = {column["name"] for column in sa.inspect(bind).get_columns("student_quran_plans")}
    if "last_advanced_on" not in plan_columns:
        op.add_column("student_quran_plans", sa.Column("last_advanced_on", sa.Date(), nullable=True))
    bind.execute(sa.text(
        "UPDATE student_quran_plans SET last_advanced_on = "
        "(SELECT date FROM sessions WHERE sessions.id = student_quran_plans.last_advanced_session_id) "
        "WHERE last_advanced_session_id IS NOT NULL AND last_advanced_on IS NULL"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    if "last_advanced_on" in {column["name"] for column in sa.inspect(bind).get_columns("student_quran_plans")}:
        with op.batch_alter_table("student_quran_plans") as batch:
            batch.drop_column("last_advanced_on")

    session_columns = {column["name"] for column in sa.inspect(bind).get_columns("sessions")}
    if {"name", "daily_sequence", "explicit_membership"} & session_columns:
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes("sessions")}
        if "uq_sessions_tenant_date_sequence" in indexes:
            op.drop_index("uq_sessions_tenant_date_sequence", table_name="sessions")
        with op.batch_alter_table("sessions") as batch:
            if "name" in session_columns:
                batch.drop_column("name")
            if "daily_sequence" in session_columns:
                batch.drop_column("daily_sequence")
            if "explicit_membership" in session_columns:
                batch.drop_column("explicit_membership")

    tables = set(sa.inspect(bind).get_table_names())
    if "student_category_memberships" in tables:
        op.drop_table("student_category_memberships")
    if "student_categories" in tables:
        op.drop_table("student_categories")
    if "multiple_sessions_per_day_enabled" in {column["name"] for column in sa.inspect(bind).get_columns("tahfiz")}:
        with op.batch_alter_table("tahfiz") as batch:
            batch.drop_column("multiple_sessions_per_day_enabled")
