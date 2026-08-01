import inspect
import unittest

from fastapi import HTTPException
from pydantic import ValidationError

from app.routers import management
from app.schemas import DeleteSheikhRequest, DeleteSheikhStudentResolution


class SheikhDeletionPlanTests(unittest.TestCase):
    def resolution(self, student_id: int, action: str, sheikh_id: int | None = None):
        return DeleteSheikhStudentResolution(
            student_id=student_id,
            action=action,
            sheikh_id=sheikh_id,
        )

    def test_schema_requires_destination_only_for_reassignment(self):
        with self.assertRaises(ValidationError):
            self.resolution(1, "reassign")
        with self.assertRaises(ValidationError):
            self.resolution(1, "delete", 9)

    def test_schema_rejects_duplicate_student_resolutions(self):
        with self.assertRaises(ValidationError):
            DeleteSheikhRequest(student_resolutions=[
                self.resolution(1, "delete"),
                self.resolution(1, "reassign", 9),
            ])

    def test_plan_requires_exact_current_student_set(self):
        body = DeleteSheikhRequest(student_resolutions=[self.resolution(1, "delete")])
        with self.assertRaises(HTTPException) as raised:
            management.validate_sheikh_deletion_plan({1, 2}, body, 7, set())
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail["code"], "sheikh_students_changed")

    def test_plan_rejects_source_or_cross_tenant_destination(self):
        source_body = DeleteSheikhRequest(student_resolutions=[self.resolution(1, "reassign", 7)])
        with self.assertRaises(HTTPException) as source_error:
            management.validate_sheikh_deletion_plan({1}, source_body, 7, {7})
        self.assertEqual(source_error.exception.detail["code"], "cannot_reassign_to_deleted_sheikh")

        missing_body = DeleteSheikhRequest(student_resolutions=[self.resolution(1, "reassign", 8)])
        with self.assertRaises(HTTPException) as missing_error:
            management.validate_sheikh_deletion_plan({1}, missing_body, 7, set())
        self.assertEqual(missing_error.exception.detail["code"], "destination_sheikh_not_found")

    def test_valid_mixed_plan_is_accepted(self):
        body = DeleteSheikhRequest(student_resolutions=[
            self.resolution(1, "reassign", 8),
            self.resolution(2, "delete"),
        ])
        management.validate_sheikh_deletion_plan({1, 2}, body, 7, {8})

    def test_route_contract_preserves_history_and_linked_account_integrity(self):
        source = inspect.getsource(management.finalize_sheikh_deletion)
        self.assertIn("Attendance.sheikh_id == sheikh.id", source)
        self.assertIn("QuranProgressEntry.sheikh_id == sheikh.id", source)
        self.assertIn("UserTahfizMembership.sheikh_id == sheikh.id", source)
        self.assertIn("TahfizInvitation.sheikh_id == sheikh.id", source)
        self.assertIn("student.reassigned_before_sheikh_delete", source)
        self.assertIn("student.deleted_before_sheikh_delete", source)

    def test_legacy_delete_refuses_silent_unassignment(self):
        source = inspect.getsource(management.delete_sheikh)
        self.assertIn("sheikh_has_students", source)
        self.assertNotIn("values(sheikh_id=None)", source)

    def test_student_deletion_removes_progress_revisions_first(self):
        source = inspect.getsource(management.delete_student_entity)
        revision_position = source.index("QuranProgressRevision")
        progress_position = source.index("QuranProgressEntry")
        self.assertLess(revision_position, progress_position)


if __name__ == "__main__":
    unittest.main()
