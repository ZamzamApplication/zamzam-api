import importlib
import json
import unittest
from datetime import date
from pathlib import Path

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from pydantic import ValidationError
from sqlalchemy import create_engine, select, text, inspect
from sqlalchemy.orm import Session

from app.database import Base
from app.models import QuranProgressEntry, QuranProgressRevision, Session as StudySession, Student, StudentQuranPlan, Tahfiz, User, UserRole, WardIncrementUnit
from app.quran_data import next_reverse_ayah, reverse_to_end
from app.routers import progress, sync
from app.routers.auth import TenantContext
from app.schemas import QuranProgressBatchRequest, QuranProgressItem, StudentQuranPlansRequest
from tests.test_finance_history_and_custom_progress import AsyncSessionAdapter


class PlanSessionAdapter(AsyncSessionAdapter):
    async def refresh(self, row):
        self.session.refresh(row)

    async def delete(self, row):
        self.session.delete(row)


class ReverseAllocationTests(unittest.TestCase):
    def test_matches_hifz_builder_assignments_for_every_surah_based_unit(self):
        # Generated from generateQuranPlan with descending surahs, ascending ayahs,
        # and a stop at Fatiha 7. Includes partial surahs and completion.
        cases = json.loads((Path(__file__).parent / "fixtures/quran_reverse_builder.json").read_text())
        for case in cases:
            with self.subTest(case=case):
                end = reverse_to_end(case["surah"], case["ayah"], case["amount"], case["unit"])
                self.assertEqual(list(end), case["end"])

    def test_next_ayah_ascends_within_surah_then_descends_between_surahs(self):
        self.assertEqual(next_reverse_ayah(114, 4), (114, 5))
        self.assertEqual(next_reverse_ayah(114, 6), (113, 1))
        self.assertIsNone(next_reverse_ayah(1, 7))

    def test_ranges_require_explicit_direction_and_valid_ayahs(self):
        values = dict(student_id=1, category="new_memorization", range_type="surah_ayah",
                      from_surah=114, from_ayah=1, to_surah=113, to_ayah=5, quality_score=4)
        self.assertEqual(QuranProgressItem(**values, direction="backward").direction, "backward")
        with self.assertRaises(ValidationError):
            QuranProgressItem(**values)
        for patch in ({"to_surah": 114, "from_ayah": 5, "to_ayah": 4}, {"from_ayah": 7}, {"direction": "sideways"}):
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                QuranProgressItem(**{**values, "direction": "backward", **patch})
        with self.assertRaises(ValidationError):
            StudentQuranPlansRequest(plans=[dict(category="new_memorization", increment_unit="ayahs",
                                               increment_amount=1, direction="backward", next_surah=114, next_ayah=7)])


class QuranDirectionPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine, expire_on_commit=False)
        self.session.add(Tahfiz(id=1, name="اختبار", progress_tracking_enabled=True))
        self.session.add(User(id=1, username="admin", password_hash="unused", role=UserRole.admin, tahfiz_id=1))
        self.session.add(Student(id=1, name="طالب", tahfiz_id=1, quran_progress_enabled=True))
        self.session.add_all([StudySession(id=i, date=date(2026, 10, i), tahfiz_id=1,
                                          quran_progress_enabled=True, is_confirmed=False) for i in (1, 2)])
        self.session.commit()
        self.context = TenantContext(user=self.session.get(User, 1), tahfiz=self.session.get(Tahfiz, 1))
        self.db = PlanSessionAdapter(self.session)

    async def asyncTearDown(self):
        self.session.close()
        self.engine.dispose()

    async def set_plan(self, **patch):
        values = dict(category="new_memorization", increment_unit="ayahs", increment_amount=8,
                      direction="backward", next_surah=114, next_ayah=1)
        return await progress.update_student_quran_plans(1, StudentQuranPlansRequest(plans=[{**values, **patch}]), self.db, self.context)

    async def save(self, session_id, **patch):
        values = dict(student_id=1, category="new_memorization", range_type="surah_ayah", direction="backward",
                      from_surah=114, from_ayah=1, to_surah=113, to_ayah=2, quality_score=4)
        return await progress.save_session_progress(session_id, QuranProgressBatchRequest(updates=[QuranProgressItem(**{**values, **patch})]), self.db, self.context)

    async def test_plan_reload_suggestion_save_and_edit_preserve_direction(self):
        saved = await self.set_plan()
        self.assertEqual(saved["plans"][0]["direction"], "backward")
        loaded = await progress.student_quran_plans(1, self.db, self.context)
        self.assertEqual(loaded["plans"][0]["direction"], "backward")
        plan = self.session.scalar(select(StudentQuranPlan))
        suggestion = progress.plan_suggestion(plan)
        self.assertEqual((suggestion["from_surah"], suggestion["to_surah"], suggestion["to_ayah"]), (114, 113, 2))
        await self.save(1)
        self.assertEqual((plan.next_surah, plan.next_ayah), (113, 3))
        self.session.expire_all()
        entry = self.session.scalar(select(QuranProgressEntry))
        self.assertEqual(progress.serialize_entry(entry)["direction"], "backward")
        await self.save(1, to_ayah=3)
        self.assertEqual((plan.next_surah, plan.next_ayah), (113, 3))
        revision = self.session.scalar(select(QuranProgressRevision))
        self.assertEqual(json.loads(revision.before_json)["direction"], "backward")
        self.assertEqual(json.loads(revision.after_json)["direction"], "backward")
        history = await progress.student_progress(1, self.db, self.context)
        self.assertEqual(history["entries"][0]["direction"], "backward")
        # A subsequent plan change cannot reinterpret the saved historical range.
        await self.set_plan(direction="forward", next_surah=1)
        self.session.refresh(entry)
        self.assertEqual(entry.direction, "backward")

    async def test_backward_completes_at_fatiha_and_forward_still_completes_at_nas(self):
        await self.set_plan(next_surah=1, next_ayah=6)
        await self.save(1, from_surah=1, from_ayah=6, to_surah=1, to_ayah=7)
        plan = self.session.scalar(select(StudentQuranPlan))
        self.assertIsNotNone(plan.completed_at)
        await self.set_plan(direction="forward", next_surah=114, next_ayah=5)
        await self.save(2, direction="forward", from_ayah=5, to_surah=114, to_ayah=6)
        self.assertIsNotNone(plan.completed_at)

    async def test_backward_pages_advance_downward_and_complete_at_page_one(self):
        await self.set_plan(increment_unit="pages", increment_amount=3, next_page=4)
        plan = self.session.scalar(select(StudentQuranPlan))
        self.assertEqual(progress.plan_suggestion(plan)["to_page"], 2)
        await self.save(1, range_type="page", from_page=4, to_page=2)
        self.assertEqual(plan.next_page, 1)
        self.assertIsNone(plan.completed_at)
        await self.save(2, range_type="page", from_page=1, to_page=1)
        self.assertIsNotNone(plan.completed_at)

    async def test_other_direction_does_not_advance_plan(self):
        await self.set_plan()
        await self.save(1, direction="forward", to_surah=114, to_ayah=4)
        plan = self.session.scalar(select(StudentQuranPlan))
        self.assertEqual((plan.next_surah, plan.next_ayah), (114, 1))

    async def test_direction_changes_are_retained_in_revision_history(self):
        await self.save(1, to_surah=114, to_ayah=4)
        await self.save(1, direction="forward", to_surah=114, to_ayah=4)
        revision = self.session.scalar(select(QuranProgressRevision))
        self.assertEqual(json.loads(revision.before_json)["direction"], "backward")
        self.assertEqual(json.loads(revision.after_json)["direction"], "forward")

    async def test_sync_mutations_preserve_backward_direction(self):
        item = QuranProgressItem(student_id=1, category="new_memorization", range_type="surah_ayah",
                                 direction="backward", from_surah=114, from_ayah=1, to_surah=113,
                                 to_ayah=5, quality_score=4)
        mutation = sync.SyncMutation(mutation_id="quran-direction", device_id="test-device",
                                     entity_type="quran_progress", entity_key="1:1:new_memorization",
                                     base_revision=0, values={**item.model_dump(), "session_id": 1})
        result = await sync.apply_progress(mutation, self.db, self.context)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["entity"]["direction"], "backward")
        self.assertEqual(self.session.scalar(select(QuranProgressEntry)).direction, "backward")


class QuranDirectionMigrationTests(unittest.TestCase):
    def test_old_records_keep_forward_direction_and_migration_is_repeatable(self):
        migration = importlib.import_module("migrations.versions.20261004_31_quran_direction")
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            for table in ("student_quran_plans", "quran_progress_entries"):
                connection.execute(text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)"))
                connection.execute(text(f"INSERT INTO {table} VALUES (1)"))
            original_op = migration.op
            migration.op = Operations(MigrationContext.configure(connection))
            try:
                migration.upgrade()
                migration.upgrade()
                for table in ("student_quran_plans", "quran_progress_entries"):
                    self.assertEqual(connection.execute(text(f"SELECT direction FROM {table}")).scalar_one(), "forward")
                migration.downgrade()
                for table in ("student_quran_plans", "quran_progress_entries"):
                    self.assertNotIn("direction", {c["name"] for c in inspect(connection).get_columns(table)})
                    self.assertEqual(connection.execute(text(f"SELECT id FROM {table}")).scalar_one(), 1)
            finally:
                migration.op = original_op
        engine.dispose()
