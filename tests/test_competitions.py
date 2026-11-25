import importlib
import inspect as python_inspect
import unittest
from datetime import date, timedelta
from unittest import mock

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import (AuditLog, Competition, CompetitionEntry, CompetitionParticipant, Sheikh, Student,
                        StudentCategory, StudentCategoryMembership, StudentStatus, Tahfiz, TahfizStatus, User, UserRole)
from app.routers import competitions as comp
from app.routers import management
from app.routers.auth import TenantContext, require_tenant_admin
from tests.test_finance_history_and_custom_progress import AsyncSessionAdapter

START = date(2026, 11, 1)
END = date(2026, 11, 30)
TODAY = date(2026, 11, 20)


class Adapter(AsyncSessionAdapter):
    async def delete(self, row):
        self.session.delete(row)

    async def rollback(self):
        self.session.rollback()


class CompetitionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")

        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine, expire_on_commit=False)
        self.session.add_all([Tahfiz(id=1, name="One", status=TahfizStatus.active),
                              Tahfiz(id=2, name="Two", status=TahfizStatus.active)])
        self.session.flush()
        self.session.add_all([Sheikh(id=1, name="Sheikh A", tahfiz_id=1), Sheikh(id=2, name="Sheikh B", tahfiz_id=1),
                              Sheikh(id=3, name="Other", tahfiz_id=2)])
        self.session.flush()
        self.session.add_all([
            User(id=1, username="admin", password_hash="x", role=UserRole.admin, tahfiz_id=1),
            User(id=2, username="other", password_hash="x", role=UserRole.admin, tahfiz_id=2),
            User(id=3, username="sheikh", password_hash="x", role=UserRole.sheikh, tahfiz_id=1, sheikh_id=1),
            Student(id=1, name="أحمد محمد علي", tahfiz_id=1, sheikh_id=1),
            Student(id=2, name="علي حسن", tahfiz_id=1, sheikh_id=1),
            Student(id=3, name="عمر", tahfiz_id=1, sheikh_id=2),
            Student(id=4, name="خالد سعيد", tahfiz_id=1, sheikh_id=2),
            Student(id=5, name="منقطع", tahfiz_id=1, sheikh_id=2, status=StudentStatus.discontinued),
            Student(id=6, name="Other tenant", tahfiz_id=2, sheikh_id=3),
            StudentCategory(id=1, name="Juniors", tahfiz_id=1),
        ])
        self.session.flush()
        self.session.add(StudentCategoryMembership(tahfiz_id=1, category_id=1, student_id=4))
        self.session.commit()
        tahfiz = self.session.get(Tahfiz, 1)
        self.admin = TenantContext(user=self.session.get(User, 1), tahfiz=tahfiz)
        self.other = TenantContext(user=self.session.get(User, 2), tahfiz=self.session.get(Tahfiz, 2))
        self.sheikh = TenantContext(user=self.session.get(User, 3), tahfiz=tahfiz, role=UserRole.sheikh, sheikh_id=1)
        self.db = Adapter(self.session)
        patcher = mock.patch.object(comp, "utcnow", wraps=comp.utcnow)
        self.clock = patcher.start()
        self.clock.return_value = comp.utcnow().replace(year=TODAY.year, month=TODAY.month, day=TODAY.day)
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    async def assert_http(self, code, call):
        with self.assertRaises(HTTPException) as error:
            await call
        self.assertEqual(error.exception.status_code, code)
        self.session.rollback()

    async def create(self, context=None, **values):
        body = comp.CompetitionInput(**{"title": "تحدي الفجر", "start_date": START, "end_date": END, **values})
        return (await comp.create_competition(body, self.db, context or self.admin))["id"]

    async def detail(self, competition_id, context=None):
        self.session.expire_all()
        return await comp.competition_detail(competition_id, self.db, context or self.admin)

    async def version(self, competition_id):
        return (await self.detail(competition_id))["competition"]["version"]

    async def set_status(self, competition_id, status):
        await comp.change_status(competition_id, comp.StatusInput(status=status, expected_version=await self.version(competition_id)),
                                 self.db, self.admin)

    async def active_with_roster(self, **values):
        competition_id = await self.create(**values)
        await comp.add_participants(competition_id, comp.ParticipantsInput(student_ids=[1, 2, 3, 4]), self.db, self.admin)
        await self.set_status(competition_id, "active")
        ids = {p["student_id"]: p["id"] for p in (await self.detail(competition_id))["participants"]}
        return competition_id, ids

    async def mark(self, competition_id, participant_ids, day, done=True, context=None):
        return await comp.record_entries(competition_id, comp.EntriesInput(date=day, participant_ids=participant_ids, done=done),
                                         self.db, context or self.admin)

    async def enable_public(self, competition_id, regenerate=False):
        return await comp.set_public_link(competition_id, comp.PublicLinkInput(
            enabled=True, regenerate=regenerate, expected_version=await self.version(competition_id)), self.db, self.admin)

    async def test_bulk_roster_by_student_sheikh_and_category_skips_inactive_and_duplicates(self):
        competition_id = await self.create()
        result = await comp.add_participants(competition_id, comp.ParticipantsInput(sheikh_ids=[1], category_ids=[1]), self.db, self.admin)
        self.assertEqual(result, {"added": 3, "already_participating": 0})
        result = await comp.add_participants(competition_id, comp.ParticipantsInput(sheikh_ids=[2]), self.db, self.admin)
        self.assertEqual(result, {"added": 1, "already_participating": 1})  # student 5 is discontinued
        self.assertEqual({p["student_id"] for p in (await self.detail(competition_id))["participants"]}, {1, 2, 3, 4})
        await self.assert_http(404, comp.add_participants(competition_id, comp.ParticipantsInput(student_ids=[5]), self.db, self.admin))
        await self.assert_http(404, comp.add_participants(competition_id, comp.ParticipantsInput(student_ids=[6]), self.db, self.admin))
        await self.assert_http(404, comp.add_participants(competition_id, comp.ParticipantsInput(sheikh_ids=[3]), self.db, self.admin))

    async def test_everything_is_tenant_scoped(self):
        competition_id = await self.create(self.other)
        await self.assert_http(404, comp.competition_detail(competition_id, self.db, self.admin))
        await self.assert_http(404, comp.add_participants(competition_id, comp.ParticipantsInput(student_ids=[1]), self.db, self.admin))
        await self.assert_http(404, self.mark(competition_id, [1], TODAY))
        self.assertEqual(await comp.list_competitions(self.db, self.admin), [])
        self.assertEqual({s["id"] for s in await comp.competition_students(self.db, self.admin)}, {1, 2, 3, 4})

    async def test_entries_are_idempotent_and_respect_status_and_dates(self):
        competition_id = await self.create()
        await comp.add_participants(competition_id, comp.ParticipantsInput(student_ids=[1, 2]), self.db, self.admin)
        pids = [p["id"] for p in (await self.detail(competition_id))["participants"]]
        await self.assert_http(409, self.mark(competition_id, pids, TODAY))  # still a draft
        await self.set_status(competition_id, "active")
        self.assertEqual(await self.mark(competition_id, pids, TODAY), {"changed": 2, "unchanged": 0})
        self.assertEqual(await self.mark(competition_id, pids, TODAY), {"changed": 0, "unchanged": 2})
        self.assertEqual(await self.mark(competition_id, pids[:1], TODAY, done=False), {"changed": 1, "unchanged": 0})
        self.assertEqual(len((await self.detail(competition_id))["entries"]), 1)
        await self.assert_http(422, self.mark(competition_id, pids, START - timedelta(days=1)))
        await self.assert_http(422, self.mark(competition_id, pids, TODAY + timedelta(days=2)))
        self.assertEqual((await self.mark(competition_id, pids, TODAY + timedelta(days=1)))["changed"], 2)  # timezone slack
        await self.set_status(competition_id, "ended")
        await self.assert_http(409, self.mark(competition_id, pids, TODAY))
        await self.assert_http(409, comp.add_participants(competition_id, comp.ParticipantsInput(student_ids=[3]), self.db, self.admin))
        await self.assert_http(409, comp.change_status(competition_id, comp.StatusInput(status="draft", expected_version=await self.version(competition_id)), self.db, self.admin))
        await self.set_status(competition_id, "active")  # reopen
        await self.assert_http(409, comp.change_status(competition_id, comp.StatusInput(status="draft", expected_version=await self.version(competition_id)), self.db, self.admin))
        actions = [row.action for row in self.session.scalars(select(AuditLog).order_by(AuditLog.id))]
        self.assertIn("competition.entries_recorded", actions)
        self.assertIn("competition.entries_removed", actions)

    async def test_standings_share_ranks_and_trophies_and_track_streaks_and_completion(self):
        competition_id, ids = await self.active_with_roster(completion_threshold=3)
        for offset in range(3):
            await self.mark(competition_id, [ids[1], ids[2]], START + timedelta(days=offset))
        await self.mark(competition_id, [ids[3]], START)
        await self.mark(competition_id, [ids[3]], START + timedelta(days=5))
        standings = {row["student_id"]: row for row in (await self.detail(competition_id))["standings"]}
        self.assertEqual([standings[s]["rank"] for s in (1, 2, 3, 4)], [1, 1, 3, 4])
        self.assertEqual([standings[s]["trophy"] for s in (1, 2, 3, 4)], ["gold", "gold", "bronze", None])
        self.assertEqual(standings[1]["best_streak"], 3)
        self.assertEqual(standings[3]["best_streak"], 1)
        self.assertEqual([standings[s]["completed"] for s in (1, 3, 4)], [True, False, False])

    async def test_sheikh_records_only_own_students_and_cannot_manage(self):
        competition_id, ids = await self.active_with_roster()
        detail = await self.detail(competition_id, self.sheikh)
        self.assertEqual({p["student_id"] for p in detail["participants"] if p["can_record"]}, {1, 2})
        self.assertNotIn("public_url", detail["competition"])
        await self.mark(competition_id, [ids[1], ids[2]], TODAY, context=self.sheikh)
        await self.assert_http(404, self.mark(competition_id, [ids[3]], TODAY, context=self.sheikh))
        draft_id = await self.create()
        await self.assert_http(404, comp.competition_detail(draft_id, self.db, self.sheikh))
        self.assertNotIn(draft_id, [item["id"] for item in await comp.list_competitions(self.db, self.sheikh)])
        admin_only = {"create_competition", "update_competition", "change_status", "set_public_link",
                      "add_participants", "remove_participant", "competition_students"}
        for route in comp.router.routes:
            params = python_inspect.signature(route.endpoint).parameters
            if route.endpoint.__name__ in admin_only:
                self.assertIs(params["context"].default.dependency, require_tenant_admin)
            elif route.endpoint.__name__ == "public_leaderboard":
                self.assertNotIn("context", params)
            else:
                self.assertIs(params["context"].default.dependency, comp.require_competition_staff)
        with self.assertRaises(HTTPException):
            await comp.require_competition_staff(TenantContext(user=self.admin.user, tahfiz=self.admin.tahfiz, role=UserRole.auditor))

    async def test_public_leaderboard_privacy_limits_and_link_lifecycle(self):
        competition_id, ids = await self.active_with_roster(public_limit=1)
        await self.assert_http(404, comp.public_leaderboard("missing", self.db))
        token = (await self.enable_public(competition_id))["public_url"].rsplit("/", 1)[1]
        await self.mark(competition_id, [ids[1], ids[2]], TODAY)
        await self.mark(competition_id, [ids[1], ids[2]], TODAY - timedelta(days=1))
        await self.mark(competition_id, [ids[3]], TODAY - timedelta(days=2))
        board = await comp.public_leaderboard(token, self.db)
        # Limit 1 still shows everyone tied for first; zero-score participants are never listed.
        self.assertEqual([row["name"] for row in board["leaderboard"]], ["أحمد م.", "علي ح."])
        self.assertEqual(board["participant_count"], 4)
        self.assertEqual(board["hidden_count"], 2)
        self.assertEqual(set(board["leaderboard"][0]), {"rank", "trophy", "points", "days", "best_streak", "completed", "name"})
        self.assertNotIn("participant_id", str(board))
        new_token = (await self.enable_public(competition_id, regenerate=True))["public_url"].rsplit("/", 1)[1]
        await self.assert_http(404, comp.public_leaderboard(token, self.db))
        await comp.public_leaderboard(new_token, self.db)
        await comp.set_public_link(competition_id, comp.PublicLinkInput(enabled=False, expected_version=await self.version(competition_id)), self.db, self.admin)
        await self.assert_http(404, comp.public_leaderboard(new_token, self.db))

    async def test_draft_or_suspended_tenant_is_never_public(self):
        competition_id = await self.create()
        token = (await self.enable_public(competition_id))["public_url"].rsplit("/", 1)[1]
        await self.assert_http(404, comp.public_leaderboard(token, self.db))
        await self.set_status(competition_id, "active")
        await comp.public_leaderboard(token, self.db)
        self.session.get(Tahfiz, 1).status = TahfizStatus.suspended
        self.session.commit()
        await self.assert_http(404, comp.public_leaderboard(token, self.db))

    async def test_settings_reprice_points_and_protect_recorded_dates(self):
        competition_id, ids = await self.active_with_roster()
        await self.mark(competition_id, [ids[1]], START + timedelta(days=2))
        values = dict(title="Fajr", start_date=START, end_date=END, points_per_check=5)
        await comp.update_competition(competition_id, comp.CompetitionUpdateInput(**values, expected_version=await self.version(competition_id)), self.db, self.admin)
        self.assertEqual((await self.detail(competition_id))["standings"][0]["points"], 5)
        await self.assert_http(409, comp.update_competition(competition_id, comp.CompetitionUpdateInput(
            **{**values, "start_date": START + timedelta(days=5)}, expected_version=await self.version(competition_id)), self.db, self.admin))
        await self.assert_http(409, comp.update_competition(competition_id, comp.CompetitionUpdateInput(**values, expected_version=1), self.db, self.admin))

    async def test_removing_participant_or_deleting_student_keeps_data_consistent(self):
        competition_id, ids = await self.active_with_roster()
        await self.mark(competition_id, [ids[1], ids[2]], TODAY)
        await comp.remove_participant(competition_id, ids[2], self.db, self.admin)
        self.assertEqual(self.session.scalar(select(CompetitionEntry.participant_id)), ids[1])
        student = self.session.get(Student, 1)
        await management.delete_student_entity(self.db, student, 1, 1, delete_attendance=True)
        self.session.commit()
        participant = self.session.get(CompetitionParticipant, ids[1])
        self.assertIsNone(participant.student_id)
        self.assertEqual(participant.name, "أحمد محمد علي")
        self.assertEqual((await self.detail(competition_id))["standings"][0]["points"], 1)

    async def test_student_card_shows_todays_status(self):
        competition_id, ids = await self.active_with_roster()
        await self.mark(competition_id, [ids[1]], TODAY)
        [card] = await comp.student_competitions(1, None, self.db, self.sheikh)
        self.assertEqual((card["id"], card["done"], card["rank"], card["trophy"]), (competition_id, True, 1, "gold"))
        await self.assert_http(404, comp.student_competitions(3, None, self.db, self.sheikh))

    def test_validation(self):
        with self.assertRaises(ValidationError):
            comp.CompetitionInput(title="x", start_date=END, end_date=START)
        with self.assertRaises(ValidationError):
            comp.CompetitionInput(title="x", start_date=START, end_date=START + timedelta(days=400))
        with self.assertRaises(ValidationError):
            comp.ParticipantsInput()
        with self.assertRaises(ValidationError):
            comp.EntriesInput(date=TODAY, participant_ids=[1, 1], done=True)
        self.assertEqual(comp.display_name("عمر", "short"), "عمر")
        self.assertEqual(comp.display_name("أحمد محمد علي", "full"), "أحمد محمد علي")


class CompetitionMigrationTests(unittest.TestCase):
    def test_upgrade_is_idempotent_matches_orm_and_downgrades(self):
        engine = create_engine("sqlite:///:memory:")
        models = (Competition, CompetitionParticipant, CompetitionEntry)
        names = {model.__tablename__ for model in models}
        Base.metadata.create_all(engine, tables=[t for t in Base.metadata.sorted_tables if t.name not in names])
        with engine.begin() as connection:
            connection.execute(Tahfiz.__table__.insert().values(id=1, name="Existing"))
            module = importlib.import_module("migrations.versions.20261125_37_competitions")
            with Operations.context(MigrationContext.configure(connection)):
                module.upgrade(); module.upgrade()
                schema = inspect(connection)
                for model in models:
                    self.assertEqual({c["name"] for c in schema.get_columns(model.__tablename__)},
                                     set(model.__table__.columns.keys()))
                self.assertEqual(connection.scalar(select(Tahfiz.name)), "Existing")
                module.downgrade()
                self.assertFalse(names & set(inspect(connection).get_table_names()))
        engine.dispose()
