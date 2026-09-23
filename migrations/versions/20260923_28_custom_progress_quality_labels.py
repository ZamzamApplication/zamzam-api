"""Allow tenant-specific Quran progress evaluation labels.

Revision ID: 20260923_28
Revises: 20260923_27
"""

from alembic import op
import sqlalchemy as sa


revision = "20260923_28"
down_revision = "20260923_27"
branch_labels = None
depends_on = None


DEFAULT_OPTIONS = '[{"value": 5, "label": "ممتاز"}, {"value": 4, "label": "جيد جداً"}, {"value": 3, "label": "جيد"}, {"value": 2, "label": "مقبول"}, {"value": 1, "label": "يحتاج متابعة"}]'


def upgrade() -> None:
    op.add_column(
        "tahfiz",
        sa.Column("progress_quality_options", sa.Text(), nullable=False, server_default=DEFAULT_OPTIONS),
    )


def downgrade() -> None:
    op.drop_column("tahfiz", "progress_quality_options")
