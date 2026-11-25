"""Competitions with participants, daily entries and an optional public leaderboard."""
from alembic import op
import sqlalchemy as sa

revision = "20261125_37"
down_revision = "20261105_36"
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "competitions" not in existing:
        op.create_table(
            "competitions",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("tahfiz_id", sa.Integer(), sa.ForeignKey("tahfiz.id"), nullable=False),
            sa.Column("title", sa.String(length=120), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("start_date", sa.Date(), nullable=False),
            sa.Column("end_date", sa.Date(), nullable=False),
            sa.Column("status", sa.String(length=12), nullable=False, server_default="draft"),
            sa.Column("points_per_check", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("completion_threshold", sa.Integer(), nullable=True),
            sa.Column("public_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("public_token", sa.String(length=64), nullable=True, unique=True),
            sa.Column("name_display", sa.String(length=8), nullable=False, server_default="short"),
            sa.Column("public_limit", sa.Integer(), nullable=False, server_default="10"),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint("end_date >= start_date", name="ck_competition_dates"),
            sa.CheckConstraint("points_per_check >= 1", name="ck_competition_points"),
        )
        op.create_index("ix_competitions_tenant_start", "competitions", ["tahfiz_id", "start_date"])
    if "competition_participants" not in existing:
        op.create_table(
            "competition_participants",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("tahfiz_id", sa.Integer(), sa.ForeignKey("tahfiz.id"), nullable=False),
            sa.Column("competition_id", sa.Integer(), sa.ForeignKey("competitions.id"), nullable=False),
            sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id", ondelete="SET NULL"), nullable=True),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("competition_id", "student_id", name="uq_competition_student"),
        )
        op.create_index("ix_competition_participants_tenant_competition", "competition_participants",
                        ["tahfiz_id", "competition_id"])
    if "competition_entries" not in existing:
        op.create_table(
            "competition_entries",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("tahfiz_id", sa.Integer(), sa.ForeignKey("tahfiz.id"), nullable=False),
            sa.Column("competition_id", sa.Integer(), sa.ForeignKey("competitions.id"), nullable=False),
            sa.Column("participant_id", sa.Integer(),
                      sa.ForeignKey("competition_participants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("entry_date", sa.Date(), nullable=False),
            sa.Column("points", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("recorded_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("recorded_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("participant_id", "entry_date", name="uq_competition_entry_day"),
            sa.CheckConstraint("points >= 1", name="ck_competition_entry_points"),
        )
        op.create_index("ix_competition_entries_tenant_competition_date", "competition_entries",
                        ["tahfiz_id", "competition_id", "entry_date"])


def downgrade():
    op.drop_table("competition_entries")
    op.drop_table("competition_participants")
    op.drop_table("competitions")
