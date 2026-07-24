import unittest
from datetime import datetime
from importlib import import_module
from tempfile import TemporaryDirectory
from pathlib import Path

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect

from app.database import Base
from app.models import (
    AuditLog,
    FeedbackCategory,
    FeedbackReport,
    FeedbackStatus,
    Tahfiz,
    TahfizStatus,
    User,
    UserRole,
)
from app.routers.auth import TenantContext
from app.routers.feedback import create_feedback, update_feedback_status
from app.schemas import CreateFeedbackRequest, UpdateFeedbackStatusRequest


def make_user(user_id: int, role: UserRole = UserRole.admin) -> User:
    return User(
        id=user_id,
        username=f"user-{user_id}",
        password_hash="not-used",
        role=role,
        tahfiz_id=8 if role != UserRole.super_admin else None,
    )


def make_context() -> TenantContext:
    return TenantContext(
        user=make_user(11),
        tahfiz=Tahfiz(id=8, name="تحفيظ الاختبار", status=TahfizStatus.active),
        role=UserRole.admin,
    )


class _OneResult:
    def __init__(self, row):
        self.row = row

    def one(self):
        return self.row


class _FeedbackSession:
    def __init__(self, report: FeedbackReport | None = None):
        self.report = report
        self.added: list[object] = []
        self.commits = 0

    def add(self, value):
        self.added.append(value)
        if isinstance(value, FeedbackReport):
            self.report = value

    async def flush(self):
        assert self.report is not None
        self.report.id = 91
        self.report.created_at = datetime(2026, 7, 24, 12, 0)
        self.report.updated_at = datetime(2026, 7, 24, 12, 0)

    async def commit(self):
        self.commits += 1

    async def refresh(self, _value):
        return None

    async def get(self, model, item_id):
        if model is FeedbackReport and self.report and self.report.id == item_id:
            return self.report
        return None

    async def execute(self, _statement):
        assert self.report is not None
        return _OneResult((
            self.report,
            self.report.reporter_username,
            "تحفيظ الاختبار",
            "platform-admin",
        ))


class FeedbackSchemaTests(unittest.TestCase):
    def test_submission_rejects_blank_or_too_short_content(self):
        with self.assertRaises(ValidationError):
            CreateFeedbackRequest(category="bug", title="     ", description="وصف كاف للمشكلة")
        with self.assertRaises(ValidationError):
            CreateFeedbackRequest(category="bug", title="عنوان جيد", description="قصير")

    def test_review_status_is_limited_to_known_workflow_values(self):
        with self.assertRaises(ValidationError):
            UpdateFeedbackStatusRequest(status="deleted")


class FeedbackTenantContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_submission_uses_authenticated_tenant_and_user(self):
        db = _FeedbackSession()
        context = make_context()

        response = await create_feedback(
            body=CreateFeedbackRequest(
                category="bug",
                title="مشكلة في قائمة الطلاب",
                description="لا تظهر قائمة الطلاب بعد فتح صفحة الإدارة.",
                page_url="/manage",
            ),
            db=db,
            context=context,
        )

        report = next(value for value in db.added if isinstance(value, FeedbackReport))
        audit = next(value for value in db.added if isinstance(value, AuditLog))
        self.assertEqual(report.reporter_user_id, context.user.id)
        self.assertEqual(report.reporter_username, context.user.username)
        self.assertEqual(report.tahfiz_id, context.tahfiz.id)
        self.assertEqual(report.status, FeedbackStatus.open)
        self.assertEqual(audit.tahfiz_id, context.tahfiz.id)
        self.assertEqual(audit.action, "feedback.created")
        self.assertEqual(response["tahfiz_name"], context.tahfiz.name)
        self.assertEqual(db.commits, 1)

    async def test_super_admin_review_records_status_and_audit(self):
        report = FeedbackReport(
            id=91,
            reporter_user_id=11,
            reporter_username="user-11",
            tahfiz_id=8,
            category=FeedbackCategory.bug,
            title="مشكلة في قائمة الطلاب",
            description="لا تظهر قائمة الطلاب بعد فتح صفحة الإدارة.",
            status=FeedbackStatus.open,
            created_at=datetime(2026, 7, 24, 12, 0),
            updated_at=datetime(2026, 7, 24, 12, 0),
        )
        db = _FeedbackSession(report)
        admin = make_user(1, UserRole.super_admin)
        admin.username = "platform-admin"

        response = await update_feedback_status(
            feedback_id=91,
            body=UpdateFeedbackStatusRequest(
                status="resolved",
                resolution_note="تم إصلاح تحميل القائمة.",
            ),
            db=db,
            admin=admin,
        )

        audit = next(value for value in db.added if isinstance(value, AuditLog))
        self.assertEqual(report.status, FeedbackStatus.resolved)
        self.assertEqual(report.reviewed_by_id, admin.id)
        self.assertEqual(report.resolution_note, "تم إصلاح تحميل القائمة.")
        self.assertEqual(audit.action, "feedback.status_changed")
        self.assertIn("from=open", audit.details)
        self.assertIn("to=resolved", audit.details)
        self.assertEqual(response["status"], "resolved")
        self.assertEqual(db.commits, 1)


class FeedbackMigrationTests(unittest.TestCase):
    def test_feedback_revision_upgrades_and_downgrades_sqlite(self):
        migration = import_module("migrations.versions.20260724_03_feedback")
        with TemporaryDirectory(prefix="zamzam-feedback-migration-") as temporary:
            engine = create_engine(f"sqlite:///{Path(temporary) / 'feedback.db'}")
            without_feedback = [
                table for table in Base.metadata.sorted_tables
                if table.name != "feedback_reports"
            ]
            Base.metadata.create_all(engine, tables=without_feedback)
            with engine.begin() as connection:
                operations = Operations(MigrationContext.configure(connection))
                original_op = migration.op
                migration.op = operations
                try:
                    migration.upgrade()
                    columns = {
                        column["name"]
                        for column in inspect(connection).get_columns("feedback_reports")
                    }
                    self.assertTrue({
                        "reporter_user_id",
                        "tahfiz_id",
                        "status",
                        "resolution_note",
                    }.issubset(columns))
                    migration.downgrade()
                    self.assertNotIn("feedback_reports", inspect(connection).get_table_names())
                finally:
                    migration.op = original_op
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
