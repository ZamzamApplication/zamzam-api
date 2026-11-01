"""Weekly session schedules and durable occurrence receipts."""
from alembic import op
import sqlalchemy as sa

revision = '20261101_35'
down_revision = '20261031_34'
branch_labels = None
depends_on = None


def upgrade():
    tables = sa.inspect(op.get_bind()).get_table_names()
    if 'session_schedules' not in tables:
        op.create_table('session_schedules',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('tahfiz_id', sa.Integer(), sa.ForeignKey('tahfiz.id'), nullable=False),
            sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('name', sa.String(100)),
            sa.Column('weekdays', sa.Text(), nullable=False),
            sa.Column('start_date', sa.Date(), nullable=False),
            sa.Column('end_date', sa.Date()),
            sa.Column('timezone', sa.String(64), nullable=False),
            sa.Column('membership_mode', sa.String(16), nullable=False),
            sa.Column('member_ids', sa.Text(), nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=False),
            sa.Column('version', sa.Integer(), nullable=False))
        op.create_index('ix_session_schedules_tahfiz_id', 'session_schedules', ['tahfiz_id'])
    if 'session_occurrences' not in tables:
        op.create_table('session_occurrences',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('schedule_id', sa.Integer(), sa.ForeignKey('session_schedules.id'), nullable=False),
            sa.Column('tahfiz_id', sa.Integer(), sa.ForeignKey('tahfiz.id'), nullable=False),
            sa.Column('date', sa.Date(), nullable=False),
            sa.Column('session_id', sa.Integer(), sa.ForeignKey('sessions.id', ondelete='SET NULL')),
            sa.Column('status', sa.String(16), nullable=False),
            sa.UniqueConstraint('schedule_id', 'date', name='uq_schedule_occurrence_date'))
        op.create_index('ix_session_occurrences_schedule_id', 'session_occurrences', ['schedule_id'])
        op.create_index('ix_session_occurrences_tahfiz_id', 'session_occurrences', ['tahfiz_id'])


def downgrade():
    op.drop_table('session_occurrences')
    op.drop_table('session_schedules')
