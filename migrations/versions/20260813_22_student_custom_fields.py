"""Add typed student custom fields.

Revision ID: 20260813_22
Revises: 20260813_21
"""

from alembic import op
import sqlalchemy as sa


revision = "20260813_22"
down_revision = "20260813_21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tahfiz_columns = {column["name"] for column in sa.inspect(bind).get_columns("tahfiz")}
    if "sheikh_custom_fields_enabled" not in tahfiz_columns:
        op.add_column("tahfiz", sa.Column("sheikh_custom_fields_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))

    tables = set(sa.inspect(bind).get_table_names())
    if "student_custom_fields" not in tables:
        op.create_table(
            "student_custom_fields",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("tahfiz_id", sa.Integer(), sa.ForeignKey("tahfiz.id"), nullable=False),
            sa.Column("name", sa.String(length=80), nullable=False),
            sa.Column("field_type", sa.String(length=20), nullable=False),
            sa.Column("options", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("tahfiz_id", "name", name="uq_student_custom_field_tenant_name"),
        )
        op.create_index("ix_student_custom_fields_tahfiz_id", "student_custom_fields", ["tahfiz_id"])
        op.create_index("ix_student_custom_fields_tenant_order", "student_custom_fields", ["tahfiz_id", "is_active", "sort_order"])

    if "student_custom_field_values" not in tables:
        op.create_table(
            "student_custom_field_values",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("tahfiz_id", sa.Integer(), sa.ForeignKey("tahfiz.id"), nullable=False),
            sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
            sa.Column("field_id", sa.Integer(), sa.ForeignKey("student_custom_fields.id", ondelete="CASCADE"), nullable=False),
            sa.Column("value", sa.Text(), nullable=False),
            sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("tahfiz_id", "student_id", "field_id", name="uq_student_custom_field_value"),
        )
        op.create_index("ix_student_custom_field_values_tahfiz_id", "student_custom_field_values", ["tahfiz_id"])
        op.create_index("ix_student_custom_field_values_tenant_student", "student_custom_field_values", ["tahfiz_id", "student_id"])


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "student_custom_field_values" in tables:
        op.drop_table("student_custom_field_values")
    if "student_custom_fields" in tables:
        op.drop_table("student_custom_fields")
    if "sheikh_custom_fields_enabled" in {column["name"] for column in sa.inspect(bind).get_columns("tahfiz")}:
        with op.batch_alter_table("tahfiz") as batch:
            batch.drop_column("sheikh_custom_fields_enabled")
