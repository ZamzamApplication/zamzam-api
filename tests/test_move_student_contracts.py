import inspect
import unittest
from types import SimpleNamespace

from fastapi import HTTPException
from pydantic import ValidationError

from app.models import AuditLog
from app.routers import management
from app.schemas import MoveStudentRequest


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeDb:
    def __init__(self, *results):
        self.results = list(results)
        self.added = []
        self.commits = 0
        self.execute_calls = 0

    async def execute(self, _statement):
        self.execute_calls += 1
        return ScalarResult(self.results.pop(0))

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.commits += 1


def context(tahfiz_id=7):
    return SimpleNamespace(tahfiz_id=tahfiz_id, user=SimpleNamespace(id=11))


class MoveStudentRequestTests(unittest.TestCase):
    def test_expected_current_sheikh_is_required(self):
        with self.assertRaises(ValidationError):
            MoveStudentRequest(sheikh_id=9)


class MoveStudentEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_cross_tenant_or_missing_student_is_not_found(self):
        db = FakeDb(None)

        with self.assertRaises(HTTPException) as raised:
            await management.move_student_sheikh(
                31,
                MoveStudentRequest(sheikh_id=9, expected_current_sheikh_id=3),
                db,
                context(),
            )

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(db.execute_calls, 1)
        self.assertEqual(db.commits, 0)

    async def test_success_moves_resets_order_audits_and_returns_details(self):
        student = SimpleNamespace(id=31, sheikh_id=3, sort_order=8)
        destination = SimpleNamespace(id=9, name="الشيخ الجديد")
        db = FakeDb(student, destination)

        response = await management.move_student_sheikh(
            31,
            MoveStudentRequest(sheikh_id=9, expected_current_sheikh_id=3),
            db,
            context(),
        )

        self.assertEqual(student.sheikh_id, 9)
        self.assertEqual(student.sort_order, 0)
        self.assertEqual(db.commits, 1)
        self.assertEqual(response["student_id"], 31)
        self.assertEqual(response["from_sheikh_id"], 3)
        self.assertEqual(response["destination_sheikh"], {"id": 9, "name": "الشيخ الجديد"})
        self.assertEqual(len(db.added), 1)
        audit = db.added[0]
        self.assertIsInstance(audit, AuditLog)
        self.assertEqual(audit.action, "student.sheikh_changed")
        self.assertEqual(audit.actor_user_id, 11)
        self.assertEqual(audit.tahfiz_id, 7)
        self.assertIn("student=31", audit.details)
        self.assertIn("from_sheikh=3", audit.details)
        self.assertIn("to_sheikh=9", audit.details)

    async def test_stale_source_returns_409_without_mutation(self):
        student = SimpleNamespace(id=31, sheikh_id=4, sort_order=8)
        db = FakeDb(student)

        with self.assertRaises(HTTPException) as raised:
            await management.move_student_sheikh(
                31,
                MoveStudentRequest(sheikh_id=9, expected_current_sheikh_id=3),
                db,
                context(),
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail["code"], "student_sheikh_changed")
        self.assertEqual(raised.exception.detail["current_sheikh_id"], 4)
        self.assertEqual(student.sheikh_id, 4)
        self.assertEqual(db.execute_calls, 1)
        self.assertEqual(db.commits, 0)
        self.assertEqual(db.added, [])

    async def test_same_target_is_rejected_without_mutation(self):
        student = SimpleNamespace(id=31, sheikh_id=3, sort_order=8)
        db = FakeDb(student)

        with self.assertRaises(HTTPException) as raised:
            await management.move_student_sheikh(
                31,
                MoveStudentRequest(sheikh_id=3, expected_current_sheikh_id=3),
                db,
                context(),
            )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail["code"], "student_already_assigned")
        self.assertEqual(db.execute_calls, 1)
        self.assertEqual(db.commits, 0)

    async def test_cross_tenant_or_missing_destination_is_not_found(self):
        student = SimpleNamespace(id=31, sheikh_id=3, sort_order=8)
        db = FakeDb(student, None)

        with self.assertRaises(HTTPException) as raised:
            await management.move_student_sheikh(
                31,
                MoveStudentRequest(sheikh_id=99, expected_current_sheikh_id=3),
                db,
                context(),
            )

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(student.sheikh_id, 3)
        self.assertEqual(db.commits, 0)

    def test_route_locks_and_tenant_scopes_both_entities(self):
        source = inspect.getsource(management.move_student_sheikh)

        self.assertEqual(source.count(".with_for_update()"), 2)
        self.assertEqual(source.count("tahfiz_id == context.tahfiz_id"), 2)
        self.assertIn('action="student.sheikh_changed"', source)


if __name__ == "__main__":
    unittest.main()
