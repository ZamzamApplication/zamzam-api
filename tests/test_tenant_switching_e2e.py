import tempfile
import unittest
from datetime import date
from pathlib import Path

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app
from app.models import SavedFilter, Session, Student, Tahfiz, TahfizStatus, User, UserRole, UserTahfizMembership
from app.routers.auth import create_access_token


class TenantSwitchingE2ETests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="zamzam-tenant-e2e-")
        database = Path(self.temporary.name) / "test.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{database}")
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with self.sessions() as db:
            first = Tahfiz(id=1, name="الأولى", status=TahfizStatus.active, progress_tracking_enabled=True)
            second = Tahfiz(id=2, name="الثانية", status=TahfizStatus.active)
            user = User(
                id=10,
                username="multi-admin",
                password_hash="unused",
                role=UserRole.admin,
                tahfiz_id=1,
                default_tahfiz_id=1,
                is_active=True,
            )
            db.add_all([first, second, user])
            await db.flush()
            db.add_all([
                UserTahfizMembership(user_id=10, tahfiz_id=1, role=UserRole.admin, is_active=True),
                UserTahfizMembership(user_id=10, tahfiz_id=2, role=UserRole.admin, is_active=True),
                Student(id=101, name="طالب الأولى", tahfiz_id=1),
                Student(id=102, name="طالب الثانية", tahfiz_id=2),
                Session(id=201, date=date(2026, 7, 23), tahfiz_id=1),
                Session(id=202, date=date(2026, 7, 24), tahfiz_id=2),
                SavedFilter(user_id=10, tahfiz_id=1, name="فلتر الأولى", data="{}"),
                SavedFilter(user_id=10, tahfiz_id=2, name="فلتر الثانية", data="{}"),
            ])
            await db.commit()

        async def override_db():
            async with self.sessions() as db:
                yield db

        app.dependency_overrides[get_db] = override_db
        token = create_access_token({"sub": "10", "uid": 10, "username": "multi-admin", "role": "admin"})
        self.headers = {"Authorization": f"Bearer {token}"}
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()
        app.dependency_overrides.clear()
        await self.engine.dispose()
        self.temporary.cleanup()

    async def test_switch_changes_workspace_and_never_combines_student_counts(self):
        first_headers = {**self.headers, "X-Tahfiz-ID": "1"}
        second_headers = {**self.headers, "X-Tahfiz-ID": "2"}
        first_report = await self.client.get("/reports/dashboard-summary", headers=first_headers)
        second_report = await self.client.get("/reports/dashboard-summary", headers=second_headers)
        first_students = await self.client.get("/students", headers=first_headers)
        second_students = await self.client.get("/students", headers=second_headers)
        first_sessions = await self.client.get("/sessions/all", headers=first_headers)
        second_sessions = await self.client.get("/sessions/all", headers=second_headers)
        first_settings = await self.client.get("/tahfiz/settings", headers=first_headers)
        second_settings = await self.client.get("/tahfiz/settings", headers=second_headers)
        first_filters = await self.client.get("/saved-filters/", headers=first_headers)
        second_filters = await self.client.get("/saved-filters/", headers=second_headers)

        for response in (
            first_report, second_report, first_students, second_students,
            first_sessions, second_sessions, first_settings, second_settings,
            first_filters, second_filters,
        ):
            self.assertEqual(response.status_code, 200)
        self.assertEqual(first_report.json()["tahfiz_name"], "الأولى")
        self.assertEqual(second_report.json()["tahfiz_name"], "الثانية")
        self.assertEqual(first_report.json()["students"], 1)
        self.assertEqual(second_report.json()["students"], 1)
        self.assertEqual([row["name"] for row in first_students.json()], ["طالب الأولى"])
        self.assertEqual([row["name"] for row in second_students.json()], ["طالب الثانية"])
        self.assertEqual([row["id"] for row in first_sessions.json()], [201])
        self.assertEqual([row["id"] for row in second_sessions.json()], [202])
        self.assertEqual(first_settings.json()["name"], "الأولى")
        self.assertEqual(second_settings.json()["name"], "الثانية")
        self.assertEqual([row["name"] for row in first_filters.json()], ["فلتر الأولى"])
        self.assertEqual([row["name"] for row in second_filters.json()], ["فلتر الثانية"])

    async def test_default_workspace_persists_without_a_device_header(self):
        changed = await self.client.post(
            "/auth/default-tahfiz",
            headers=self.headers,
            json={"tahfiz_id": 2},
        )
        me = await self.client.get("/auth/me", headers=self.headers)

        self.assertEqual(changed.status_code, 200)
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["tahfiz_id"], 2)
        self.assertEqual(me.json()["default_tahfiz_id"], 2)

    async def test_unknown_workspace_is_rejected(self):
        response = await self.client.get(
            "/reports/dashboard-summary",
            headers={**self.headers, "X-Tahfiz-ID": "999"},
        )
        self.assertEqual(response.status_code, 403)

    async def test_progress_edit_creates_readable_before_after_revision(self):
        endpoint = "/sessions/201/progress/batch"
        headers = {**self.headers, "X-Tahfiz-ID": "1"}
        initial = {
            "updates": [{
                "student_id": 101,
                "category": "new_memorization",
                "range_type": "surah_ayah",
                "from_surah": 2,
                "from_ayah": 1,
                "to_surah": 2,
                "to_ayah": 10,
                "quality_score": 4,
                "mistakes": 1,
            }]
        }
        changed = {
            "updates": [{
                **initial["updates"][0],
                "to_surah": 3,
                "to_ayah": 5,
            }]
        }
        first = await self.client.post(endpoint, headers=headers, json=initial)
        second = await self.client.post(endpoint, headers=headers, json=changed)
        history = await self.client.get("/students/101/progress", headers=headers)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(history.status_code, 200)
        self.assertEqual(len(history.json()["revisions"]), 1)
        self.assertEqual(history.json()["revisions"][0]["before"]["to_surah"], 2)
        self.assertEqual(history.json()["revisions"][0]["after"]["to_surah"], 3)

    async def test_invitation_can_be_listed_resent_and_revoked_within_workspace(self):
        headers = {**self.headers, "X-Tahfiz-ID": "1"}
        created = await self.client.post(
            "/invitations/",
            headers=headers,
            json={"role": "admin", "expires_hours": 24},
        )
        resent = await self.client.post(
            f"/invitations/{created.json()['id']}/resend",
            headers=headers,
        )
        listed = await self.client.get("/invitations/", headers=headers)

        self.assertEqual(created.status_code, 200)
        self.assertEqual(resent.status_code, 200)
        self.assertIn("path", resent.json())
        statuses = {item["id"]: item["status"] for item in listed.json()}
        self.assertEqual(statuses[created.json()["id"]], "revoked")
        self.assertEqual(statuses[resent.json()["id"]], "active")

    async def test_mobile_bootstrap_is_bounded_to_selected_tenant(self):
        first = await self.client.get(
            "/sync/v1/bootstrap",
            headers={**self.headers, "X-Tahfiz-ID": "1"},
        )
        second = await self.client.get(
            "/sync/v1/bootstrap",
            headers={**self.headers, "X-Tahfiz-ID": "2"},
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["tahfiz"]["id"], 1)
        self.assertEqual(second.json()["tahfiz"]["id"], 2)
        self.assertEqual([row["id"] for row in first.json()["students"]], [101])
        self.assertEqual([row["id"] for row in second.json()["students"]], [102])
        self.assertEqual([row["id"] for row in first.json()["sessions"]], [201])
        self.assertEqual([row["id"] for row in second.json()["sessions"]], [202])

    async def test_mobile_attendance_mutation_is_idempotent_and_detects_conflict(self):
        headers = {**self.headers, "X-Tahfiz-ID": "1"}
        mutation = {
            "mutation_id": "mobile-mutation-0001",
            "device_id": "device-install-0001",
            "entity_type": "attendance",
            "entity_key": "201:101",
            "base_revision": 0,
            "values": {
                "session_id": 201,
                "student_id": 101,
                "status": "حاضر",
                "notes": None,
                "sheikh_id": None,
            },
        }
        first = await self.client.post("/sync/v1/mutations", headers=headers, json={"mutations": [mutation]})
        replay = await self.client.post("/sync/v1/mutations", headers=headers, json={"mutations": [mutation]})
        conflict = await self.client.post("/sync/v1/mutations", headers=headers, json={"mutations": [{
            **mutation,
            "mutation_id": "mobile-mutation-0002",
            "values": {**mutation["values"], "status": "غياب"},
        }]})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["results"][0]["status"], "applied")
        self.assertEqual(first.json()["results"][0]["entity"]["revision"], 1)
        self.assertTrue(replay.json()["results"][0]["replayed"])
        self.assertEqual(conflict.json()["results"][0]["status"], "conflict")
        self.assertEqual(conflict.json()["results"][0]["server"]["status"], "حاضر")

    async def test_mobile_mutation_cannot_reference_another_tenants_student(self):
        response = await self.client.post(
            "/sync/v1/mutations",
            headers={**self.headers, "X-Tahfiz-ID": "1"},
            json={"mutations": [{
                "mutation_id": "mobile-mutation-tenant-check",
                "device_id": "device-install-0001",
                "entity_type": "attendance",
                "entity_key": "201:102",
                "base_revision": 0,
                "values": {
                    "session_id": 201,
                    "student_id": 102,
                    "status": "حاضر",
                },
            }]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["status"], "rejected")
        self.assertEqual(response.json()["results"][0]["code"], "entity_not_found")
