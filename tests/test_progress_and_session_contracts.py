import unittest
from datetime import date, datetime

from fastapi import HTTPException
from pydantic import ValidationError

from app.models import ProgressCategory, Session, StudentQuranPlan, Tahfiz, TahfizStatus, User, UserRole, WardIncrementUnit
from app.routers.auth import TenantContext
from app.routers.progress import ensure_enabled, plan_suggestion, session_progress, should_advance_plan, student_progress
from app.routers.sessions import session_status, session_summary, update_session_progress_tracking
from app.schemas import CreateStudentGoalRequest, QuranProgressItem, SessionQuranProgressRequest, StudentQuranPlansRequest


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


class ScalarSequenceDB:
    def __init__(self, *values):
        self.values = iter(values)
        self.added = []
        self.commits = 0

    async def scalar(self, _query):
        return next(self.values)

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.commits += 1


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

    async def test_session_exception_returns_disabled_without_progress_queries(self):
        session = Session(id=1, tahfiz_id=9, is_confirmed=False, quran_progress_enabled=False)

        response = await session_progress(
            session_id=1,
            db=ScalarSequenceDB(session),
            context=make_context(enabled=True),
        )

        self.assertFalse(response["enabled"])
        self.assertEqual(response["entries"], [])


class QuranRangeValidationTests(unittest.TestCase):
    def test_plan_advances_only_once_per_calendar_date(self):
        plan = StudentQuranPlan(last_advanced_on=date(2026, 8, 11))

        self.assertFalse(should_advance_plan(plan, date(2026, 8, 11), None))
        self.assertTrue(should_advance_plan(plan, date(2026, 8, 12), None))

    def test_student_plans_support_independent_units(self):
        request = StudentQuranPlansRequest(plans=[
            {"category": "new_memorization", "increment_unit": "lines", "increment_amount": 5, "next_surah": 2, "next_ayah": 1},
            {"category": "recent_revision", "increment_unit": "ayahs", "increment_amount": 10, "next_surah": 1, "next_ayah": 1},
            {"category": "old_revision", "increment_unit": "pages", "increment_amount": 2, "next_page": 50},
        ])
        self.assertEqual([plan.increment_unit for plan in request.plans], ["lines", "ayahs", "pages"])

    def test_page_plan_requires_starting_page(self):
        with self.assertRaises(ValidationError):
            StudentQuranPlansRequest(plans=[{
                "category": "new_memorization",
                "increment_unit": "pages",
                "increment_amount": 2,
            }])

    def test_plan_suggestion_uses_offline_line_mapping(self):
        plan = StudentQuranPlan(
            id=1,
            tahfiz_id=1,
            student_id=3,
            category=ProgressCategory.new_memorization,
            increment_unit=WardIncrementUnit.lines,
            increment_amount=15,
            next_surah=2,
            next_ayah=6,
        )
        suggestion = plan_suggestion(plan)
        self.assertEqual((suggestion["from_surah"], suggestion["from_ayah"]), (2, 6))
        self.assertEqual((suggestion["to_surah"], suggestion["to_ayah"]), (2, 16))

    def test_page_plan_caps_at_end_of_mushaf(self):
        plan = StudentQuranPlan(
            id=2,
            tahfiz_id=1,
            student_id=3,
            category=ProgressCategory.old_revision,
            increment_unit=WardIncrementUnit.pages,
            increment_amount=5,
            next_page=603,
        )
        suggestion = plan_suggestion(plan)
        self.assertEqual((suggestion["from_page"], suggestion["to_page"]), (603, 604))

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

    def test_session_summary_exposes_quran_progress_exception(self):
        tahfiz = Tahfiz(id=9, name="زمزم", status=TahfizStatus.active)
        session = Session(
            id=1,
            date=date(2026, 8, 11),
            tahfiz_id=9,
            is_confirmed=False,
            quran_progress_enabled=False,
            version=0,
        )
        session.tahfiz = tahfiz

        self.assertFalse(session_summary(session)["quran_progress_enabled"])

    def test_session_quran_toggle_accepts_optimistic_version(self):
        request = SessionQuranProgressRequest(enabled=False, expected_version=4)

        self.assertFalse(request.enabled)
        self.assertEqual(request.expected_version, 4)


class SessionQuranToggleTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabling_session_progress_is_persisted_and_versioned(self):
        session = Session(
            id=1,
            tahfiz_id=9,
            is_confirmed=False,
            quran_progress_enabled=True,
            version=4,
        )
        db = ScalarSequenceDB(session, None)

        response = await update_session_progress_tracking(
            session_id=1,
            body=SessionQuranProgressRequest(enabled=False, expected_version=4),
            db=db,
            context=make_context(enabled=True),
        )

        self.assertFalse(session.quran_progress_enabled)
        self.assertEqual(session.version, 5)
        self.assertEqual(response["version"], 5)
        self.assertEqual(db.commits, 1)


if __name__ == "__main__":
    unittest.main()
