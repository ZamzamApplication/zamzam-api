"""Trip rosters, payments, guardians, groups and independent headcounts."""
from alembic import op
import sqlalchemy as sa

revision = "20261018_32"
down_revision = "20261004_31"
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "trips" not in existing:
        op.create_table(
            "trips",
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('tahfiz_id', sa.Integer(), sa.ForeignKey('tahfiz.id'), nullable=False),
            sa.Column('name', sa.String(length=120), nullable=False),
            sa.Column('destination', sa.String(length=200), nullable=False),
            sa.Column('date', sa.Date(), nullable=False),
            sa.Column('meeting_point', sa.String(length=200), nullable=False),
            sa.Column('departure_time', sa.String(length=5), nullable=False),
            sa.Column('fee_minor', sa.Integer(), nullable=False),
            sa.Column('currency', sa.String(length=3), nullable=False),
            sa.Column('notes', sa.Text(), nullable=False),
            sa.Column('status', sa.String(length=16), nullable=False),
            sa.Column('version', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_trips_tenant_date', 'trips', ['tahfiz_id', 'date'])
    if "trip_groups" not in existing:
        op.create_table(
            "trip_groups",
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('tahfiz_id', sa.Integer(), sa.ForeignKey('tahfiz.id'), nullable=False),
            sa.Column('trip_id', sa.Integer(), sa.ForeignKey('trips.id'), nullable=False),
            sa.Column('name', sa.String(length=100), nullable=False),
            sa.UniqueConstraint('trip_id', 'name', name='uq_trip_group_name'),
        )
    if "trip_participants" not in existing:
        op.create_table(
            "trip_participants",
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('tahfiz_id', sa.Integer(), sa.ForeignKey('tahfiz.id'), nullable=False),
            sa.Column('trip_id', sa.Integer(), sa.ForeignKey('trips.id'), nullable=False),
            sa.Column('student_id', sa.Integer(), sa.ForeignKey('students.id', ondelete='SET NULL'), nullable=True),
            sa.Column('group_id', sa.Integer(), sa.ForeignKey('trip_groups.id', ondelete='SET NULL'), nullable=True),
            sa.Column('guardian_id', sa.Integer(), sa.ForeignKey('trip_participants.id', ondelete='SET NULL'), nullable=True),
            sa.Column('is_adult', sa.Boolean(), nullable=False),
            sa.Column('kind', sa.String(length=12), nullable=False),
            sa.Column('name', sa.String(length=120), nullable=False),
            sa.Column('phone', sa.String(length=30), nullable=False),
            sa.Column('student_code', sa.String(length=50), nullable=False),
            sa.Column('sheikh_name', sa.String(length=120), nullable=False),
            sa.Column('fee_minor', sa.Integer(), nullable=False),
            sa.Column('paid_minor', sa.Integer(), nullable=False),
            sa.Column('payment_exempt', sa.Boolean(), nullable=False),
            sa.Column('exemption_reason', sa.String(length=200), nullable=False),
            sa.Column('active', sa.Boolean(), nullable=False),
            sa.Column('notes', sa.Text(), nullable=False),
            sa.Column('version', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.CheckConstraint('fee_minor >= 0 AND paid_minor >= 0 AND paid_minor <= fee_minor', name='ck_trip_participant_money'),
            sa.UniqueConstraint('trip_id', 'student_id', name='uq_trip_student'),
        )
        op.create_index('ix_trip_participants_tenant_trip', 'trip_participants', ['tahfiz_id', 'trip_id'])
    if "trip_rounds" not in existing:
        op.create_table(
            "trip_rounds",
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('tahfiz_id', sa.Integer(), sa.ForeignKey('tahfiz.id'), nullable=False),
            sa.Column('trip_id', sa.Integer(), sa.ForeignKey('trips.id'), nullable=False),
            sa.Column('title', sa.String(length=120), nullable=False),
            sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('closed_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_trip_rounds_tenant_trip', 'trip_rounds', ['tahfiz_id', 'trip_id'])
    if "trip_checks" not in existing:
        op.create_table(
            "trip_checks",
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('tahfiz_id', sa.Integer(), sa.ForeignKey('tahfiz.id'), nullable=False),
            sa.Column('trip_id', sa.Integer(), sa.ForeignKey('trips.id'), nullable=False),
            sa.Column('round_id', sa.Integer(), sa.ForeignKey('trip_rounds.id'), nullable=False),
            sa.Column('participant_id', sa.Integer(), sa.ForeignKey('trip_participants.id'), nullable=False),
            sa.Column('group_id', sa.Integer(), sa.ForeignKey('trip_groups.id', ondelete='SET NULL'), nullable=True),
            sa.Column('status', sa.String(length=12), nullable=False),
            sa.Column('checked_at', sa.DateTime(), nullable=True),
            sa.Column('checked_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('version', sa.Integer(), nullable=False),
            sa.UniqueConstraint('round_id', 'participant_id', name='uq_trip_round_participant'),
        )
        op.create_index('ix_trip_checks_tenant_round', 'trip_checks', ['tahfiz_id', 'round_id'])


def downgrade():
    op.drop_table("trip_checks")
    op.drop_table("trip_rounds")
    op.drop_table("trip_participants")
    op.drop_table("trip_groups")
    op.drop_table("trips")
