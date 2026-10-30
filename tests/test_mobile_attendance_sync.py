import unittest
from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Attendance, Session as StudySession, Student, Tahfiz, User, UserRole
from app.routers.auth import TenantContext
from app.routers.sync import SyncMutation, SyncMutationBatch, mutations
from tests.test_finance_history_and_custom_progress import AsyncSessionAdapter


class MobileAttendanceSyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine, expire_on_commit=False)
        self.session.add_all([
            Tahfiz(id=1, name='Attendance only', progress_tracking_enabled=False),
            Tahfiz(id=2, name='Other tenant'),
            User(id=1, username='admin', password_hash='unused', role=UserRole.admin, tahfiz_id=1),
            Student(id=1, name='Student', tahfiz_id=1),
            Student(id=2, name='Other student', tahfiz_id=2),
            StudySession(id=10, date=date(2026, 10, 1), tahfiz_id=1,
                         quran_progress_enabled=False, is_confirmed=False),
        ])
        self.session.commit()
        self.db = AsyncSessionAdapter(self.session)
        self.context = TenantContext(user=self.session.get(User, 1), tahfiz=self.session.get(Tahfiz, 1))

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def mutation(self, mutation_id='attendance-offline-1', revision=0, student_id=1):
        return SyncMutation(mutation_id=mutation_id, device_id='test-device-1',
                            entity_type='attendance', entity_key=f'session:10:student:{student_id}',
                            base_revision=revision,
                            values=dict(session_id=10, student_id=student_id, status='حاضر', notes='offline'))

    async def push(self, mutation):
        return (await mutations(SyncMutationBatch(mutations=[mutation]), self.db, self.context))['results'][0]

    async def test_attendance_sync_works_without_quran_tracking_and_replays_receipts(self):
        first = await self.push(self.mutation())
        replay = await self.push(self.mutation())
        self.assertEqual(first['status'], 'applied')
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['entity']['revision'], first['entity']['revision'])
        self.assertEqual(len(self.session.scalars(select(Attendance)).all()), 1)

    async def test_stale_revisions_return_both_versions(self):
        await self.push(self.mutation())
        result = await self.push(self.mutation('attendance-offline-2'))
        self.assertEqual(result['status'], 'conflict')
        self.assertEqual(result['server']['revision'], 1)
        self.assertEqual(result['local']['notes'], 'offline')

    async def test_locked_sessions_and_other_tenants_remain_protected(self):
        result = await self.push(self.mutation('other-tenant-test', student_id=2))
        self.assertEqual(result['code'], 'entity_not_found')
        self.session.get(StudySession, 10).is_confirmed = True
        self.session.commit()
        result = await self.push(self.mutation('confirmed-session-test'))
        self.assertEqual(result['code'], 'session_locked')
        self.assertEqual(self.session.scalars(select(Attendance)).all(), [])
