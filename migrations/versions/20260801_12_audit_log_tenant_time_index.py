"""Index tenant audit logs by creation time."""

from alembic import op
import sqlalchemy as sa


revision = "20260801_12"
down_revision = "20260801_11"
branch_labels = None
depends_on = None


INDEX_NAME = "ix_audit_logs_tahfiz_created"


def upgrade() -> None:
    bind = op.get_bind()
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("audit_logs")}
    if INDEX_NAME not in indexes:
        op.create_index(INDEX_NAME, "audit_logs", ["tahfiz_id", "created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("audit_logs")}
    if INDEX_NAME in indexes:
        op.drop_index(INDEX_NAME, table_name="audit_logs")
