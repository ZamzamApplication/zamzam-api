"""Preserve session data when archiving and recovering sessions."""
from alembic import op
import sqlalchemy as sa
revision = '20261031_33'
down_revision = '20261018_32'
branch_labels = None
depends_on = None

def upgrade():
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('sessions')}
    if 'archived_at' not in columns:
        op.add_column('sessions', sa.Column('archived_at', sa.DateTime(), nullable=True))

def downgrade():
    op.drop_column('sessions', 'archived_at')
