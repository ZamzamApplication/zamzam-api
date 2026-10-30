import unittest

from app.models import Attendance, Sheikh, Student
from app.routers.sessions import get_session_attendance
from tests import test_mobile_attendance_sync as fixtures


class MobileRosterRevisionTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.MobileAttendanceSyncTests.setUp
    tearDown = fixtures.MobileAttendanceSyncTests.tearDown
    mutation = fixtures.MobileAttendanceSyncTests.mutation
    push = fixtures.MobileAttendanceSyncTests.push

    async def test_existing_roster_row_exposes_its_revision_and_syncs_without_false_conflict(self):
        self.session.add(Sheikh(id=5, name='Teacher', tahfiz_id=1))
        self.session.get(Student, 1).sheikh_id = 5
        self.session.add(Attendance(id=900, session_id=10, student_id=1, tahfiz_id=1,
                                    status='غياب', sheikh_id=5, revision=4))
        self.session.commit()
        roster = await get_session_attendance(10, db=self.db, context=self.context)
        row = next(s for g in roster['sheikh_groups'] for s in g['students'] if s['id'] == 1)
        self.assertEqual(row['attendance_id'], 900)
        self.assertEqual(row['revision'], 4)
        result = await self.push(self.mutation(revision=row['revision']))
        self.assertEqual(result['status'], 'applied')
        self.assertEqual(result['entity']['revision'], 5)
