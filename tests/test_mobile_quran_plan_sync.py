import unittest
from typing import get_type_hints
from app.routers.progress import advance_plan_cursor
from app.schemas import QuranProgressItem
from app.models import Student, Session as StudySession, StudentQuranPlan, Tahfiz, WardIncrementUnit, QuranProgressEntry
from app.routers.sync import SyncMutation, SyncMutationBatch, mutations
from tests import test_mobile_attendance_sync as fixtures

class MobileQuranPlanSyncTests(unittest.IsolatedAsyncioTestCase):
    def test_plan_cursor_annotations_resolve(self):
        self.assertIs(get_type_hints(advance_plan_cursor)['item'], QuranProgressItem)

    tearDown = fixtures.MobileAttendanceSyncTests.tearDown
    def setUp(self):
        fixtures.MobileAttendanceSyncTests.setUp(self)
        self.session.get(Tahfiz, 1).progress_tracking_enabled = True
        self.session.get(Student, 1).quran_progress_enabled = True
        self.session.get(StudySession, 10).quran_progress_enabled = True
        self.session.add(StudentQuranPlan(id=1, tahfiz_id=1, student_id=1, category='new_memorization', increment_unit=WardIncrementUnit.pages, increment_amount=2, next_page=1))
        self.session.commit()
    async def push(self, key='quran-sync-test-1', revision=0, **patch):
        values=dict(session_id=10, student_id=1, category='new_memorization', range_type='page', from_page=1, to_page=2, quality_score=5)
        values.update(patch)
        item=SyncMutation(mutation_id=key, device_id='quran-device-1', entity_type='quran_progress', entity_key='session:10:student:1:category:new_memorization', base_revision=revision, values=values)
        return (await mutations(SyncMutationBatch(mutations=[item]),self.db,self.context))['results'][0]
    async def test_plan_advances_once_and_receipt_replay_does_not_advance_again(self):
        first=await self.push()
        self.assertEqual(first['status'],'applied')
        self.assertEqual(self.session.get(StudentQuranPlan,1).next_page,3)
        replay=await self.push()
        self.assertTrue(replay['replayed'])
        self.assertEqual(self.session.get(StudentQuranPlan,1).next_page,3)
        conflict=await self.push('quran-sync-test-2')
        self.assertEqual(conflict['status'],'conflict')
        self.assertEqual(self.session.get(StudentQuranPlan,1).next_page,3)
        edit=await self.push('quran-sync-test-3',revision=1,to_page=4)
        self.assertEqual(edit['status'],'applied')
        self.assertEqual(self.session.get(StudentQuranPlan,1).next_page,3)
    async def test_disabled_student_session_and_explicit_membership_are_rejected(self):
        self.session.get(Student,1).quran_progress_enabled=False
        self.assertEqual((await self.push())['code'],'student_progress_disabled')
        self.session.get(Student,1).quran_progress_enabled=True
        self.session.get(StudySession,10).quran_progress_enabled=False
        self.assertEqual((await self.push('quran-sync-disabled-session'))['code'],'session_progress_disabled')
        self.session.get(StudySession,10).quran_progress_enabled=True
        self.session.get(StudySession,10).explicit_membership=True
        self.assertEqual((await self.push('quran-sync-not-a-member'))['code'],'entity_not_found')
        self.assertEqual(self.session.query(QuranProgressEntry).count(),0)
    async def test_reverse_plan_advances_toward_first_page(self):
        plan=self.session.get(StudentQuranPlan,1); plan.direction='backward';plan.next_page=604
        self.assertEqual((await self.push(direction='backward',from_page=604,to_page=603))['status'],'applied')
        self.assertEqual(plan.next_page,602)
