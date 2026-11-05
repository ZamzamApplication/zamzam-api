import importlib
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
import asyncio
import tempfile
import unittest

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, inspect, select, text, func, event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.database import Base, get_db
from app.models import (Student, StudentCustomField, StudentCustomFieldValue, StudentRegistrationRequest,
                        Tahfiz, TahfizStatus, User, UserRole, Sheikh, StudentCategory, ParentPhone, StudentCategoryMembership)
from app.routers import student_registration as intake
from app.routers.auth import TenantContext, require_tenant_admin


class RegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f'sqlite+aiosqlite:///{self.tempdir.name}/registration.db')
        @event.listens_for(self.engine.sync_engine, 'connect')
        def enforce_foreign_keys(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.sessions() as db:
            one, two = Tahfiz(id=1, name='تحفيظ النور', status=TahfizStatus.active), Tahfiz(id=2, name='Other', status=TahfizStatus.active)
            admin = User(id=1, username='admin', password_hash='unused', role=UserRole.admin, tahfiz_id=1)
            other = User(id=2, username='other', password_hash='unused', role=UserRole.admin, tahfiz_id=2)
            db.add_all([one, two, admin, other])
            await db.flush()
            db.add_all([
                Sheikh(id=1, name='شيخ', tahfiz_id=1), Sheikh(id=2, name='Other', tahfiz_id=2),
                StudentCategory(id=1, name='مبتدئون', tahfiz_id=1), StudentCategory(id=2, name='Other', tahfiz_id=2),
                StudentCustomField(id=1, tahfiz_id=1, name='المستوى', field_type='select', options='["مبتدئ", "متقدم"]', is_required=True),
                StudentCustomField(id=2, tahfiz_id=1, name='ملاحظة داخلية', field_type='text', is_required=True),
                StudentCustomField(id=3, tahfiz_id=2, name='Other', field_type='text'),
            ])
            await db.commit()
            self.context = TenantContext(user=admin, tahfiz=one)
            self.other = TenantContext(user=other, tahfiz=two)
        self.app = FastAPI()
        self.app.include_router(intake.router)
        async def database():
            async with self.sessions() as db:
                yield db
        self.app.dependency_overrides[get_db] = database
        self.app.dependency_overrides[require_tenant_admin] = lambda: self.context
        self.client = AsyncClient(transport=ASGITransport(app=self.app), base_url='http://test')
        response = await self.client.post('/student-registration/forms', json={"title": "سجل الآن", "public_field_ids": [1]})
        self.assertEqual(response.status_code, 201, response.text)
        self.form = response.json()
        self.public = '/student-registration/public/' + self.form['token']

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.engine.dispose()
        self.tempdir.cleanup()

    async def submit(self):
        result = await self.client.post(self.public, json={"name": "أحمد", "phone": "012345", "answers": {"1": "مبتدئ"}})
        self.assertEqual(result.status_code, 201, result.text)
        rows = (await self.client.get('/student-registration/requests')).json()
        return rows[0]['id']

    def approval(self, **updates):
        return {'student': {"name": "أحمد", "phone": "012345", "sheikh_id": 1, "custom_field_values": {"2": "مراجعة المدير"}, **updates}}

    async def test_public_form_exposes_only_selected_fields_without_login(self):
        self.app.dependency_overrides.pop(require_tenant_admin)
        response = await self.client.get(self.public)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([f['id'] for f in response.json()['fields']], [1])
        self.assertNotIn('token', response.json())
        self.assertEqual((await self.client.get('/student-registration/requests')).status_code, 401)

    async def test_submission_is_pending_until_approved_and_notifies_manager(self):
        rid = await self.submit()
        async with self.sessions() as db:
            self.assertEqual(await db.scalar(select(func.count()).select_from(Student)), 0)
        self.assertEqual((await self.client.get('/student-registration/notifications')).json()['pending_count'], 1)
        result = await self.client.post(f'/student-registration/requests/{rid}/approve', json=self.approval())
        self.assertEqual(result.status_code, 200, result.text)
        async with self.sessions() as db:
            student = await db.get(Student, result.json()['student_id'])
            self.assertEqual(student.sheikh_id, 1)
            values = (await db.execute(select(StudentCustomFieldValue))).scalars().all()
            self.assertEqual({v.field_id: v.value for v in values}, {1: 'مبتدئ', 2: 'مراجعة المدير'})
        self.assertEqual((await self.client.get('/student-registration/notifications')).json()['pending_count'], 0)
        self.assertEqual((await self.client.get('/student-registration/requests?status=approved')).json()[0]['id'], rid)

    async def test_repeated_approval_does_not_duplicate_student(self):
        rid = await self.submit()
        path = f'/student-registration/requests/{rid}/approve'
        self.assertEqual((await self.client.post(path, json=self.approval())).status_code, 200)
        self.assertEqual((await self.client.post(path, json=self.approval())).status_code, 409)
        async with self.sessions() as db:
            self.assertEqual(await db.scalar(select(func.count()).select_from(Student)), 1)

    async def test_simultaneous_approvals_create_only_one_student(self):
        rid = await self.submit()
        path = f'/student-registration/requests/{rid}/approve'
        results = await asyncio.gather(
            self.client.post(path, json=self.approval()),
            self.client.post(path, json=self.approval()),
        )
        self.assertEqual(sorted(r.status_code for r in results), [200, 409])
        async with self.sessions() as db:
            self.assertEqual(await db.scalar(select(func.count()).select_from(Student)), 1)

    async def test_failed_required_internal_field_keeps_request_pending_and_creates_no_student(self):
        rid = await self.submit()
        response = await self.client.post(f'/student-registration/requests/{rid}/approve', json=self.approval(custom_field_values={}))
        self.assertEqual(response.status_code, 422)
        async with self.sessions() as db:
            self.assertEqual((await db.get(StudentRegistrationRequest, rid)).status, 'pending')
            self.assertEqual(await db.scalar(select(func.count()).select_from(Student)), 0)

    async def test_cross_tenant_form_field_request_and_sheikh_rejected(self):
        response = await self.client.post('/student-registration/forms', json={"title": "test", "public_field_ids": [3]})
        self.assertEqual(response.status_code, 422)
        rid = await self.submit()
        response = await self.client.post(f'/student-registration/requests/{rid}/approve', json=self.approval(sheikh_id=2))
        self.assertEqual(response.status_code, 404)
        self.app.dependency_overrides[require_tenant_admin] = lambda: self.other
        self.assertEqual((await self.client.get('/student-registration/requests')).json(), [])
        self.assertEqual((await self.client.put(f'/student-registration/forms/{self.form["id"]}', json={"title": "hack"})).status_code, 404)
        self.assertEqual((await self.client.post(f'/student-registration/requests/{rid}/approve', json=self.approval())).status_code, 409)
        self.assertEqual((await self.client.post(f'/student-registration/requests/{rid}/reject')).status_code, 409)

    async def test_rejection_prevents_later_approval(self):
        rid = await self.submit()
        self.assertEqual((await self.client.post(f'/student-registration/requests/{rid}/reject')).status_code, 200)
        self.assertEqual((await self.client.post(f'/student-registration/requests/{rid}/approve', json=self.approval())).status_code, 409)

    async def test_public_required_type_private_field_and_blank_name_validation(self):
        for payload in [
            {"name": "أحمد", "answers": {}},
            {"name": "أحمد", "answers": {"1": "invalid"}},
            {"name": "أحمد", "answers": {"1": "مبتدئ", "2": "private"}},
            {"name": "   ", "answers": {"1": "مبتدئ"}},
            {"name": "أحمد", "answers": {"1": "مبتدئ"}, "website": "spam"},
        ]:
            self.assertEqual((await self.client.post(self.public, json=payload)).status_code, 422)

    async def test_disabled_and_suspended_forms_are_unavailable(self):
        path = f'/student-registration/forms/{self.form["id"]}'
        await self.client.put(path, json={"title": "Closed", "is_active": False})
        self.assertEqual((await self.client.get(self.public)).status_code, 404)
        self.assertEqual((await self.client.post(self.public, json={"name": "test"})).status_code, 404)
        await self.client.put(path, json={"title": "Open", "public_field_ids": [1]})
        async with self.sessions() as db:
            (await db.get(Tahfiz, 1)).status = TahfizStatus.suspended
            await db.commit()
        self.assertEqual((await self.client.get(self.public)).status_code, 404)

    async def test_snapshot_survives_field_archive(self):
        rid = await self.submit()
        async with self.sessions() as db:
            field = await db.get(StudentCustomField, 1)
            field.name = 'renamed'; field.is_active = False
            await db.commit()
        rows = (await self.client.get('/student-registration/requests')).json()
        self.assertEqual(rows[0]['fields'][0]['name'], 'المستوى')
        result = await self.client.post(f'/student-registration/requests/{rid}/approve', json=self.approval())
        self.assertEqual(result.status_code, 200, result.text)

    async def configure_student_fields(self, fields, required=None):
        response = await self.client.put(f'/student-registration/forms/{self.form["id"]}', json={
            "title": "طلب التحاق", "public_field_ids": [1],
            "student_fields": fields, "required_student_fields": required or [],
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def test_existing_student_fields_are_configurable_and_round_trip_through_approval(self):
        fields = ["phone", "birthday", "student_id", "parent_phones", "sheikh_id", "category_ids",
                  "registration_date", "status", "quran_progress_enabled"]
        saved = await self.configure_student_fields(fields, ["phone", "quran_progress_enabled"])
        self.assertEqual(saved['student_fields'], fields)
        public = (await self.client.get(self.public)).json()
        self.assertEqual(public['required_student_fields'], ["phone", "quran_progress_enabled"])
        self.assertEqual(public['student_field_options'], {
            "sheikh_id": [{"id": 1, "name": "شيخ"}], "category_ids": [{"id": 1, "name": "مبتدئون"}]})
        details = dict(phone="0123456789", birthday="2012-06-01", student_id="ST-42",
                       registration_date="2026-11-01", status="ضيف", quran_progress_enabled=False,
                       sheikh_id=1, category_ids=[1],
                       parent_phones=[{"phone_number": "0109876543", "parent_type": "أم", "name": "فاطمة"}])
        result = await self.client.post(self.public, json={"name": "أحمد", "answers": {"1": "مبتدئ"}, **details})
        self.assertEqual(result.status_code, 201, result.text)
        row = (await self.client.get('/student-registration/requests')).json()[0]
        self.assertEqual(row['student_data'], details)
        # Changing the form after submission must not erase the submitted student details.
        await self.configure_student_fields([])
        result = await self.client.post(f'/student-registration/requests/{row["id"]}/approve', json={
            "student": {"name": "أحمد بعد المراجعة", "custom_field_values": {"2": "تمت المراجعة"}}})
        self.assertEqual(result.status_code, 200, result.text)
        async with self.sessions() as db:
            student = await db.get(Student, result.json()['student_id'])
            self.assertEqual((student.student_id, student.phone, student.sheikh_id), ("ST-42", details['phone'], 1))
            self.assertEqual(str(student.birthday), "2012-06-01")
            self.assertEqual(str(student.registration_date), "2026-11-01")
            self.assertEqual(student.status.value, "ضيف")
            self.assertFalse(student.quran_progress_enabled)
            parent = await db.scalar(select(ParentPhone).where(ParentPhone.student_id == student.id))
            self.assertEqual((parent.name, parent.phone_number), ("فاطمة", "0109876543"))
            self.assertEqual(await db.scalar(select(StudentCategoryMembership.category_id).where(
                StudentCategoryMembership.student_id == student.id)), 1)

    async def test_hidden_required_and_invalid_student_fields_are_rejected(self):
        await self.configure_student_fields(["phone", "quran_progress_enabled"], ["phone", "quran_progress_enabled"])
        base = {"name": "أحمد", "answers": {"1": "مبتدئ"}, "phone": "012345", "quran_progress_enabled": False}
        for update in [{"phone": " "}, {"phone": None}, {"quran_progress_enabled": None},
                       {"student_id": "hidden"}, {"sheikh_id": 2}, {"category_ids": [2]},
                       {"custom_field_values": {"2": "private"}}]:
            response = await self.client.post(self.public, json={**base, **update})
            self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual((await self.client.post(self.public, json={k: v for k, v in base.items() if k != 'quran_progress_enabled'})).status_code, 422)
        self.assertEqual((await self.client.post(self.public, json=base)).status_code, 201)
        self.assertNotIn('sheikh_id', (await self.client.get(self.public)).json()['student_field_options'])
        await self.configure_student_fields(["sheikh_id", "category_ids", "parent_phones"])
        for update in [{"sheikh_id": 2}, {"category_ids": [2]}, {"category_ids": [1, 1]},
                       {"parent_phones": [{"parent_type": "unknown", "phone_number": "123"}]}]:
            response = await self.client.post(self.public, json={"name": "أحمد", "answers": {"1": "مبتدئ"}, **update})
            self.assertEqual(response.status_code, 422, response.text)

    async def test_form_rejects_unknown_and_unselected_required_student_fields(self):
        for fields, required in [(["tahfiz_id"], []), (["phone"], ["birthday"]), (["phone", "phone"], [])]:
            response = await self.client.post('/student-registration/forms', json={
                "title": "طلب", "student_fields": fields, "required_student_fields": required})
            self.assertEqual(response.status_code, 422)

    async def test_admin_can_override_and_clear_submitted_student_details(self):
        await self.configure_student_fields(["phone", "student_id", "sheikh_id", "category_ids"])
        result = await self.client.post(self.public, json={"name": "أحمد", "phone": "123456", "student_id": "old",
            "sheikh_id": 1, "category_ids": [1], "answers": {"1": "مبتدئ"}})
        self.assertEqual(result.status_code, 201, result.text)
        row = (await self.client.get('/student-registration/requests')).json()[0]
        result = await self.client.post(f'/student-registration/requests/{row["id"]}/approve', json=self.approval(
            phone=None, student_id="corrected", sheikh_id=None, category_ids=[]))
        self.assertEqual(result.status_code, 200, result.text)
        async with self.sessions() as db:
            student = await db.get(Student, result.json()['student_id'])
            self.assertIsNone(student.phone)
            self.assertIsNone(student.sheikh_id)
            self.assertEqual(student.student_id, "corrected")
            self.assertEqual(await db.scalar(select(func.count()).select_from(StudentCategoryMembership)), 0)

    async def test_rate_limit(self):
        for _ in range(10):
            await self.client.post(self.public, json={"name": "test", "answers": {"1": "مبتدئ"}})
        self.assertEqual((await self.client.post(self.public, json={"name": "test"})).status_code, 429)

    def test_all_management_endpoints_require_tenant_admin(self):
        for route in intake.router.routes:
            if '/public/' not in route.path:
                self.assertIn(require_tenant_admin, [d.call for d in route.dependant.dependencies])


class RegistrationMigrationTests(unittest.TestCase):
    def test_fresh_database_upgrades_full_chain_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as path:
            database = Path(path) / 'fresh.db'
            environment = {**os.environ, 'DATABASE_URL': f'sqlite+aiosqlite:///{database}'}
            for _ in range(2):
                result = subprocess.run(
                    [sys.executable, '-m', 'alembic', 'upgrade', 'head'],
                    cwd=Path(__file__).resolve().parents[1], env=environment,
                    capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
            with sqlite3.connect(database) as conn:
                self.assertEqual(conn.execute('SELECT version_num FROM alembic_version').fetchone()[0], '20261105_36')
                self.assertIn('progress_quality_options', {c[1] for c in conn.execute('PRAGMA table_info(tahfiz)')})
                self.assertIsNotNone(conn.execute("SELECT name FROM sqlite_master WHERE name='student_registration_forms'").fetchone())
                self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

    def test_student_fields_migration_preserves_existing_forms_and_requests(self):
        migration = importlib.import_module('migrations.versions.20261105_36_registration_student_fields')
        engine = create_engine('sqlite:///:memory:')
        with engine.begin() as conn:
            conn.execute(text('CREATE TABLE student_registration_forms (id INTEGER PRIMARY KEY, title TEXT)'))
            conn.execute(text('CREATE TABLE student_registration_requests (id INTEGER PRIMARY KEY, phone TEXT)'))
            conn.execute(text("INSERT INTO student_registration_forms VALUES (1, 'Existing form')"))
            conn.execute(text("INSERT INTO student_registration_requests VALUES (1, '0123456')"))
            original = migration.op
            migration.op = Operations(MigrationContext.configure(conn))
            try:
                migration.upgrade()
                migration.upgrade()
                row = conn.execute(text('SELECT title, student_fields, required_student_fields FROM student_registration_forms')).one()
                self.assertEqual(tuple(row), ('Existing form', '["phone", "birthday"]', '[]'))
                row = conn.execute(text('SELECT phone, student_data FROM student_registration_requests')).one()
                self.assertEqual(tuple(row), ('0123456', '{}'))
                migration.downgrade()
                self.assertEqual(conn.execute(text('SELECT phone FROM student_registration_requests')).scalar(), '0123456')
            finally:
                migration.op = original
        engine.dispose()

    def test_migration_round_trip(self):
        migration = importlib.import_module('migrations.versions.20261031_34_student_registration')
        engine = create_engine('sqlite:///:memory:')
        with engine.begin() as conn:
            for table in ['tahfiz', 'users', 'students']:
                conn.execute(text(f'CREATE TABLE {table} (id INTEGER PRIMARY KEY)'))
            original = migration.op
            migration.op = Operations(MigrationContext.configure(conn))
            try:
                migration.upgrade(); migration.upgrade()
                self.assertIn('student_registration_requests', inspect(conn).get_table_names())
                self.assertIn('ix_registration_requests_tenant_status', {i['name'] for i in inspect(conn).get_indexes('student_registration_requests')})
                migration.downgrade()
                self.assertNotIn('student_registration_forms', inspect(conn).get_table_names())
            finally:
                migration.op = original
        engine.dispose()
