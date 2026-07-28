import importlib
import json
import unittest

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from app.models import DEFAULT_EXCEL_EXPORT_TEMPLATES


class ExcelExportSettingsMigrationTests(unittest.TestCase):
    def test_existing_tahfiz_gets_default_export_templates(self):
        migration = importlib.import_module("migrations.versions.20260728_07_excel_export_templates")
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE tahfiz (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"))
            connection.execute(text("INSERT INTO tahfiz (id, name) VALUES (1, 'اختبار')"))
            operations = Operations(MigrationContext.configure(connection))
            original_op = migration.op
            migration.op = operations
            try:
                migration.upgrade()
            finally:
                migration.op = original_op

            columns = {column["name"] for column in inspect(connection).get_columns("tahfiz")}
            stored = connection.execute(
                text("SELECT excel_export_templates FROM tahfiz WHERE id = 1")
            ).scalar_one()
            self.assertIn("excel_export_templates", columns)
            self.assertEqual(json.loads(stored), DEFAULT_EXCEL_EXPORT_TEMPLATES)
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
