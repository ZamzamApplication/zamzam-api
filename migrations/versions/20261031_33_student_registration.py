"""Public registration forms and pending student requests."""
from alembic import op
import sqlalchemy as sa

revision = "20261031_33"
down_revision = "20261018_32"
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "student_registration_forms" not in existing:
        op.create_table("student_registration_forms",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tahfiz_id", sa.Integer(), sa.ForeignKey("tahfiz.id"), nullable=False),
            sa.Column("token", sa.String(64), unique=True, nullable=False),
            sa.Column("title", sa.String(120), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("public_field_ids", sa.Text(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False))
        op.create_index("ix_student_registration_forms_tahfiz_id", "student_registration_forms", ["tahfiz_id"])
    if "student_registration_requests" not in existing:
        op.create_table("student_registration_requests",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tahfiz_id", sa.Integer(), sa.ForeignKey("tahfiz.id"), nullable=False),
            sa.Column("form_id", sa.Integer(), sa.ForeignKey("student_registration_forms.id"), nullable=False),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("phone", sa.String(20), nullable=True),
            sa.Column("birthday", sa.Date(), nullable=True),
            sa.Column("answers", sa.Text(), nullable=False),
            sa.Column("field_snapshot", sa.Text(), nullable=False),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id", ondelete="SET NULL"), nullable=True),
            sa.Column("reviewed_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False))
        op.create_index("ix_registration_requests_tenant_status", "student_registration_requests", ["tahfiz_id", "status"])


def downgrade():
    op.drop_table("student_registration_requests")
    op.drop_table("student_registration_forms")
