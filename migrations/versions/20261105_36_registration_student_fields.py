"""Select existing student fields for public registration forms."""
from alembic import op
import sqlalchemy as sa

revision = "20261105_36"
down_revision = "20261101_35"
branch_labels = None
depends_on = None


def upgrade():
    additions = {
        "student_registration_forms": [
            ("student_fields", '["phone", "birthday"]'),
            ("required_student_fields", '[]'),
        ],
        "student_registration_requests": [("student_data", '{}')],
    }
    for table, columns in additions.items():
        existing = {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}
        for name, default in columns:
            if name not in existing:
                op.add_column(table, sa.Column(name, sa.Text(), nullable=False, server_default=default))


def downgrade():
    op.drop_column("student_registration_requests", "student_data")
    op.drop_column("student_registration_forms", "required_student_fields")
    op.drop_column("student_registration_forms", "student_fields")
