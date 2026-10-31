import copy
import importlib
import tempfile
import unittest
from pathlib import Path

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app
from app.models import PersonalPlan, User, UserRole
from app.routers.auth import create_access_token


def plan_body():
    return {
        "name": "خطة رمضان",
        "configuration": {
            "planOwnerType": "student", "studentName": "أحمد",
            "startDate": "2026-10-01", "endDate": "2026-10-03", "weekdays": [0, 1, 2, 3, 4, 5, 6],
            "includeCompletionCheckboxes": True,
            "tracks": [{"id": "hifz", "name": "الحفظ", "kind": "quran", "enabled": True, "dailyAmount": 1,
                        "start": {"surah": 1, "ayah": 1}, "unit": "ayahs", "subject": "", "quantityUnit": "صفحة", "startNumber": 1}],
        },
        "study_dates": ["2026-10-01", "2026-10-02", "2026-10-03"],
        "completed_dates": [],
    }


class PersonalPlanTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.temporary.name) / 'test.db'}")
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with self.sessions() as db:
            db.add_all([User(id=1, username="owner", password_hash="unused", role=UserRole.admin, is_active=True),
                        User(id=2, username="other", password_hash="unused", role=UserRole.admin, is_active=True)])
            await db.commit()
        async def database():
            async with self.sessions() as db:
                yield db
        app.dependency_overrides[get_db] = database
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        self.owner = {"Authorization": f"Bearer {create_access_token({'sub': 'owner', 'uid': 1})}"}
        self.other = {"Authorization": f"Bearer {create_access_token({'sub': 'other', 'uid': 2})}"}

    async def asyncTearDown(self):
        await self.client.aclose()
        app.dependency_overrides.clear()
        await self.engine.dispose()
        self.temporary.cleanup()

    async def create(self):
        response = await self.client.post("/personal-plans", headers=self.owner, json=plan_body())
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    async def status(self, plan, **changes):
        response = await self.client.patch(f"/personal-plans/{plan['id']}", headers=self.owner,
                                          json={"expected_version": plan["version"], **changes})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def test_saving_requires_login_and_private_plans_are_owner_scoped(self):
        self.assertEqual((await self.client.post("/personal-plans", json=plan_body())).status_code, 401)
        self.assertEqual((await self.client.get("/personal-plans")).status_code, 401)
        plan = await self.create()
        self.assertEqual(plan["share_mode"], "private")
        self.assertIsNone(plan["share_token"])
        for method, kwargs in [("get", {}), ("put", {"json": {**plan_body(), "expected_version": 1}}),
                               ("patch", {"json": {"expected_version": 1, "archived": True}}),
                               ("delete", {"params": {"expected_version": 1}})]:
            response = await getattr(self.client, method)(f"/personal-plans/{plan['id']}", headers=self.other, **kwargs)
            self.assertEqual(response.status_code, 404)
        self.assertEqual((await self.client.get("/personal-plans", headers=self.other)).json(), [])
        owner_list = await self.client.get("/personal-plans", headers=self.owner)
        self.assertEqual(len(owner_list.json()), 1)
        self.assertEqual(owner_list.headers["cache-control"], "private, no-store")

    async def test_readonly_shares_work_without_account_and_cannot_mark_or_edit(self):
        plan = await self.status(await self.create(), share_mode="readonly")
        path = f"/shared-plans/{plan['share_token']}"
        response = await self.client.get(path)
        self.assertEqual(response.status_code, 200)
        shared = response.json()
        self.assertFalse(shared["can_edit"])
        self.assertFalse(shared["can_mark"])
        self.assertNotIn("share_token", shared)
        self.assertNotIn("owner_user_id", shared)
        self.assertEqual(response.headers["x-robots-tag"], "noindex, nofollow")
        self.assertEqual((await self.client.patch(path + "/progress", json={"expected_version": plan["version"], "date": "2026-10-01", "done": True})).status_code, 403)
        self.assertEqual((await self.client.put(f"/personal-plans/{plan['id']}", json=plan_body())).status_code, 401)
        self.assertEqual((await self.client.delete(f"/personal-plans/{plan['id']}?expected_version=1")).status_code, 401)

    async def test_read_mark_access_only_changes_progress_and_detects_stale_writes(self):
        plan = await self.status(await self.create(), share_mode="read_mark")
        path = f"/shared-plans/{plan['share_token']}/progress"
        progress = {"expected_version": plan["version"], "date": "2026-10-01", "done": True}
        self.assertEqual((await self.client.patch(path, json={**progress, "archived": True})).status_code, 422)
        self.assertEqual((await self.client.patch(path, json={**progress, "date": "2026-11-01"})).status_code, 422)
        response = await self.client.patch(path, json=progress)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["completed_dates"], ["2026-10-01"])
        self.assertEqual((await self.client.patch(path, json=progress)).status_code, 409)
        current = (await self.client.get(f"/personal-plans/{plan['id']}", headers=self.owner)).json()
        self.assertEqual(current["completed_dates"], ["2026-10-01"])
        for day in ["2026-10-02", "2026-10-03"]:
            response = await self.client.patch(path, json={**progress, "expected_version": current["version"], "date": day})
            current = response.json()
        self.assertTrue(current["completed"])

    async def test_switching_share_mode_and_making_private_revokes_old_links(self):
        plan = await self.status(await self.create(), share_mode="read_mark")
        old_token = plan["share_token"]
        plan = await self.status(plan, share_mode="readonly")
        self.assertNotEqual(plan["share_token"], old_token)
        self.assertEqual((await self.client.get(f"/shared-plans/{old_token}")).status_code, 404)
        readonly_token = plan["share_token"]
        plan = await self.status(plan, share_mode="private")
        self.assertIsNone(plan["share_token"])
        self.assertEqual((await self.client.get(f"/shared-plans/{readonly_token}")).status_code, 404)
        self.assertEqual((await self.client.patch(f"/shared-plans/{readonly_token}/progress", json={"expected_version": plan["version"], "date": "2026-10-01", "done": True})).status_code, 404)

    async def test_edit_rename_complete_archive_restore_and_delete_keep_history_until_deleted(self):
        plan = await self.create()
        body = plan_body()
        body.update(name="اسم جديد", expected_version=plan["version"])
        body["configuration"]["tracks"][0]["dailyAmount"] = 2
        response = await self.client.put(f"/personal-plans/{plan['id']}", headers=self.owner, json=body)
        self.assertEqual(response.status_code, 200)
        plan = response.json()
        self.assertEqual(plan["name"], "اسم جديد")
        self.assertEqual(plan["configuration"]["tracks"][0]["dailyAmount"], 2)
        self.assertEqual((await self.client.put(f"/personal-plans/{plan['id']}", headers=self.owner, json=body)).status_code, 409)
        plan = await self.status(plan, completed=True, archived=True, share_mode="read_mark")
        self.assertTrue(plan["completed"])
        self.assertTrue(plan["archived"])
        self.assertEqual(len((await self.client.get("/personal-plans", headers=self.owner)).json()), 1)
        response = await self.client.patch(f"/shared-plans/{plan['share_token']}/progress", json={"expected_version": plan["version"], "date": "2026-10-01", "done": True})
        self.assertEqual(response.status_code, 409)
        plan = await self.status(plan, archived=False)
        self.assertFalse(plan["archived"])
        self.assertTrue(plan["completed"])
        self.assertEqual((await self.client.delete(f"/personal-plans/{plan['id']}?expected_version=1", headers=self.owner)).status_code, 409)
        self.assertEqual((await self.client.delete(f"/personal-plans/{plan['id']}?expected_version={plan['version']}", headers=self.owner)).status_code, 204)
        self.assertEqual((await self.client.get(f"/shared-plans/{plan['share_token']}")).status_code, 404)
        self.assertEqual((await self.client.get("/personal-plans", headers=self.owner)).json(), [])

    async def test_invalid_dates_names_and_periods_are_rejected(self):
        for modify in [lambda body: body.update(name="   "), lambda body: body.update(completed_dates=["2026-11-01"]),
                       lambda body: body["configuration"].update(endDate="2029-01-01")]:
            body = copy.deepcopy(plan_body())
            modify(body)
            self.assertEqual((await self.client.post("/personal-plans", headers=self.owner, json=body)).status_code, 422)

    async def test_shared_content_rejects_executable_media_links(self):
        body = plan_body()
        body["configuration"]["tracks"][0]["items"] = [{"episodes": [{"title": "Unsafe", "url": "javascript:alert(1)"}]}]
        self.assertEqual((await self.client.post("/personal-plans", headers=self.owner, json=body)).status_code, 422)

    def item_body(self):
        body = plan_body()
        body["configuration"]["completionMode"] = "item"
        track = {**body["configuration"]["tracks"][0], "id": "revision", "name": "المراجعة"}
        body["configuration"]["tracks"].append(track)
        body["assignment_ids"] = {day: ["hifz", "revision"] for day in body["study_dates"]}
        return body

    async def test_items_are_persistent_independent_and_complete_the_day_together(self):
        response = await self.client.post("/personal-plans", headers=self.owner, json=self.item_body())
        self.assertEqual(response.status_code, 201, response.text)
        plan = response.json()
        path = f"/personal-plans/{plan['id']}/progress"
        async def mark(track_id, done):
            nonlocal plan
            response = await self.client.patch(path, headers=self.owner, json={"expected_version": plan["version"], "date": "2026-10-01", "track_id": track_id, "done": done})
            self.assertEqual(response.status_code, 200, response.text)
            plan = response.json()
        await mark("hifz", True)
        self.assertEqual(plan["completed_dates"], [])
        self.assertEqual(plan["completed_items"], {"2026-10-01": ["hifz"]})
        loaded = (await self.client.get(f"/personal-plans/{plan['id']}", headers=self.owner)).json()
        self.assertEqual(loaded["completed_items"], plan["completed_items"])
        await mark("revision", True)
        self.assertEqual(plan["completed_dates"], ["2026-10-01"])
        await mark("hifz", False)
        self.assertEqual(plan["completed_dates"], [])
        self.assertEqual(plan["completed_items"]["2026-10-01"], ["revision"])

    async def test_day_and_item_modes_preserve_partial_and_existing_full_day_progress(self):
        body = self.item_body()
        body["completed_dates"] = ["2026-10-01"]
        body["completed_items"] = {"2026-10-02": ["hifz"]}
        response = await self.client.post("/personal-plans", headers=self.owner, json=body)
        self.assertEqual(response.status_code, 201, response.text)
        plan = response.json()
        self.assertEqual(plan["completed_items"]["2026-10-01"], ["hifz", "revision"])
        for mode in ["day", "item"]:
            body["configuration"]["completionMode"] = mode
            body["expected_version"] = plan["version"]
            body["completed_items"] = plan["completed_items"]
            response = await self.client.put(f"/personal-plans/{plan['id']}", headers=self.owner, json=body)
            self.assertEqual(response.status_code, 200, response.text)
            plan = response.json()
            self.assertEqual(plan["completed_items"]["2026-10-02"], ["hifz"])
            self.assertEqual(plan["completed_dates"], ["2026-10-01"])

    async def test_item_sharing_respects_readonly_and_only_accepts_assigned_items(self):
        body = self.item_body()
        body["assignment_ids"]["2026-10-01"] = ["hifz"]
        response = await self.client.post("/personal-plans", headers=self.owner, json=body)
        self.assertEqual(response.status_code, 201, response.text)
        plan = await self.status(response.json(), share_mode="readonly")
        progress = {"expected_version": plan["version"], "date": "2026-10-01", "track_id": "hifz", "done": True}
        self.assertEqual((await self.client.patch(f"/shared-plans/{plan['share_token']}/progress", json=progress)).status_code, 403)
        plan = await self.status(plan, share_mode="read_mark")
        progress["expected_version"] = plan["version"]
        path = f"/shared-plans/{plan['share_token']}/progress"
        self.assertEqual((await self.client.patch(path, json={**progress, "track_id": "revision"})).status_code, 422)
        response = await self.client.patch(path, json=progress)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["completed_dates"], ["2026-10-01"])
        self.assertEqual((await self.client.patch(path, json=progress)).status_code, 409)

    async def test_legacy_day_clients_and_invalid_item_maps(self):
        legacy = await self.create()
        self.assertEqual(legacy["configuration"]["completionMode"], "day")
        response = await self.client.patch(f"/personal-plans/{legacy['id']}/progress", headers=self.owner, json={"expected_version": legacy["version"], "date": "2026-10-01", "done": True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["completed_dates"], ["2026-10-01"])
        for change in [lambda body: body.update(assignment_ids={}),
                       lambda body: body.update(completed_items={"2026-10-01": ["unassigned"]}),
                       lambda body: body.update(assignment_ids={"2026-10-01": ["hifz", "hifz"]})]:
            body = self.item_body()
            change(body)
            self.assertEqual((await self.client.post("/personal-plans", headers=self.owner, json=body)).status_code, 422)


class PersonalPlanMigrationTests(unittest.TestCase):
    def test_item_migration_preserves_old_completion_and_adds_empty_defaults(self):
        migration = importlib.import_module("migrations.versions.20261002_30_plan_item_completion")
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE personal_plans (id VARCHAR(36) PRIMARY KEY, completed_dates TEXT NOT NULL)"))
            connection.execute(text("INSERT INTO personal_plans VALUES ('old', '[\"2026-10-01\"]')"))
            original_op = migration.op
            migration.op = Operations(MigrationContext.configure(connection))
            try:
                migration.upgrade()
                migration.upgrade()
                row = connection.execute(text("SELECT completed_dates, assignment_ids, completed_items FROM personal_plans")).one()
                self.assertEqual(tuple(row), ('["2026-10-01"]', '{}', '{}'))
                migration.downgrade()
                self.assertEqual(connection.execute(text("SELECT completed_dates FROM personal_plans")).scalar_one(), '["2026-10-01"]')
            finally:
                migration.op = original_op
        engine.dispose()

    def test_migration_creates_table_and_is_idempotent(self):
        migration = importlib.import_module("migrations.versions.20261001_29_personal_plans")
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            original_op = migration.op
            migration.op = Operations(MigrationContext.configure(connection))
            try:
                migration.upgrade()
                migration.upgrade()
                columns = {column["name"] for column in inspect(connection).get_columns("personal_plans")}
                self.assertTrue({"owner_user_id", "share_token", "version", "configuration"}.issubset(columns))
                migration.downgrade()
                self.assertNotIn("personal_plans", inspect(connection).get_table_names())
            finally:
                migration.op = original_op
        engine.dispose()
