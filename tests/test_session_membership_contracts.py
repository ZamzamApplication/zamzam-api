import unittest
from datetime import date, datetime

from app.models import Attendance, Session
from app.routers.reports import confirmed_session_records
from app.routers.sessions import student_is_in_session


class SessionMembershipContractTests(unittest.TestCase):
    def test_confirmed_session_excludes_student_without_attendance_snapshot(self):
        session = Session(id=10, date=date(2026, 8, 1), tahfiz_id=2, is_confirmed=True)

        self.assertFalse(student_is_in_session(session, None))
        self.assertTrue(student_is_in_session(
            session,
            Attendance(session_id=10, student_id=7, tahfiz_id=2, status="حاضر"),
        ))

    def test_reopened_session_allows_new_student_to_join(self):
        session = Session(
            id=10,
            date=date(2026, 8, 1),
            tahfiz_id=2,
            is_confirmed=False,
            reopened_at=datetime(2026, 8, 2),
        )

        self.assertTrue(student_is_in_session(session, None))

    def test_register_uses_null_for_non_member_and_preserves_real_status(self):
        sessions = [
            Session(id=10, date=date(2026, 8, 1), tahfiz_id=2, is_confirmed=True),
            Session(id=11, date=date(2026, 8, 2), tahfiz_id=2, is_confirmed=True),
        ]

        records = confirmed_session_records(sessions, 7, {(7, 11): "لا ينطبق"})

        self.assertIsNone(records["10"])
        self.assertEqual(records["11"], "لا ينطبق")


if __name__ == "__main__":
    unittest.main()
