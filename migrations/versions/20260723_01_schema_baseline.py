"""Establish the managed schema baseline.

Revision ID: 20260723_01
Revises:
Create Date: 2026-07-23
"""
from alembic import op

from app.database import Base
import app.models  # noqa: F401

revision = "20260723_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing installations were brought to this baseline by the legacy
    # idempotent migrator. New installations are created directly from the
    # declared metadata. Future changes must use a new Alembic revision.
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    # A baseline downgrade must never destroy an existing installation.
    pass
