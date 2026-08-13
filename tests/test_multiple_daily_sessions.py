import tempfile
import sys
import unittest
from datetime import date
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import (
    Attendance,
    ProgressCategory,
    Sheikh,
    Student,
    StudentCategory,
    StudentCategoryMembership,
    StudentQuranPlan,
    Tahfiz,
    TahfizStatus,
    User,
    UserRole,
    WardIncrementUnit,
)
from app.routers.auth import TenantContext
from app.routers.management import list_student_categories
from app.routers.progress import save_session_progress
from app.routers.sessions import confirm_session, create_session, get_session_attendance, update_session_membership
from app.schemas import ConfirmSessionRequest, CreateSessionRequest, QuranProgressBatchRequest, UpdateSessionMembershipRequest


@unittest.skipIf(sys.version_info >= (3, 14), "aiosqlite test transactions hang on Python 3.14; production uses Python 3.12")
class MultipleDailySessionsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="zamzam-multi-session-")
        database = Path(self.temporary.name) / "test.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{database}")
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with self.sessions() as db:
            self.tahfiz = Tahfiz(
                id=1,
                name="اختبار",
                status=TahfizStatus.active,
                multiple_sessions_per_day_enabled=True,
                progress_tracking_enabled=True,
            )
            self.user = User(id=10, username="admin", password_hash="unused", role=UserRole.admin, tahfiz_id=1, is_active=True)
            db.add_all([self.tahfiz, self.user, Sheikh(id=20, name="الشيخ", tahfiz_id=1)])
            await db.flush()
            db.add_all([
                Student(id=101, name="الأول", tahfiz_id=1, sheikh_id=20),
                Student(id=102, name="الثاني", tahfiz_id=1, sheikh_id=20),
                Student(id=103, name="الثالث", tahfiz_id=1, sheikh_id=20),
                StudentCategory(id=30, tahfiz_id=1, name="صباحي"),
            ])
            await db.flush()
            db.add_all([
                StudentCategoryMembership(tahfiz_id=1, category_id=30, student_id=101),
                StudentCategoryMembership(tahfiz_id=1, category_id=30, student_id=102),
                StudentQuranPlan(
                    tahfiz_id=1,
                    student_id=101,
                    category=ProgressCategory.new_memorization,
                    increment_unit=WardIncrementUnit.ayahs,
                    increment_amount=1,
                    next_surah=2,
                    next_ayah=1,
                ),
            ])
            await db.commit()
        self.context = TenantContext(user=self.user, tahfiz=self.tahfiz)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.temporary.cleanup()

    async def create(self, db, student_ids, name=None, session_date=date(2026, 8, 11)):
        return await create_session(
            CreateSessionRequest(session_date=session_date, name=name, student_ids=student_ids),
            db=db,
            context=self.context,
        )

    async def test_categories_report_membership_counts(self):
        async with self.sessions() as db:
            categories = await list_student_categories(db=db, context=self.context)
        self.assertEqual(categories, [{"id": 30, "name": "صباحي", "student_count": 2}])

    async def test_multiple_sessions_snapshot_membership_and_allow_overlap(self):
        async with self.sessions() as db:
            first = await self.create(db, [101, 102], "الصباحية")
            second = await self.create(db, [101, 103])
            attendance = await get_session_attendance(first["id"], db=db, context=self.context)
            confirmed = await confirm_session(
                first["id"],
                ConfirmSessionRequest(expected_version=attendance["version"]),
                db=db,
                context=self.context,
            )
            member_ids = set((await db.execute(select(Attendance.student_id).where(
                Attendance.session_id == first["id"],
            ))).scalars().all())

        self.assertEqual((first["daily_sequence"], second["daily_sequence"]), (1, 2))
        self.assertEqual({student["id"] for group in attendance["sheikh_groups"] for student in group["students"]}, {101, 102})
        self.assertEqual(confirmed["status"], "confirmed")
        self.assertEqual(member_ids, {101, 102})

    async def test_membership_can_change_before_confirmation(self):
        async with self.sessions() as db:
            session = await self.create(db, [101, 102])
            updated = await update_session_membership(
                session["id"],
                UpdateSessionMembershipRequest(student_ids=[102, 103], expected_version=0),
                db=db,
                context=self.context,
            )
        self.assertEqual(updated["student_ids"], [102, 103])
        self.assertEqual(updated["version"], 1)

    async def test_quran_plan_advances_only_once_for_same_day(self):
        base = {
            "student_id": 101,
            "category": "new_memorization",
            "range_type": "surah_ayah",
            "from_surah": 2,
            "from_ayah": 1,
            "to_surah": 2,
            "quality_score": 4,
            "mistakes": 0,
        }
        async with self.sessions() as db:
            first = await self.create(db, [101])
            second = await self.create(db, [101])
            await save_session_progress(
                first["id"],
                QuranProgressBatchRequest(updates=[{**base, "to_ayah": 5}]),
                db=db,
                context=self.context,
            )
            await save_session_progress(
                second["id"],
                QuranProgressBatchRequest(updates=[{**base, "from_ayah": 6, "to_ayah": 10}]),
                db=db,
                context=self.context,
            )
            plan = await db.scalar(select(StudentQuranPlan).where(StudentQuranPlan.student_id == 101))
        self.assertEqual((plan.next_surah, plan.next_ayah), (2, 6))
        self.assertEqual(plan.last_advanced_on, date(2026, 8, 11))

    async def test_disabled_setting_rejects_second_session_on_date(self):
        self.tahfiz.multiple_sessions_per_day_enabled = False
        async with self.sessions() as db:
            await create_session(CreateSessionRequest(session_date=date(2026, 8, 12)), db=db, context=self.context)
            with self.assertRaises(HTTPException) as raised:
                await create_session(CreateSessionRequest(session_date=date(2026, 8, 12)), db=db, context=self.context)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail["code"], "session_date_exists")


if __name__ == "__main__":
    unittest.main()
