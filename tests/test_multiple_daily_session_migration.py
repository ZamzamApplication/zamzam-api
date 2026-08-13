import importlib
import unittest

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text


class MultipleDailySessionMigrationTests(unittest.TestCase):
    def test_upgrade_backfills_stable_sequences_and_downgrades(self):
        migration = importlib.import_module("migrations.versions.20260811_20_multiple_daily_sessions")
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE tahfiz (id INTEGER PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE students (id INTEGER PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE sessions (id INTEGER PRIMARY KEY, tahfiz_id INTEGER NOT NULL, date DATE NOT NULL)"))
            connection.execute(text("CREATE TABLE student_quran_plans (id INTEGER PRIMARY KEY, last_advanced_session_id INTEGER)"))
            connection.execute(text("INSERT INTO tahfiz (id) VALUES (1)"))
            connection.execute(text("INSERT INTO sessions VALUES (1,1,'2026-08-11'),(2,1,'2026-08-11'),(3,1,'2026-08-12')"))
            operations = Operations(MigrationContext.configure(connection))
            original_op = migration.op
            migration.op = operations
            try:
                migration.upgrade()
                self.assertEqual(
                    connection.execute(text("SELECT id, daily_sequence FROM sessions ORDER BY id")).all(),
                    [(1, 1), (2, 2), (3, 1)],
                )
                self.assertTrue({"student_categories", "student_category_memberships"}.issubset(inspect(connection).get_table_names()))
                self.assertEqual(connection.execute(text("SELECT multiple_sessions_per_day_enabled FROM tahfiz")).scalar_one(), 0)
                migration.downgrade()
                self.assertNotIn("student_categories", inspect(connection).get_table_names())
                self.assertNotIn("daily_sequence", {column["name"] for column in inspect(connection).get_columns("sessions")})
            finally:
                migration.op = original_op
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
