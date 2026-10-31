import json
import unittest
from datetime import date

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import AuditLog, QuranProgressEntry, QuranProgressRevision, Session as StudySession, Student, Tahfiz, User, UserRole
from app.routers.auth import TenantContext
from app.routers.progress import save_session_progress
from app.schemas import QuranProgressBatchRequest, QuranProgressItem
from tests.test_finance_history_and_custom_progress import AsyncSessionAdapter


class ProgressDeletionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine, expire_on_commit=False)
        self.session.add_all([
            Tahfiz(id=1, name='Test', progress_tracking_enabled=True),
            User(id=1, username='admin', password_hash='unused', role=UserRole.admin, tahfiz_id=1),
            Student(id=1, name='Student', tahfiz_id=1, quran_progress_enabled=True),
            StudySession(id=10, date=date(2026, 10, 1), tahfiz_id=1, quran_progress_enabled=True, is_confirmed=False),
        ])
        self.session.commit()
        self.context = TenantContext(user=self.session.get(User, 1), tahfiz=self.session.get(Tahfiz, 1))
        self.db = AsyncSessionAdapter(self.session)
        self.deletion = QuranProgressBatchRequest(deletions=[dict(student_id=1, category='new_memorization')])

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    async def save_rating(self, score):
        await save_session_progress(10, QuranProgressBatchRequest(updates=[QuranProgressItem(
            student_id=1, category='new_memorization', range_type='surah_ayah',
            from_surah=1, from_ayah=1, to_surah=1, to_ayah=2, quality_score=score,
        )]), self.db, self.context)

    async def test_delete_saved_rating_preserves_audit_and_revision_history(self):
        await self.save_rating(4)
        await self.save_rating(5)
        self.assertEqual(len(self.session.scalars(select(QuranProgressRevision)).all()), 1)
        await save_session_progress(10, self.deletion, self.db, self.context)
        self.assertEqual(self.session.scalars(select(QuranProgressEntry)).all(), [])
        self.assertEqual(self.session.scalars(select(QuranProgressRevision)).all(), [])
        audit = self.session.scalars(select(AuditLog).order_by(AuditLog.id.desc())).first()
        deleted = json.loads(audit.details)['deleted'][0]
        self.assertEqual(deleted['before']['quality_score'], 5)
        self.assertEqual(deleted['revisions'][0]['before']['quality_score'], 4)
        # Retrying deletion is safe.
        await save_session_progress(10, self.deletion, self.db, self.context)

    async def test_confirmed_session_cannot_be_deleted(self):
        await self.save_rating(4)
        self.session.get(StudySession, 10).is_confirmed = True
        self.session.commit()
        with self.assertRaises(HTTPException) as error:
            await save_session_progress(10, self.deletion, self.db, self.context)
        self.assertEqual(error.exception.status_code, 409)
        self.assertIsNotNone(self.session.scalar(select(QuranProgressEntry)))

    async def test_other_tenant_student_cannot_be_deleted(self):
        self.session.add(Tahfiz(id=2, name='Other'))
        self.session.add(Student(id=2, name='Other student', tahfiz_id=2, quran_progress_enabled=True))
        self.session.commit()
        body = QuranProgressBatchRequest(deletions=[dict(student_id=2, category='new_memorization')])
        with self.assertRaises(HTTPException) as error:
            await save_session_progress(10, body, self.db, self.context)
        self.assertEqual(error.exception.status_code, 404)

    def test_empty_or_duplicate_changes_are_rejected(self):
        for payload in ({}, dict(deletions=[dict(student_id=1, category='test')] * 2)):
            with self.assertRaises(ValidationError):
                QuranProgressBatchRequest(**payload)
