import inspect
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from pydantic import ValidationError

from app.models import ACTIVE_STUDENT_STATUSES, StudentStatus, StudentSubscription
from app.routers import finance, management, reports, sessions, subscriptions
from app.schemas import BulkSubscriptionPaymentRequest, SignupRequest, SubscriptionAmountRequest, SubscriptionPaymentRequest, UpdateTahfizSettingsRequest


class SubscriptionPeriodTests(unittest.TestCase):
    def test_period_uses_configured_month_start(self):
        self.assertEqual(
            subscriptions.monthly_period(date(2026, 8, 20), 15),
            (date(2026, 8, 15), date(2026, 9, 14)),
        )
        self.assertEqual(
            subscriptions.monthly_period(date(2026, 8, 3), 15),
            (date(2026, 7, 15), date(2026, 8, 14)),
        )

    def test_record_serialization_matches_web_contract(self):
        record = SimpleNamespace(
            id=4,
            student_id=2,
            student_name="أحمد",
            student_custom_id="A-1",
            student_phone="0100",
            sheikh_id_snapshot=8,
            sheikh_name="الشيخ محمود",
            period_start=date(2026, 8, 1),
            period_end=date(2026, 8, 31),
            amount_due_minor=12500,
            currency="EGP",
            is_paid=False,
            payment_date=None,
            payment_method=None,
            payment_note=None,
            receipt_number=None,
        )
        serialized = subscriptions.serialize_record(record)
        self.assertEqual(serialized["fee_minor"], 12500)
        self.assertEqual(serialized["student_code"], "A-1")
        self.assertEqual(serialized["sheikh_id"], 8)
        self.assertIn("payment_date", serialized)


class SubscriptionSchemaTests(unittest.TestCase):
    def test_signup_requires_payment_configuration_when_subscriptions_are_enabled(self):
        with self.assertRaises(ValidationError):
            SignupRequest(
                username="owner",
                password="password123",
                tahfiz_name="دار الاختبار",
                subscriptions_enabled=True,
                subscription_default_fee_minor=0,
            )
        request = SignupRequest(
            username="owner",
            password="password123",
            tahfiz_name="دار الاختبار",
            subscriptions_enabled=True,
            subscription_default_fee_minor=15000,
            subscription_currency="egp",
            month_start_day=15,
        )
        self.assertEqual(request.subscription_currency, "EGP")
        self.assertEqual(request.month_start_day, 15)

    def test_main_settings_accept_optional_subscription_controls(self):
        request = UpdateTahfizSettingsRequest(
            subscriptions_enabled=True,
            subscription_default_fee_minor=12500,
            subscription_currency="egp",
        )
        self.assertTrue(request.subscriptions_enabled)
        self.assertEqual(request.subscription_default_fee_minor, 12500)

    def test_bulk_ids_must_be_unique(self):
        with self.assertRaises(ValidationError):
            BulkSubscriptionPaymentRequest(
                record_ids=[1, 1],
                payment_date=date(2026, 8, 1),
                payment_method="cash",
            )

    def test_future_override_requires_explicit_flag(self):
        with self.assertRaises(ValidationError):
            SubscriptionAmountRequest(fee_minor=1000, future_monthly_fee_minor=1200)

    def test_payment_methods_are_closed_set(self):
        with self.assertRaises(ValidationError):
            SubscriptionPaymentRequest(
                payment_date=date(2026, 8, 1),
                payment_method="card",
            )


class SubscriptionSourceContractTests(unittest.TestCase):
    def test_routes_match_web_contract(self):
        source = inspect.getsource(subscriptions)
        for route in (
            '@router.get("/settings")',
            '@router.put("/settings")',
            '@router.get("/months")',
            '@router.post("/months/bulk-mark-paid")',
            '@router.patch("/months/{record_id}")',
            '@router.post("/months/{record_id}/mark-paid")',
            '@router.post("/months/{record_id}/mark-unpaid")',
            '@router.get("/months/{record_id}/receipt")',
            '@router.get("/export")',
            '@router.get("/students/{student_id}/current")',
        ):
            self.assertIn(route, source)

    def test_every_financial_query_is_tenant_scoped_and_mutations_audited(self):
        source = inspect.getsource(subscriptions)
        self.assertGreaterEqual(source.count("tahfiz_id == context.tahfiz_id"), 12)
        for action in (
            "subscriptions.settings_updated",
            "subscriptions.student_fee_updated",
            "subscriptions.amount_corrected",
            "subscriptions.marked_paid",
            "subscriptions.bulk_marked_paid",
            "subscriptions.marked_unpaid",
        ):
            self.assertIn(action, source)

    def test_generation_and_payments_have_write_time_guards(self):
        source = inspect.getsource(subscriptions)
        self.assertIn(
            "uq_student_subscriptions_tenant_student_period",
            {constraint.name for constraint in StudentSubscription.__table__.constraints},
        )
        self.assertIn("StudentSubscription.is_paid.is_(False)", source)
        self.assertIn('"student_fee_override_minor"', source)
        self.assertIn("subscription_batch_stale", source)
        self.assertIn("subscription_currency_locked", source)
        self.assertIn("Student.registration_date <= today", source)
        self.assertIn("Student.status == StudentStatus.enrolled", source)
        self.assertIn('"student_not_enrolled"', source)

    def test_inactive_students_are_archived_but_guests_remain_operational(self):
        self.assertEqual(ACTIVE_STUDENT_STATUSES, (StudentStatus.enrolled, StudentStatus.guest))
        self.assertIn("Student.status.in_(ACTIVE_STUDENT_STATUSES)", inspect.getsource(sessions))
        self.assertIn("Student.status.in_(ACTIVE_STUDENT_STATUSES)", inspect.getsource(reports))

    def test_financial_views_only_bill_enrolled_students(self):
        self.assertIn("Student.status == StudentStatus.enrolled", inspect.getsource(subscriptions.filtered_statement))
        self.assertIn("Student.status == StudentStatus.enrolled", inspect.getsource(finance.overview))

    def test_student_deletion_removes_unpaid_subscriptions(self):
        source = inspect.getsource(management.delete_student_entity)
        self.assertIn("sa_delete(StudentSubscription)", source)
        self.assertIn("StudentSubscription.is_paid.is_(False)", source)
        self.assertIn("values(student_id=None)", source)

    def test_management_preserves_history_and_locks_month_start(self):
        source = inspect.getsource(management)
        self.assertIn("StudentSubscription.student_id == student.id", source)
        self.assertIn("values(student_id=None)", source)
        self.assertIn("subscription_month_start_locked", source)
        self.assertIn('"subscriptions": [serialize_subscription_record', source)
        self.assertIn('"subscription_fee_override_minor"', source)
        self.assertIn('"subscriptions_enabled"', source)
        self.assertIn("subscription_default_fee_required", source)
        self.assertIn("subscription_currency_locked", source)

    def test_cleanup_migration_removes_orphaned_unpaid_rows(self):
        migration = (Path(__file__).parents[1] / "migrations/versions/20260808_15_cleanup_orphaned_unpaid_subscriptions.py").read_text()
        self.assertIn('down_revision = "20260808_14"', migration)
        self.assertIn("DELETE FROM student_subscriptions", migration)
        self.assertIn("student_id IS NULL AND is_paid = FALSE", migration)

    def test_migration_contains_required_constraints_and_snapshots(self):
        migration = (Path(__file__).parents[1] / "migrations/versions/20260801_11_student_subscriptions.py").read_text()
        for expected in (
            'down_revision = "20260801_10"',
            '"student_subscriptions"',
            'ondelete="SET NULL"',
            '"student_snapshot_id"',
            '"student_name"',
            '"payment_method"',
            '"receipt_number"',
            '"uq_student_subscriptions_tenant_student_period"',
        ):
            self.assertIn(expected, migration)


if __name__ == "__main__":
    unittest.main()
