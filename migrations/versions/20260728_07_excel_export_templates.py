"""Add saved Excel export templates.

Revision ID: 20260728_07
Revises: 20260726_06
"""

import json

from alembic import op
import sqlalchemy as sa

from app.models import DEFAULT_EXCEL_EXPORT_TEMPLATES


revision = "20260728_07"
down_revision = "20260726_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("tahfiz")}
    if "excel_export_templates" not in columns:
        op.add_column(
            "tahfiz",
            sa.Column(
                "excel_export_templates",
                sa.Text(),
                nullable=False,
                server_default=json.dumps(DEFAULT_EXCEL_EXPORT_TEMPLATES, ensure_ascii=False),
            ),
        )


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("tahfiz")}
    if "excel_export_templates" in columns:
        with op.batch_alter_table("tahfiz") as batch:
            batch.drop_column("excel_export_templates")
