"""Keep independent completion for each daily plan assignment."""

from alembic import op
import sqlalchemy as sa

revision = "20261002_30"
down_revision = "20261001_29"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("personal_plans")}
    for name in ("assignment_ids", "completed_items"):
        if name not in columns:
            op.add_column("personal_plans", sa.Column(name, sa.Text(), nullable=False, server_default="{}"))


def downgrade() -> None:
    with op.batch_alter_table("personal_plans") as batch:
        batch.drop_column("completed_items")
        batch.drop_column("assignment_ids")
