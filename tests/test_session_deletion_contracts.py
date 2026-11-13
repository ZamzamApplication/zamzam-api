import inspect
import unittest
from datetime import date, datetime
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import (
    Attendance, AttendanceBatchOperation, AttendanceStatus, AuditLog,
    QuranProgressEntry, QuranProgressRevision, QuranRangeType, Session,
    Student, Tahfiz, User, UserRole,
)
from app.routers import sessions


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeSessionDb:
    def __init__(self, session=None):
        self.session = session
        self.execute_count = 0
        self.added = []
        self.deleted = []
        self.committed = False

    async def execute(self, _statement):
        self.execute_count += 1
        if self.execute_count == 1:
            return ScalarResult(self.session)
        return ScalarResult(None)

    def add(self, value):
        self.added.append(value)

    async def delete(self, value):
        self.deleted.append(value)

    async def commit(self):
        self.committed = True


def make_context(tahfiz_id=1):
    return SimpleNamespace(
        tahfiz_id=tahfiz_id,
        user=SimpleNamespace(id=10),
    )


def make_session(*, confirmed=False, reopened=False, tahfiz_id=1):
    return Session(
        id=101,
        date=date(2026, 8, 1),
        tahfiz_id=tahfiz_id,
        is_confirmed=confirmed,
        reopened_at=datetime(2026, 8, 2) if reopened else None,
        reopened_reason="تصحيح الحضور" if reopened else None,
        reopened_by_id=10 if reopened else None,
    )


class SessionDeletionContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_delete_session_with_progress_revisions_preserves_other_tenant(self):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")

        @event.listens_for(engine.sync_engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with factory() as db:
                for tenant_id in (1, 2):
                    db.add(Tahfiz(id=tenant_id, name=f"Tenant {tenant_id}"))
                    await db.flush()
                    db.add(User(id=tenant_id * 10, username=f"admin{tenant_id}",
                                password_hash="x", role=UserRole.admin, tahfiz_id=tenant_id))
                    db.add(Student(id=tenant_id, name="Student", tahfiz_id=tenant_id))
                    db.add(Session(id=tenant_id, date=date(2026, 11, 1), tahfiz_id=tenant_id,
                                   reopened_at=datetime(2026, 11, 2)))
                    await db.flush()
                    db.add(QuranProgressEntry(
                        id=tenant_id, tahfiz_id=tenant_id, session_id=tenant_id,
                        student_id=tenant_id, recorded_by_id=tenant_id * 10,
                        category="memorization", range_type=QuranRangeType.surah_ayah,
                        from_surah=1, from_ayah=1, to_surah=1, to_ayah=3, quality_score=5,
                    ))
                    db.add(Attendance(tahfiz_id=tenant_id, session_id=tenant_id,
                                      student_id=tenant_id, status=AttendanceStatus.present))
                    db.add(AttendanceBatchOperation(
                        tahfiz_id=tenant_id, session_id=tenant_id,
                        idempotency_key="batch", resulting_version=1,
                    ))
                    await db.flush()
                    db.add(QuranProgressRevision(
                        id=tenant_id, tahfiz_id=tenant_id, session_id=tenant_id,
                        student_id=tenant_id, progress_entry_id=tenant_id,
                        editor_user_id=tenant_id * 10, category="memorization",
                        before_json="{}", after_json="{}",
                    ))
                    await db.flush()
                await db.commit()

            async with factory() as db:
                response = await sessions.delete_session(1, db=db, context=make_context())
                self.assertEqual(response["message"], "Session deleted")

            async with factory() as db:
                for model in (Session, QuranProgressEntry, QuranProgressRevision,
                              Attendance, AttendanceBatchOperation):
                    rows = list((await db.scalars(select(model))).all())
                    self.assertEqual(len(rows), 1, model.__name__)
                    self.assertEqual(rows[0].tahfiz_id, 2, model.__name__)
                audit = (await db.scalars(select(AuditLog))).one()
                self.assertEqual(audit.action, "session.deleted")
                self.assertEqual(audit.tahfiz_id, 1)
        finally:
            await engine.dispose()

    async def test_confirmed_session_requires_reopening_before_delete(self):
        session = make_session(confirmed=True)
        db = FakeSessionDb(session)

        with self.assertRaises(HTTPException) as raised:
            await sessions.delete_session(session_id=session.id, db=db, context=make_context())

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail["code"], "confirmed_session_delete_forbidden")
        self.assertEqual(raised.exception.detail["required_action"], "reopen")
        self.assertEqual(db.deleted, [])
        self.assertFalse(db.committed)

    async def test_draft_session_can_be_deleted_and_is_audited(self):
        session = make_session()
        db = FakeSessionDb(session)

        response = await sessions.delete_session(session_id=session.id, db=db, context=make_context())

        self.assertEqual(response["message"], "Session deleted")
        self.assertEqual(db.deleted, [session])
        self.assertTrue(db.committed)
        audit = next(value for value in db.added if isinstance(value, AuditLog))
        self.assertIn("previous_status=draft", audit.details)

    async def test_reopened_session_can_be_deleted_and_is_audited(self):
        session = make_session(reopened=True)
        db = FakeSessionDb(session)

        await sessions.delete_session(session_id=session.id, db=db, context=make_context())

        self.assertEqual(db.deleted, [session])
        audit = next(value for value in db.added if isinstance(value, AuditLog))
        self.assertIn("previous_status=reopened", audit.details)

    async def test_missing_or_cross_tenant_session_is_not_disclosed(self):
        db = FakeSessionDb(session=None)

        with self.assertRaises(HTTPException) as raised:
            await sessions.delete_session(session_id=201, db=db, context=make_context())

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(db.deleted, [])

    def test_delete_lookup_is_tenant_scoped(self):
        source = inspect.getsource(sessions.delete_session)
        self.assertIn("Session.tahfiz_id == context.tahfiz_id", source)


if __name__ == "__main__":
    unittest.main()
