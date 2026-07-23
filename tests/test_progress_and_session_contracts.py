import unittest
from datetime import datetime

from fastapi import HTTPException
from pydantic import ValidationError

from app.models import Session, Tahfiz, TahfizStatus, User, UserRole
from app.routers.auth import TenantContext
from app.routers.progress import ensure_enabled, student_progress
from app.routers.sessions import session_status
from app.schemas import CreateStudentGoalRequest, QuranProgressItem


def make_context(*, enabled: bool) -> TenantContext:
    user = User(
        id=4,
        username="teacher",
        password_hash="unused",
        role=UserRole.sheikh,
        tahfiz_id=9,
    )
    tahfiz = Tahfiz(
        id=9,
        name="زمزم",
        status=TahfizStatus.active,
        progress_tracking_enabled=enabled,
    )
    return TenantContext(user=user, tahfiz=tahfiz)


class ProgressFeatureGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_student_progress_returns_empty_without_querying(self):
        response = await student_progress(
            student_id=100,
            db=object(),
            context=make_context(enabled=False),
        )

        self.assertFalse(response["enabled"])
        self.assertEqual(response["entries"], [])
        self.assertEqual(response["goals"], [])
        self.assertEqual(response["trend"], [])

    async def test_disabled_write_gate_returns_conflict(self):
        with self.assertRaises(HTTPException) as raised:
            ensure_enabled(make_context(enabled=False))

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail["code"], "progress_tracking_disabled")


class QuranRangeValidationTests(unittest.TestCase):
    def test_page_goal_accepts_valid_quran_pages(self):
        goal = CreateStudentGoalRequest(
            range_type="page",
            from_page=15,
            to_page=20,
        )

        self.assertEqual(goal.to_page, 20)

    def test_reversed_page_range_is_rejected(self):
        with self.assertRaises(ValidationError):
            CreateStudentGoalRequest(
                range_type="page",
                from_page=20,
                to_page=15,
            )

    def test_surah_and_ayah_fields_are_required_together(self):
        with self.assertRaises(ValidationError):
            QuranProgressItem(
                student_id=1,
                category="new_memorization",
                range_type="surah_ayah",
                from_surah=2,
                from_ayah=1,
                quality_score=4,
            )

    def test_progress_accepts_a_range_across_multiple_surahs(self):
        progress = QuranProgressItem(
            student_id=1,
            category="new_memorization",
            range_type="surah_ayah",
            from_surah=2,
            from_ayah=250,
            to_surah=3,
            to_ayah=20,
            quality_score=4,
        )

        self.assertEqual((progress.to_surah, progress.to_ayah), (3, 20))

    def test_reversed_surah_range_is_rejected(self):
        with self.assertRaises(ValidationError):
            QuranProgressItem(
                student_id=1,
                category="new_memorization",
                range_type="surah_ayah",
                from_surah=3,
                from_ayah=20,
                to_surah=2,
                to_ayah=250,
                quality_score=4,
            )

    def test_progress_quality_is_limited_to_five(self):
        with self.assertRaises(ValidationError):
            QuranProgressItem(
                student_id=1,
                category="test",
                range_type="page",
                from_page=1,
                to_page=1,
                quality_score=6,
            )


class SessionLifecycleTests(unittest.TestCase):
    def test_session_status_distinguishes_draft_reopened_and_confirmed(self):
        session = Session(id=1, tahfiz_id=9, is_confirmed=False)
        self.assertEqual(session_status(session), "draft")

        session.reopened_at = datetime(2026, 7, 18)
        self.assertEqual(session_status(session), "reopened")

        session.is_confirmed = True
        self.assertEqual(session_status(session), "confirmed")


if __name__ == "__main__":
    unittest.main()
