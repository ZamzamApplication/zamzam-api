import importlib
import json
import unittest
from types import SimpleNamespace

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, text

from app.models import StudentCustomField, UserRole
from app.routers.management import (
    can_create_student_custom_fields,
    normalize_student_custom_value,
    serialize_student_custom_field,
)
from app.schemas import StudentCustomFieldRequest


def field(field_type: str, *, options: list[str] | None = None, required: bool = False):
    return StudentCustomField(
        id=7,
        tahfiz_id=2,
        name="المستوى",
        field_type=field_type,
        options=json.dumps(options or [], ensure_ascii=False),
        is_required=required,
        is_active=True,
        sort_order=1,
        created_by_user_id=9,
    )


class StudentCustomFieldContractTests(unittest.TestCase):
    def test_typed_values_are_normalized_and_validated(self):
        self.assertEqual(normalize_student_custom_value(field("number"), "01.50"), "1.50")
        self.assertEqual(normalize_student_custom_value(field("date"), "2026-08-13"), "2026-08-13")
        self.assertEqual(normalize_student_custom_value(field("checkbox"), True), "true")
        self.assertEqual(normalize_student_custom_value(field("select", options=["أ", "ب"]), "ب"), "ب")
        with self.assertRaises(HTTPException):
            normalize_student_custom_value(field("select", options=["أ"]), "ب")
        with self.assertRaises(HTTPException):
            normalize_student_custom_value(field("number"), "NaN")

    def test_required_field_rejects_empty_value(self):
        with self.assertRaises(HTTPException) as error:
            normalize_student_custom_value(field("text", required=True), "")
        self.assertEqual(error.exception.status_code, 422)

    def test_select_schema_requires_options(self):
        with self.assertRaises(ValueError):
            StudentCustomFieldRequest(name="المستوى", field_type="select", options=[])

    def test_sheikh_creation_respects_tahfiz_setting(self):
        enabled = SimpleNamespace(
            effective_role=UserRole.sheikh,
            tahfiz=SimpleNamespace(sheikh_custom_fields_enabled=True),
        )
        disabled = SimpleNamespace(
            effective_role=UserRole.sheikh,
            tahfiz=SimpleNamespace(sheikh_custom_fields_enabled=False),
        )
        self.assertTrue(can_create_student_custom_fields(enabled))
        self.assertFalse(can_create_student_custom_fields(disabled))

    def test_field_serialization_keeps_stable_id_and_creator_permissions(self):
        context = SimpleNamespace(effective_role=UserRole.sheikh, user=SimpleNamespace(id=9))
        result = serialize_student_custom_field(field("select", options=["أ", "ب"]), context)
        self.assertEqual(result["id"], 7)
        self.assertEqual(result["options"], ["أ", "ب"])
        self.assertTrue(result["can_edit"])

    def test_custom_field_migration_roundtrip(self):
        migration = importlib.import_module("migrations.versions.20260813_22_student_custom_fields")
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE tahfiz (id INTEGER PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE students (id INTEGER PRIMARY KEY)"))
            operations = Operations(MigrationContext.configure(connection))
            original_op = migration.op
            migration.op = operations
            try:
                migration.upgrade()
                self.assertTrue({"student_custom_fields", "student_custom_field_values"}.issubset(inspect(connection).get_table_names()))
                self.assertIn("sheikh_custom_fields_enabled", {column["name"] for column in inspect(connection).get_columns("tahfiz")})
                migration.downgrade()
                self.assertNotIn("student_custom_fields", inspect(connection).get_table_names())
            finally:
                migration.op = original_op
        engine.dispose()
