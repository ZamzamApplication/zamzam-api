"""Compatibility marker for the abandoned session-owned ward migration.

The original revision was reset before entering the maintained migration
history. Keeping its revision identifier as a no-op lets any database that
was briefly stamped with it rejoin the supported chain without recreating
the abandoned session columns on fresh installations.
"""

revision = "20260808_16"
down_revision = "20260808_15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
