"""Add finance expense tracking and configurable categories."""

import json

from alembic import op
import sqlalchemy as sa


revision = "20260803_13"
down_revision = "20260801_12"
branch_labels = None
depends_on = None


DEFAULT_CATEGORIES = [
    {"id": "rent", "label": "إيجار", "enabled": True},
    {"id": "salaries", "label": "رواتب", "enabled": True},
    {"id": "utilities", "label": "مرافق", "enabled": True},
    {"id": "maintenance", "label": "صيانة", "enabled": True},
    {"id": "supplies", "label": "مستلزمات", "enabled": True},
    {"id": "transportation", "label": "انتقالات", "enabled": True},
    {"id": "other", "label": "أخرى", "enabled": True},
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tahfiz_columns = {column["name"] for column in inspector.get_columns("tahfiz")}
    if "expense_categories" not in tahfiz_columns:
        with op.batch_alter_table("tahfiz") as batch:
            batch.add_column(sa.Column(
                "expense_categories",
                sa.Text(),
                nullable=False,
                server_default=json.dumps(DEFAULT_CATEGORIES, ensure_ascii=False),
            ))

    if "expenses" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "expenses",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("tahfiz_id", sa.Integer(), sa.ForeignKey("tahfiz.id"), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("category_id", sa.String(length=80), nullable=False),
            sa.Column("category_label_snapshot", sa.String(length=100), nullable=False),
            sa.Column("amount_minor", sa.Integer(), nullable=False),
            sa.Column("currency", sa.String(length=3), nullable=False),
            sa.Column("expense_date", sa.Date(), nullable=False),
            sa.Column("payment_method", sa.String(length=30), nullable=False),
            sa.Column("note", sa.String(length=500), nullable=True),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("deleted_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint("amount_minor > 0", name="ck_expenses_amount_positive"),
        )
        op.create_index("ix_expenses_tahfiz_id", "expenses", ["tahfiz_id"])
        op.create_index(
            "ix_expenses_tenant_date_deleted",
            "expenses",
            ["tahfiz_id", "expense_date", "deleted_at"],
        )
        op.create_index(
            "ix_expenses_tenant_method_date",
            "expenses",
            ["tahfiz_id", "payment_method", "expense_date"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "expenses" in sa.inspect(bind).get_table_names():
        op.drop_table("expenses")
    tahfiz_columns = {column["name"] for column in sa.inspect(bind).get_columns("tahfiz")}
    if "expense_categories" in tahfiz_columns:
        with op.batch_alter_table("tahfiz") as batch:
            batch.drop_column("expense_categories")
