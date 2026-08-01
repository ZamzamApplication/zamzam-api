import inspect
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from app.models import AuditLog
from app.routers import audit_logs


class AuditLogContractTests(unittest.TestCase):
    def test_serialization_exposes_actor_without_cross_tenant_metadata(self):
        log = SimpleNamespace(
            id=3,
            actor_user_id=7,
            action="session.reopened",
            details="session=2; reason=تصحيح",
            created_at=datetime(2026, 8, 1, 12, 30),
        )

        result = audit_logs.serialize_audit_log(log, "admin")

        self.assertEqual(result["actor_username"], "admin")
        self.assertEqual(result["action"], "session.reopened")
        self.assertNotIn("tahfiz_id", result)

    def test_route_is_admin_only_tenant_scoped_paginated_and_filtered(self):
        source = inspect.getsource(audit_logs.list_audit_logs)
        self.assertIn("Depends(require_tenant_admin)", source)
        self.assertGreaterEqual(source.count("AuditLog.tahfiz_id == context.tahfiz_id"), 3)
        for expected in ("page_size", "action", "actor_user_id", "date_from", "date_to", "query"):
            self.assertIn(expected, source)
        self.assertIn("invalid_audit_date_range", source)
        self.assertIn(".offset((page - 1) * page_size)", source)
        self.assertIn(".limit(page_size)", source)

    def test_model_and_migration_have_tenant_time_index(self):
        self.assertIn(
            "ix_audit_logs_tahfiz_created",
            {index.name for index in AuditLog.__table__.indexes},
        )
        migration = (Path(__file__).parents[1] / "migrations/versions/20260801_12_audit_log_tenant_time_index.py").read_text()
        self.assertIn('down_revision = "20260801_11"', migration)
        self.assertIn('"tahfiz_id", "created_at"', migration)


if __name__ == "__main__":
    unittest.main()
