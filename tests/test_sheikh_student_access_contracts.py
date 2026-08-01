import importlib
import inspect
import unittest

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect as sa_inspect, select, text
from sqlalchemy.orm import Session as OrmSession

from app.database import Base
from app.models import Sheikh, Student, Tahfiz, TahfizStatus, User, UserRole
from app.routers import attendance, management, progress, reports, sync
from app.routers.auth import TenantContext, student_scope_clause
from app.routers.management import serialize_tahfiz
from app.schemas import UpdateTahfizSettingsRequest


def make_context(
    role: UserRole,
    *,
    restricted: bool = True,
    tahfiz_id: int = 7,
    sheikh_id: int | None = 3,
) -> TenantContext:
    return TenantContext(
        user=User(
            id=11,
            username="scope-test",
            password_hash="not-used",
            role=role,
            tahfiz_id=tahfiz_id,
        ),
        tahfiz=Tahfiz(
            id=tahfiz_id,
            name="Scope",
            status=TahfizStatus.active,
            restrict_sheikh_student_access=restricted,
        ),
        role=role,
        sheikh_id=sheikh_id,
    )


class SheikhStudentScopeTests(unittest.TestCase):
    def compiled_scope(self, context: TenantContext) -> tuple[str, list[object]]:
        statement = select(Student.id).where(student_scope_clause(context))
        compiled = statement.compile()
        return str(compiled), list(compiled.params.values())

    def test_setting_defaults_to_restricted_and_can_be_disabled(self):
        column = Tahfiz.__table__.c.restrict_sheikh_student_access
        tahfiz = Tahfiz(id=7, name="Scope", status=TahfizStatus.active)

        self.assertIs(column.default.arg, True)
        self.assertIs(serialize_tahfiz(tahfiz)["restrict_sheikh_student_access"], True)
        self.assertIs(
            UpdateTahfizSettingsRequest(restrict_sheikh_student_access=False).restrict_sheikh_student_access,
            False,
        )

    def test_restricted_sheikh_scope_contains_tenant_and_assignment(self):
        sql, params = self.compiled_scope(make_context(UserRole.sheikh))

        self.assertIn("students.tahfiz_id", sql)
        self.assertIn("students.sheikh_id", sql)
        self.assertIn(7, params)
        self.assertIn(3, params)

    def test_admin_and_unrestricted_sheikh_keep_tenant_scope_only(self):
        admin_sql, _ = self.compiled_scope(make_context(UserRole.admin))
        open_sql, _ = self.compiled_scope(make_context(UserRole.sheikh, restricted=False))

        self.assertNotIn("students.sheikh_id", admin_sql)
        self.assertNotIn("students.sheikh_id", open_sql)
        self.assertIn("students.tahfiz_id", admin_sql)
        self.assertIn("students.tahfiz_id", open_sql)

    def test_restricted_unassigned_sheikh_matches_no_students(self):
        sql, _ = self.compiled_scope(make_context(UserRole.sheikh, sheikh_id=None))

        self.assertIn("false", sql.lower())

    def test_scope_executes_as_assigned_only_and_toggle_can_restore_tenant_access(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with OrmSession(engine) as db:
            db.add_all([
                Tahfiz(id=7, name="Scope", status=TahfizStatus.active),
                Sheikh(id=3, name="Assigned", tahfiz_id=7),
                Sheikh(id=4, name="Other", tahfiz_id=7),
                Student(id=31, name="Assigned student", tahfiz_id=7, sheikh_id=3),
                Student(id=32, name="Other student", tahfiz_id=7, sheikh_id=4),
                Student(id=33, name="Another tenant", tahfiz_id=8),
                Tahfiz(id=8, name="Other tenant", status=TahfizStatus.active),
            ])
            db.commit()

            restricted = db.scalars(select(Student).where(
                student_scope_clause(make_context(UserRole.sheikh))
            )).all()
            unrestricted = db.scalars(select(Student).where(
                student_scope_clause(make_context(UserRole.sheikh, restricted=False))
            )).all()

            self.assertEqual([student.id for student in restricted], [31])
            self.assertEqual([student.id for student in unrestricted], [31, 32])
        engine.dispose()

    def test_student_routes_use_the_shared_backend_scope(self):
        guarded_functions = [
            management.student_profile,
            attendance.update_attendance,
            attendance.upsert_attendance,
            attendance.batch_attendance,
            progress.session_progress,
            progress.save_session_progress,
            progress.student_progress,
            progress.create_student_goal,
            progress.update_student_goal,
            progress.progress_report,
            reports.circle_attendance_rate,
            reports.circle_student_stats,
            reports.student_streak,
            reports.attendance_grid,
            sync.bootstrap,
            sync.apply_attendance,
            sync.apply_progress,
        ]

        for function in guarded_functions:
            with self.subTest(function=function.__name__):
                self.assertIn("student_scope_clause", inspect.getsource(function))


class SheikhStudentScopeMigrationTests(unittest.TestCase):
    def test_migration_adds_secure_default_and_is_idempotent(self):
        migration = importlib.import_module(
            "migrations.versions.20260801_09_restrict_sheikh_student_access"
        )
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE tahfiz (id INTEGER PRIMARY KEY, name VARCHAR(100))"))
            original_op = migration.op
            migration.op = Operations(MigrationContext.configure(connection))
            try:
                migration.upgrade()
                migration.upgrade()
            finally:
                migration.op = original_op

            columns = {
                column["name"]: column
                for column in sa_inspect(connection).get_columns("tahfiz")
            }
            self.assertIn("restrict_sheikh_student_access", columns)
            connection.execute(text("INSERT INTO tahfiz (id, name) VALUES (1, 'Existing')"))
            value = connection.execute(text(
                "SELECT restrict_sheikh_student_access FROM tahfiz WHERE id = 1"
            )).scalar_one()
            self.assertEqual(value, 1)
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
