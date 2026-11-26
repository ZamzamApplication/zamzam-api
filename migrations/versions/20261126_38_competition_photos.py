"""Opt-in student photos on public competition leaderboards."""
from alembic import op
import sqlalchemy as sa

revision = "20261126_38"
down_revision = "20261125_37"
branch_labels = None
depends_on = None


def upgrade():
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("competitions")}
    if "show_photos" not in existing:
        op.add_column("competitions", sa.Column("show_photos", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("competitions", "show_photos")
