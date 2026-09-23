"""Add finance-only auditor tenant role.

Revision ID: 20260923_27
Revises: 20260923_26
"""

from alembic import op


revision = "20260923_27"
down_revision = "20260923_26"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'auditor'")


def downgrade() -> None:
    # PostgreSQL enum values cannot be safely removed while records may use them.
    pass
