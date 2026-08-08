"""Remove unpaid subscription rows orphaned by deleted students."""

from alembic import op
import sqlalchemy as sa


revision = "20260808_15"
down_revision = "20260808_14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM student_subscriptions "
            "WHERE student_id IS NULL AND is_paid = FALSE"
        )
    )


def downgrade() -> None:
    pass
