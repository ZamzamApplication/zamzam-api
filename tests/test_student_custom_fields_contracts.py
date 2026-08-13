import importlib
import json
from types import SimpleNamespace

import pytest
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


def test_typed_values_are_normalized_and_validated():
    assert normalize_student_custom_value(field("number"), "01.50") == "1.50"
    assert normalize_student_custom_value(field("date"), "2026-08-13") == "2026-08-13"
    assert normalize_student_custom_value(field("checkbox"), True) == "true"
    assert normalize_student_custom_value(field("select", options=["أ", "ب"]), "ب") == "ب"
    with pytest.raises(HTTPException):
        normalize_student_custom_value(field("select", options=["أ"]), "ب")
    with pytest.raises(HTTPException):
        normalize_student_custom_value(field("number"), "NaN")


def test_required_field_rejects_empty_value():
    with pytest.raises(HTTPException) as error:
        normalize_student_custom_value(field("text", required=True), "")
    assert error.value.status_code == 422


def test_select_schema_requires_options():
    with pytest.raises(ValueError):
        StudentCustomFieldRequest(name="المستوى", field_type="select", options=[])


def test_sheikh_creation_respects_tahfiz_setting():
    enabled = SimpleNamespace(
        effective_role=UserRole.sheikh,
        tahfiz=SimpleNamespace(sheikh_custom_fields_enabled=True),
    )
    disabled = SimpleNamespace(
        effective_role=UserRole.sheikh,
        tahfiz=SimpleNamespace(sheikh_custom_fields_enabled=False),
    )
    assert can_create_student_custom_fields(enabled) is True
    assert can_create_student_custom_fields(disabled) is False


def test_field_serialization_keeps_stable_id_and_creator_permissions():
    context = SimpleNamespace(effective_role=UserRole.sheikh, user=SimpleNamespace(id=9))
    result = serialize_student_custom_field(field("select", options=["أ", "ب"]), context)
    assert result["id"] == 7
    assert result["options"] == ["أ", "ب"]
    assert result["can_edit"] is True


def test_custom_field_migration_roundtrip():
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
            assert {"student_custom_fields", "student_custom_field_values"}.issubset(inspect(connection).get_table_names())
            assert "sheikh_custom_fields_enabled" in {column["name"] for column in inspect(connection).get_columns("tahfiz")}
            migration.downgrade()
            assert "student_custom_fields" not in inspect(connection).get_table_names()
        finally:
            migration.op = original_op
    engine.dispose()
