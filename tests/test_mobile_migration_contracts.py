import importlib
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text


class MobileMigrationUpgradeTests(unittest.TestCase):
    def test_student_quran_plan_migration_creates_forward_only_plan_table(self):
        migration = importlib.import_module("migrations.versions.20260809_16_student_quran_plans")
        with TemporaryDirectory(prefix="zamzam-quran-plan-migration-") as temporary:
            path = Path(temporary) / "production.db"
            engine = create_engine(f"sqlite:///{path}")
            with engine.begin() as connection:
                connection.execute(text("CREATE TABLE tahfiz (id INTEGER PRIMARY KEY)"))
                connection.execute(text("CREATE TABLE students (id INTEGER PRIMARY KEY)"))
                operations = Operations(MigrationContext.configure(connection))
                original_op = migration.op
                migration.op = operations
                try:
                    migration.upgrade()
                finally:
                    migration.op = original_op

                inspector = inspect(connection)
                self.assertIn("student_quran_plans", inspector.get_table_names())
                columns = {column["name"] for column in inspector.get_columns("student_quran_plans")}
                self.assertTrue({
                    "tahfiz_id", "student_id", "category", "increment_unit",
                    "increment_amount", "next_surah", "next_ayah", "next_page",
                    "last_advanced_session_id",
                }.issubset(columns))
            engine.dispose()

    def test_existing_sqlite_database_gets_timestamp_without_nonconstant_default(self):
        migration = importlib.import_module("migrations.versions.20260724_02_mobile_sync")
        with TemporaryDirectory(prefix="zamzam-mobile-migration-") as temporary:
            path = Path(temporary) / "production.db"
            database = sqlite3.connect(path)
            database.executescript("""
                CREATE TABLE tahfiz (id INTEGER PRIMARY KEY);
                CREATE TABLE users (id INTEGER PRIMARY KEY);
                CREATE TABLE sessions (id INTEGER PRIMARY KEY, tahfiz_id INTEGER NOT NULL);
                CREATE TABLE students (id INTEGER PRIMARY KEY, tahfiz_id INTEGER NOT NULL);
                CREATE TABLE sheikhs (id INTEGER PRIMARY KEY, tahfiz_id INTEGER NOT NULL);
                CREATE TABLE attendance (
                    id INTEGER PRIMARY KEY,
                    tahfiz_id INTEGER NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE quran_progress_entries (
                    id INTEGER PRIMARY KEY,
                    tahfiz_id INTEGER NOT NULL,
                    session_id INTEGER NOT NULL,
                    student_id INTEGER NOT NULL,
                    category VARCHAR(40) NOT NULL
                );
                INSERT INTO tahfiz (id) VALUES (1);
                INSERT INTO attendance (id, tahfiz_id) VALUES (1, 1);
            """)
            database.commit()
            database.close()

            engine = create_engine(f"sqlite:///{path}")
            with engine.begin() as connection:
                operations = Operations(MigrationContext.configure(connection))
                original_op = migration.op
                migration.op = operations
                try:
                    migration.upgrade()
                finally:
                    migration.op = original_op

                columns = {
                    column["name"]: column
                    for column in inspect(connection).get_columns("attendance")
                }
                updated_at = connection.execute(
                    text("SELECT updated_at FROM attendance WHERE id = 1")
                ).scalar_one()
                self.assertIn("updated_at", columns)
                self.assertFalse(columns["updated_at"]["nullable"])
                self.assertNotEqual(str(updated_at), "1970-01-01 00:00:00")
                self.assertIn("device_sessions", inspect(connection).get_table_names())
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
