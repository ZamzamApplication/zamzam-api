import importlib
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session as DBSession
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from fastapi import HTTPException
from pydantic import ValidationError
from app.database import Base
from app.models import (Tahfiz, User, UserRole, SessionSchedule, SessionOccurrence, Session,
                        Student, StudentStatus, StudentCategory, StudentCategoryMembership, Attendance)
from app.routers.auth import TenantContext
from app.routers.session_schedules import create_schedule, update_schedule, skip_occurrence, list_schedules
from app.schemas import SessionScheduleRequest, SkipOccurrenceRequest
from app.session_scheduler import generate_schedule, occurrence_dates, lock_schedule
from tests.test_finance_history_and_custom_progress import AsyncSessionAdapter

class ScheduleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(self.engine)
        self.session = DBSession(self.engine, expire_on_commit=False)
        self.session.add_all([Tahfiz(id=1, name='One'), Tahfiz(id=2, name='Two'),
            User(id=1, username='admin', password_hash='x', role=UserRole.admin, tahfiz_id=1),
            Student(id=1, name='Active', tahfiz_id=1, status=StudentStatus.enrolled),
            Student(id=2, name='Other', tahfiz_id=2, status=StudentStatus.enrolled)])
        self.session.commit()
        self.db = AsyncSessionAdapter(self.session)
        self.context = TenantContext(user=self.session.get(User, 1), tahfiz=self.session.get(Tahfiz, 1))
        self.clock = patch('app.session_scheduler.local_today', return_value=date(2026, 11, 1)); self.clock.start()
        self.router_clock = patch('app.routers.session_schedules.local_today', return_value=date(2026, 11, 1)); self.router_clock.start()
    def tearDown(self):
        self.clock.stop(); self.router_clock.stop(); self.session.close(); self.engine.dispose()
    def body(self, **values):
        return SessionScheduleRequest(**{**dict(weekdays=[0, 2], start_date='2026-11-01'), **values})
    async def test_generation_is_idempotent_and_tenant_scoped(self):
        result = await create_schedule(self.body(), self.db, self.context)
        self.assertEqual([v['date'] for v in result['upcoming']], ['2026-11-01','2026-11-03','2026-11-08'])
        row = await lock_schedule(self.db, result['id'], 1)
        await generate_schedule(self.db, row); self.session.commit()
        self.assertEqual(self.session.query(Session).count(), 3)
        self.assertEqual(self.session.query(Attendance).count(), 3)
        self.assertTrue(all(v.student_id == 1 for v in self.session.query(Attendance)))
        other = TenantContext(user=self.context.user, tahfiz=self.session.get(Tahfiz, 2))
        self.assertEqual(await list_schedules(self.db, other), [])
        with self.assertRaises(HTTPException) as error:
            await update_schedule(row.id, self.body(expected_version=1), self.db, other)
        self.assertEqual(error.exception.status_code, 404)
    async def test_pause_resume_and_stale_version(self):
        result = await create_schedule(self.body(), self.db, self.context)
        paused = await update_schedule(result['id'], self.body(is_active=False, expected_version=1), self.db, self.context)
        self.assertFalse(paused['is_active'])
        row = self.session.get(SessionSchedule, result['id'])
        await generate_schedule(self.db, row, date(2026,11,8))
        self.assertEqual(self.session.query(Session).count(), 3)
        with self.assertRaises(HTTPException) as error:
            await update_schedule(row.id, self.body(expected_version=1), self.db, self.context)
        self.assertEqual(error.exception.status_code, 409)
        row.is_active = True
        await generate_schedule(self.db, row, date(2026,11,8)); self.session.flush()
        self.assertEqual(self.session.query(Session).count(), 5)
    async def test_skip_archives_only_pristine_sessions_and_never_recreates(self):
        result = await create_schedule(self.body(), self.db, self.context)
        result = await skip_occurrence(result['id'], SkipOccurrenceRequest(date='2026-11-03', expected_version=1), self.db, self.context)
        receipt = self.session.scalar(select(SessionOccurrence).where(SessionOccurrence.date == date(2026,11,3)))
        self.assertEqual(receipt.status, 'skipped')
        self.assertIsNotNone(self.session.get(Session, receipt.session_id).archived_at)
        await generate_schedule(self.db, self.session.get(SessionSchedule,result['id']))
        self.assertEqual(self.session.query(Session).count(),3)
        attendance = self.session.scalar(select(Attendance).where(Attendance.session_id == result['upcoming'][0]['session_id']))
        attendance.revision = 2; self.session.commit()
        with self.assertRaises(HTTPException) as error:
            await skip_occurrence(result['id'],SkipOccurrenceRequest(date='2026-11-01',expected_version=2),self.db,self.context)
        self.assertEqual(error.exception.status_code,409)
    async def test_existing_manual_session_is_not_duplicated(self):
        self.session.add(Session(date=date(2026,11,1),tahfiz_id=1)); self.session.commit()
        result = await create_schedule(self.body(),self.db,self.context)
        self.assertEqual(result['upcoming'][0]['status'],'conflict')
        self.assertEqual(self.session.query(Session).count(),3)
    async def test_dynamic_categories_and_cross_tenant_members(self):
        self.context.tahfiz.multiple_sessions_per_day_enabled = True
        self.session.add_all([StudentCategory(id=1,tahfiz_id=1,name='Group'),StudentCategoryMembership(tahfiz_id=1,category_id=1,student_id=1)])
        self.session.commit()
        with self.assertRaises(HTTPException):
            await create_schedule(self.body(membership_mode='students',member_ids=[2]),self.db,self.context)
        result = await create_schedule(self.body(membership_mode='categories',member_ids=[1]),self.db,self.context)
        self.session.add(Student(id=3,name='New',tahfiz_id=1,status=StudentStatus.enrolled))
        self.session.add(StudentCategoryMembership(tahfiz_id=1,category_id=1,student_id=3)); self.session.commit()
        await generate_schedule(self.db,self.session.get(SessionSchedule,result['id']),date(2026,11,8)); self.session.flush()
        session = self.session.scalar(select(Session).where(Session.date == date(2026,11,10)))
        self.assertEqual(set(self.session.scalars(select(Attendance.student_id).where(Attendance.session_id == session.id))),{1,3})
    def test_validation_and_bounds(self):
        for values in [dict(weekdays=[7]),dict(weekdays=[0,0]),dict(weekdays=[]),dict(timezone='Invalid/Zone'),dict(end_date='2026-10-31'),dict(membership_mode='students')]:
            with self.assertRaises(ValidationError): self.body(**values)
        row = SimpleNamespace(start_date=date(2026,11,1),end_date=date(2026,11,3),weekdays='[0,2]')
        self.assertEqual(list(occurrence_dates(row,date(2026,11,1))),[date(2026,11,1),date(2026,11,3)])

class ScheduleMigrationTests(unittest.TestCase):
    def test_repeatable_migration_preserves_sessions(self):
        migration = importlib.import_module('migrations.versions.20261101_35_session_schedules')
        engine = create_engine('sqlite:///:memory:')
        with engine.begin() as conn:
            for table in ['tahfiz','users','sessions']: conn.execute(text(f'CREATE TABLE {table} (id INTEGER PRIMARY KEY)'))
            conn.execute(text('INSERT INTO sessions VALUES (1)'))
            original = migration.op; migration.op = Operations(MigrationContext.configure(conn))
            try:
                migration.upgrade(); migration.upgrade()
                self.assertEqual(conn.execute(text('SELECT id FROM sessions')).scalar(),1)
                migration.downgrade()
            finally: migration.op = original
        engine.dispose()

class ConcurrentSchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_workers_create_one_occurrence_and_rollbacks_leave_no_receipt(self):
        import asyncio
        import tempfile
        from pathlib import Path
        from sqlalchemy import event
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        with tempfile.TemporaryDirectory() as folder:
            engine = create_async_engine(f'sqlite+aiosqlite:///{Path(folder) / "schedules.db"}')
            @event.listens_for(engine.sync_engine, 'connect')
            def configure(connection, _):
                connection.execute('PRAGMA foreign_keys=ON')
                connection.execute('PRAGMA busy_timeout=5000')
            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with factory() as db:
                db.add(Tahfiz(id=1,name='Concurrent')); await db.flush()
                db.add(User(id=1,username='admin',password_hash='x',role=UserRole.admin,tahfiz_id=1)); await db.flush()
                db.add(SessionSchedule(id=1,tahfiz_id=1,created_by_id=1,weekdays='[0]',start_date=date(2026,11,1),end_date=date(2026,11,1),timezone='Africa/Cairo',membership_mode='all',member_ids='[]'))
                await db.commit()
            async def worker(rollback=False):
                async with factory() as db:
                    row = await lock_schedule(db,1,1)
                    await generate_schedule(db,row,date(2026,11,1))
                    if rollback: await db.rollback()
                    else: await db.commit()
            await worker(rollback=True)
            async with factory() as db:
                self.assertEqual((await db.execute(select(SessionOccurrence))).scalars().all(),[])
                self.assertEqual((await db.execute(select(Session))).scalars().all(),[])
            await asyncio.gather(worker(),worker())
            async with factory() as db:
                rows = (await db.execute(select(Session))).scalars().all()
                receipts = (await db.execute(select(SessionOccurrence))).scalars().all()
                self.assertEqual(len(rows),1); self.assertEqual(len(receipts),1)
                await db.delete(rows[0]); await db.commit()
            await worker()
            async with factory() as db:
                self.assertEqual((await db.execute(select(Session))).scalars().all(),[])
                receipt = (await db.execute(select(SessionOccurrence))).scalar_one()
                self.assertIsNone(receipt.session_id)
            await engine.dispose()
