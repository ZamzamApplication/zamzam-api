import tempfile
import unittest
from datetime import date
from pathlib import Path

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app
from app.models import (
    Attendance,
    ProgressCategory,
    QuranProgressEntry,
    QuranRangeType,
    SavedFilter,
    Session,
    Student,
    Tahfiz,
    TahfizStatus,
    User,
    UserRole,
    UserTahfizMembership,
)
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

    async def test_existing_user_can_create_linked_tahfiz_without_new_account(self):
        response = await self.client.post(
            "/auth/tahfiz",
            headers={**self.headers, "X-Tahfiz-ID": "1"},
            json={"name": "تحفيظ جديد", "contact_phone": "01000000000"},
        )

        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["status"], "pending")
        async with self.sessions() as db:
            self.assertEqual(await db.scalar(select(func.count(User.id))), 1)
            tahfiz = await db.get(Tahfiz, response.json()["tahfiz_id"])
            membership = await db.get(UserTahfizMembership, response.json()["membership_id"])
            user = await db.get(User, 10)
            self.assertEqual(tahfiz.owner_user_id, 10)
            self.assertEqual(membership.user_id, 10)
            self.assertEqual(membership.role, UserRole.admin)
            self.assertEqual(user.default_tahfiz_id, 1)

    async def test_excel_quran_columns_and_per_header_sizes_can_be_saved(self):
        headers = {**self.headers, "X-Tahfiz-ID": "1"}
        current = await self.client.get("/tahfiz/settings", headers=headers)
        templates = current.json()["excel_export_templates"]
        memorization = next(column for column in templates["attendance"]["columns"] if column["id"] == "memorization")
        memorization["header_font_size"] = 19

        response = await self.client.put(
            "/tahfiz/settings",
            headers=headers,
            json={"excel_export_templates": templates},
        )

        self.assertEqual(response.status_code, 200, response.text)
        saved = next(column for column in response.json()["excel_export_templates"]["attendance"]["columns"] if column["id"] == "memorization")
        self.assertEqual(saved["header_font_size"], 19)
        self.assertEqual([item["id"] for item in saved["subcolumns"]], ["from", "to"])

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

    async def test_student_quran_plan_suggests_and_advances_only_once(self):
        headers = {**self.headers, "X-Tahfiz-ID": "1"}
        configured = await self.client.put(
            "/students/101/quran-plans",
            headers=headers,
            json={"plans": [{
                "category": "new_memorization",
                "increment_unit": "ayahs",
                "increment_amount": 3,
                "next_surah": 2,
                "next_ayah": 285,
            }]},
        )
        preview = await self.client.get("/sessions/201/progress", headers=headers)

        self.assertEqual(configured.status_code, 200, configured.text)
        self.assertEqual(preview.status_code, 200, preview.text)
        suggestion = preview.json()["suggested_entries"][0]
        self.assertEqual(
            (suggestion["from_surah"], suggestion["from_ayah"], suggestion["to_surah"], suggestion["to_ayah"]),
            (2, 285, 3, 1),
        )

        payload = {"updates": [{**suggestion, "quality_score": 4}]}
        first_save = await self.client.post("/sessions/201/progress/batch", headers=headers, json=payload)
        after_first = await self.client.get("/students/101/quran-plans", headers=headers)
        second_save = await self.client.post(
            "/sessions/201/progress/batch",
            headers=headers,
            json={"updates": [{**suggestion, "quality_score": 5}]},
        )
        after_second = await self.client.get("/students/101/quran-plans", headers=headers)

        self.assertEqual(first_save.status_code, 200, first_save.text)
        self.assertEqual(second_save.status_code, 200, second_save.text)
        self.assertEqual(
            (after_first.json()["plans"][0]["next_surah"], after_first.json()["plans"][0]["next_ayah"]),
            (3, 2),
        )
        self.assertEqual(after_second.json()["plans"], after_first.json()["plans"])

    async def test_quran_plans_are_tenant_scoped(self):
        first_headers = {**self.headers, "X-Tahfiz-ID": "1"}
        second_headers = {**self.headers, "X-Tahfiz-ID": "2"}
        foreign_write = await self.client.put(
            "/students/102/quran-plans",
            headers=first_headers,
            json={"plans": [{
                "category": "old_revision",
                "increment_unit": "pages",
                "increment_amount": 2,
                "next_page": 10,
            }]},
        )
        disabled_tenant = await self.client.get("/students/102/quran-plans", headers=second_headers)
        self.assertEqual(foreign_write.status_code, 404)
        self.assertEqual(disabled_tenant.status_code, 409)

    async def test_attendance_grid_quran_ranges_use_first_and_last_entries_in_period(self):
        async with self.sessions() as db:
            first_session = await db.get(Session, 201)
            first_session.is_confirmed = True
            db.add(Session(id=203, date=date(2026, 7, 25), tahfiz_id=1, is_confirmed=True))
            db.add_all([
                Attendance(session_id=201, student_id=101, tahfiz_id=1, status="حاضر"),
                Attendance(session_id=203, student_id=101, tahfiz_id=1, status="حاضر"),
                QuranProgressEntry(
                    tahfiz_id=1, session_id=201, student_id=101, recorded_by_id=10,
                    category=ProgressCategory.new_memorization, range_type=QuranRangeType.surah_ayah,
                    from_surah=2, from_ayah=1, to_surah=2, to_ayah=5, quality_score=4,
                ),
                QuranProgressEntry(
                    tahfiz_id=1, session_id=203, student_id=101, recorded_by_id=10,
                    category=ProgressCategory.new_memorization, range_type=QuranRangeType.surah_ayah,
                    from_surah=2, from_ayah=6, to_surah=2, to_ayah=10, quality_score=5,
                ),
            ])
            await db.commit()

        response = await self.client.get(
            "/reports/attendance-grid?date_from=2026-07-23&date_to=2026-07-25",
            headers={**self.headers, "X-Tahfiz-ID": "1"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        memorization = response.json()["students"][0]["quran_progress_ranges"]["new_memorization"]
        self.assertEqual((memorization["first"]["from_surah"], memorization["first"]["from_ayah"]), (2, 1))
        self.assertEqual((memorization["last"]["to_surah"], memorization["last"]["to_ayah"]), (2, 10))

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
