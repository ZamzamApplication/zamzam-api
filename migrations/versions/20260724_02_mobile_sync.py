"""Add mobile synchronization and device sessions.

Revision ID: 20260724_02
Revises: 20260723_01
Create Date: 2026-07-24
"""
from alembic import op
import sqlalchemy as sa


revision = "20260724_02"
down_revision = "20260723_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    attendance_columns = {column["name"] for column in inspector.get_columns("attendance")}
    if "revision" not in attendance_columns:
        op.add_column("attendance", sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
    if "updated_at" not in attendance_columns:
        op.add_column(
            "attendance",
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                # SQLite only permits constant defaults when ALTER TABLE adds
                # a column. Existing rows are backfilled immediately below.
                server_default=sa.text("'1970-01-01 00:00:00'"),
            ),
        )
        op.execute(sa.text(
            "UPDATE attendance SET updated_at = CURRENT_TIMESTAMP "
            "WHERE updated_at = '1970-01-01 00:00:00'"
        ))

    progress_columns = {column["name"] for column in inspector.get_columns("quran_progress_entries")}
    if "revision" not in progress_columns:
        op.add_column("quran_progress_entries", sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))

    tables = set(inspector.get_table_names())
    if "device_sessions" not in tables:
        op.create_table(
            "device_sessions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("device_id", sa.String(100), nullable=False),
            sa.Column("device_name", sa.String(100)),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("last_used_at", sa.DateTime(), nullable=False),
            sa.Column("revoked_at", sa.DateTime()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_device_sessions_user_id", "device_sessions", ["user_id"])
        op.create_index("ix_device_sessions_token_hash", "device_sessions", ["token_hash"], unique=True)
        op.create_index("ix_device_sessions_user_revoked", "device_sessions", ["user_id", "revoked_at"])

    if "sync_changes" not in tables:
        op.create_table(
            "sync_changes",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("tahfiz_id", sa.Integer(), sa.ForeignKey("tahfiz.id"), nullable=False),
            sa.Column("entity_type", sa.String(40), nullable=False),
            sa.Column("entity_key", sa.String(160), nullable=False),
            sa.Column("operation", sa.String(10), nullable=False),
            sa.Column("payload_json", sa.Text()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_sync_changes_tahfiz_id", "sync_changes", ["tahfiz_id"])
        op.create_index("ix_sync_changes_tahfiz_cursor", "sync_changes", ["tahfiz_id", "id"])

    if "sync_mutation_receipts" not in tables:
        op.create_table(
            "sync_mutation_receipts",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("tahfiz_id", sa.Integer(), sa.ForeignKey("tahfiz.id"), nullable=False),
            sa.Column("mutation_id", sa.String(64), nullable=False),
            sa.Column("device_id", sa.String(100), nullable=False),
            sa.Column("result_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("tahfiz_id", "mutation_id", name="uq_sync_mutation_tenant_id"),
        )
        op.create_index("ix_sync_mutation_receipts_tahfiz_id", "sync_mutation_receipts", ["tahfiz_id"])

    # A bootstrap is the source of truth for existing data. These triggers make
    # every later web, API, or mobile change visible to incremental clients.
    if bind.dialect.name == "sqlite":
        trigger_specs = {
            "attendance": ("attendance", "CAST(NEW.id AS TEXT)", "NEW.tahfiz_id"),
            "quran_progress_entries": (
                "quran_progress",
                "NEW.session_id || ':' || NEW.student_id || ':' || NEW.category",
                "NEW.tahfiz_id",
            ),
            "sessions": ("session", "CAST(NEW.id AS TEXT)", "NEW.tahfiz_id"),
            "students": ("student", "CAST(NEW.id AS TEXT)", "NEW.tahfiz_id"),
            "sheikhs": ("sheikh", "CAST(NEW.id AS TEXT)", "NEW.tahfiz_id"),
        }
        for table, (entity_type, key_expr, tenant_expr) in trigger_specs.items():
            for event, operation in (("INSERT", "upsert"), ("UPDATE", "upsert")):
                op.execute(sa.text(
                    f"CREATE TRIGGER IF NOT EXISTS sync_{table}_{event.lower()} AFTER {event} ON {table} "
                    "BEGIN "
                    "INSERT INTO sync_changes "
                    "(tahfiz_id, entity_type, entity_key, operation, payload_json, created_at) "
                    f"VALUES ({tenant_expr}, '{entity_type}', {key_expr}, '{operation}', NULL, CURRENT_TIMESTAMP); "
                    "END"
                ))
            old_key = key_expr.replace("NEW.", "OLD.")
            old_tenant = tenant_expr.replace("NEW.", "OLD.")
            op.execute(sa.text(
                f"CREATE TRIGGER IF NOT EXISTS sync_{table}_delete AFTER DELETE ON {table} "
                "BEGIN "
                "INSERT INTO sync_changes "
                "(tahfiz_id, entity_type, entity_key, operation, payload_json, created_at) "
                f"VALUES ({old_tenant}, '{entity_type}', {old_key}, 'delete', NULL, CURRENT_TIMESTAMP); "
                "END"
            ))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        for table in ("attendance", "quran_progress_entries", "sessions", "students", "sheikhs"):
            for event in ("insert", "update", "delete"):
                op.execute(sa.text(f"DROP TRIGGER IF EXISTS sync_{table}_{event}"))
    op.drop_table("sync_mutation_receipts")
    op.drop_table("sync_changes")
    op.drop_table("device_sessions")
    with op.batch_alter_table("quran_progress_entries") as batch:
        batch.drop_column("revision")
    with op.batch_alter_table("attendance") as batch:
        batch.drop_column("updated_at")
        batch.drop_column("revision")
