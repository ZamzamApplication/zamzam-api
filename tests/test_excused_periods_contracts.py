import importlib
import inspect
import unittest
from datetime import date

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect as sa_inspect

from app.excused_periods import automatic_attendance, excused_period_note
from app.models import ExcusedWeekday, Student, StudentExcusedPeriod, Tahfiz, TahfizStatus
from app.routers import management, sessions
from app.schemas import CreateExcusedPeriodRequest


class ExcusedPeriodBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.day = date(2026, 8, 10)
        self.tahfiz = Tahfiz(
            id=7,
            name="Scope",
            status=TahfizStatus.active,
            attendance_statuses='["حاضر", "غياب", "بعذر مخصص", "لا ينطبق"]',
            attendance_streak_status="بعذر مخصص",
        )
        self.student = Student(id=31, name="Student", tahfiz_id=7)
        self.period = StudentExcusedPeriod(
            id=4,
            student_id=31,
            tahfiz_id=7,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 20),
            reason="سفر مع الأسرة",
            created_by_id=11,
        )

    def test_temporary_period_uses_configured_excused_status_and_reason(self):
        status, notes = automatic_attendance(
            self.tahfiz, self.student, self.day, "غياب", period=self.period
        )
        self.assertEqual(status, "بعذر مخصص")
        self.assertEqual(notes, excused_period_note("سفر مع الأسرة"))

    def test_registration_date_precedes_period_and_period_precedes_weekday(self):
        weekday = ExcusedWeekday(student_id=31, weekday=1, note="عذر أسبوعي")
        self.student.registration_date = date(2026, 8, 11)
        self.assertEqual(
            automatic_attendance(
                self.tahfiz, self.student, self.day, "غياب", period=self.period, weekday=weekday
            ),
            ("لا ينطبق", None),
        )
        self.student.registration_date = None
        self.assertEqual(
            automatic_attendance(
                self.tahfiz, self.student, self.day, "غياب", period=self.period, weekday=weekday
            )[0],
            "بعذر مخصص",
        )

    def test_date_range_and_reason_validation(self):
        with self.assertRaises(ValidationError):
            CreateExcusedPeriodRequest(
                start_date=date(2026, 8, 10), end_date=date(2026, 8, 9), reason="سفر"
            )
        with self.assertRaises(ValidationError):
            CreateExcusedPeriodRequest(
                start_date=date(2026, 8, 10), end_date=date(2026, 8, 11), reason=" "
            )

    def test_routes_audit_lifecycle_and_sessions_use_shared_resolution(self):
        lifecycle = {
            management.create_excused_period: "student.excused_period_created",
            management.update_excused_period: "student.excused_period_updated",
            management.cancel_excused_period: "student.excused_period_cancelled",
            management.end_excused_period_early: "student.excused_period_ended_early",
        }
        for function, action in lifecycle.items():
            with self.subTest(function=function.__name__):
                source = inspect.getsource(function)
                self.assertIn(action, source)
                self.assertIn("context.tahfiz_id", source)
        for function in (sessions.create_session, sessions.get_session_attendance, sessions.confirm_session):
            with self.subTest(function=function.__name__):
                self.assertIn("automatic_attendance", inspect.getsource(function))


class ExcusedPeriodMigrationTests(unittest.TestCase):
    def test_migration_creates_table_and_index_idempotently(self):
        migration = importlib.import_module(
            "migrations.versions.20260801_10_student_excused_periods"
        )
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            original_op = migration.op
            migration.op = Operations(MigrationContext.configure(connection))
            try:
                migration.upgrade()
                migration.upgrade()
            finally:
                migration.op = original_op
            inspector = sa_inspect(connection)
            self.assertIn("student_excused_periods", inspector.get_table_names())
            indexes = {item["name"] for item in inspector.get_indexes("student_excused_periods")}
            self.assertIn("ix_student_excused_periods_tenant_student_dates", indexes)
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
