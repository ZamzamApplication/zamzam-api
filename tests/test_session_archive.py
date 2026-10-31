import unittest
import importlib
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text
from fastapi import HTTPException
from app.models import Attendance, AuditLog, Session as StudySession
from app.routers.sessions import archive_session, recover_session, update_session
from app.routers.sync import serialize_session
from app.schemas import ArchiveSessionRequest, UpdateSessionRequest
from tests import test_mobile_attendance_sync as fixtures

class SessionArchiveTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.MobileAttendanceSyncTests.setUp
    tearDown = fixtures.MobileAttendanceSyncTests.tearDown
    push = fixtures.MobileAttendanceSyncTests.push
    mutation = fixtures.MobileAttendanceSyncTests.mutation
    async def test_archive_blocks_mutations_preserves_records_and_recovers_with_version(self):
        self.session.add(Attendance(session_id=10,student_id=1,tahfiz_id=1,status='حاضر',revision=1))
        self.session.commit()
        archived=await archive_session(10,ArchiveSessionRequest(expected_version=0,reason='Duplicate lesson'),self.db,self.context)
        self.assertEqual(archived['version'],1)
        self.assertIsNotNone(serialize_session(self.session.get(StudySession,10))['archived_at'])
        result=await self.push(self.mutation(revision=1))
        self.assertEqual(result['code'],'session_archived')
        with self.assertRaises(HTTPException) as error:
            await update_session(10,UpdateSessionRequest(session_date='2026-10-02'),self.db,self.context)
        self.assertEqual(error.exception.status_code,409)
        self.assertEqual(self.session.query(Attendance).count(),1)
        with self.assertRaises(HTTPException):
            await recover_session(10,ArchiveSessionRequest(expected_version=0,reason='Recover lesson'),self.db,self.context)
        restored=await recover_session(10,ArchiveSessionRequest(expected_version=1,reason='Recover lesson'),self.db,self.context)
        self.assertEqual(restored['version'],2)
        self.assertIsNone(self.session.get(StudySession,10).archived_at)
        self.assertEqual(self.session.query(AuditLog).filter(AuditLog.action.in_(['session.archived','session.recovered'])).count(),2)
    async def test_archive_is_tenant_scoped_and_preserves_confirmation(self):
        row=self.session.get(StudySession,10);row.is_confirmed=True;self.session.commit()
        with self.assertRaises(HTTPException) as error:
            await archive_session(99,ArchiveSessionRequest(expected_version=0,reason='Archive lesson'),self.db,self.context)
        self.assertEqual(error.exception.status_code,404)
        await archive_session(10,ArchiveSessionRequest(expected_version=0,reason='Archive lesson'),self.db,self.context)
        await recover_session(10,ArchiveSessionRequest(expected_version=1,reason='Restore lesson'),self.db,self.context)
        self.assertTrue(row.is_confirmed)


class SessionArchiveMigrationTests(unittest.TestCase):
    def test_upgrade_preserves_old_rows_and_can_run_again(self):
        migration=importlib.import_module('migrations.versions.20261031_33_session_archive')
        engine=create_engine('sqlite:///:memory:')
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE sessions (id INTEGER PRIMARY KEY, date DATE)'))
            connection.execute(text("INSERT INTO sessions VALUES (1,'2026-10-01')"))
            original=migration.op
            migration.op=Operations(MigrationContext.configure(connection))
            try:
                migration.upgrade();migration.upgrade()
                self.assertEqual(connection.execute(text('SELECT id, archived_at FROM sessions')).all(),[(1,None)])
                migration.downgrade()
                self.assertEqual(connection.execute(text('SELECT id, date FROM sessions')).all(),[(1,'2026-10-01')])
            finally: migration.op=original
        engine.dispose()

class WarningRetryTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.MobileAttendanceSyncTests.setUp
    tearDown = fixtures.MobileAttendanceSyncTests.tearDown
    async def test_sent_warning_replay_does_not_send_again_and_other_tenant_is_hidden(self):
        from unittest.mock import AsyncMock, patch
        from app.models import StudentWarning
        from app.routers.management import send_warnings
        from app.schemas import SendWarningsRequest
        self.session.add_all([StudentWarning(id=1,student_id=1,reason='Test',warning_number=1,sent=True),StudentWarning(id=2,student_id=2,reason='Other tenant',warning_number=1,sent=True)])
        self.session.commit()
        async def get(model, key): return self.session.get(model,key)
        self.db.get=get
        with patch('app.routers.management.send_whatsend_group_message',new_callable=AsyncMock) as provider:
            response=await send_warnings(SendWarningsRequest(warning_ids=[1,2]),self.db,self.context)
            self.assertTrue(response['results'][0]['replayed'])
            self.assertFalse(response['results'][1]['success'])
            provider.assert_not_awaited()
