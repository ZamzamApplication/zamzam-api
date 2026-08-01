"""Add simple monthly student subscriptions."""

from alembic import op
import sqlalchemy as sa


revision = "20260801_11"
down_revision = "20260801_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tahfiz_columns = {column["name"] for column in inspector.get_columns("tahfiz")}
    with op.batch_alter_table("tahfiz") as batch:
        if "subscriptions_enabled" not in tahfiz_columns:
            batch.add_column(sa.Column("subscriptions_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
        if "subscription_default_fee_minor" not in tahfiz_columns:
            batch.add_column(sa.Column("subscription_default_fee_minor", sa.Integer(), nullable=False, server_default="0"))
        if "subscription_currency" not in tahfiz_columns:
            batch.add_column(sa.Column("subscription_currency", sa.String(length=3), nullable=False, server_default="EGP"))

    inspector = sa.inspect(bind)
    student_columns = {column["name"] for column in inspector.get_columns("students")}
    if "subscription_fee_override_minor" not in student_columns:
        with op.batch_alter_table("students") as batch:
            batch.add_column(sa.Column("subscription_fee_override_minor", sa.Integer(), nullable=True))

    if "student_subscriptions" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "student_subscriptions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("tahfiz_id", sa.Integer(), sa.ForeignKey("tahfiz.id"), nullable=False),
            sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id", ondelete="SET NULL"), nullable=True),
            sa.Column("student_snapshot_id", sa.Integer(), nullable=False),
            sa.Column("student_name", sa.String(length=100), nullable=False),
            sa.Column("student_custom_id", sa.String(length=50), nullable=True),
            sa.Column("student_phone", sa.String(length=20), nullable=True),
            sa.Column("sheikh_id_snapshot", sa.Integer(), nullable=True),
            sa.Column("sheikh_name", sa.String(length=100), nullable=True),
            sa.Column("period_start", sa.Date(), nullable=False),
            sa.Column("period_end", sa.Date(), nullable=False),
            sa.Column("amount_due_minor", sa.Integer(), nullable=False),
            sa.Column("currency", sa.String(length=3), nullable=False),
            sa.Column("is_paid", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("payment_date", sa.Date(), nullable=True),
            sa.Column("paid_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("payment_method", sa.String(length=30), nullable=True),
            sa.Column("payment_note", sa.String(length=500), nullable=True),
            sa.Column("receipt_number", sa.String(length=80), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint("amount_due_minor >= 0", name="ck_student_subscriptions_amount_nonnegative"),
            sa.UniqueConstraint(
                "tahfiz_id",
                "student_snapshot_id",
                "period_start",
                name="uq_student_subscriptions_tenant_student_period",
            ),
            sa.UniqueConstraint("receipt_number", name="uq_student_subscriptions_receipt_number"),
        )
        op.create_index(
            "ix_student_subscriptions_tenant_period_paid",
            "student_subscriptions",
            ["tahfiz_id", "period_start", "is_paid"],
        )
        op.create_index(
            "ix_student_subscriptions_tenant_student",
            "student_subscriptions",
            ["tahfiz_id", "student_id"],
        )
        op.create_index("ix_student_subscriptions_tahfiz_id", "student_subscriptions", ["tahfiz_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if "student_subscriptions" in sa.inspect(bind).get_table_names():
        op.drop_table("student_subscriptions")

    student_columns = {column["name"] for column in sa.inspect(bind).get_columns("students")}
    if "subscription_fee_override_minor" in student_columns:
        with op.batch_alter_table("students") as batch:
            batch.drop_column("subscription_fee_override_minor")

    tahfiz_columns = {column["name"] for column in sa.inspect(bind).get_columns("tahfiz")}
    with op.batch_alter_table("tahfiz") as batch:
        for column in ("subscription_currency", "subscription_default_fee_minor", "subscriptions_enabled"):
            if column in tahfiz_columns:
                batch.drop_column(column)
