import importlib

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text


def test_session_name_options_migration_roundtrip():
    migration = importlib.import_module("migrations.versions.20260813_21_session_name_options")
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE tahfiz (id INTEGER PRIMARY KEY)"))
        connection.execute(text("INSERT INTO tahfiz (id) VALUES (1)"))
        operations = Operations(MigrationContext.configure(connection))
        original_op = migration.op
        migration.op = operations
        try:
            migration.upgrade()
            assert "session_name_options" in {column["name"] for column in inspect(connection).get_columns("tahfiz")}
            assert connection.execute(text("SELECT session_name_options FROM tahfiz")).scalar_one() == '["الصباحية", "المسائية"]'
            migration.downgrade()
            assert "session_name_options" not in {column["name"] for column in inspect(connection).get_columns("tahfiz")}
        finally:
            migration.op = original_op
    engine.dispose()
