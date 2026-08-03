import inspect
import importlib
import json
import unittest
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

from pydantic import ValidationError
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect as sqlalchemy_inspect, text

from app.models import DEFAULT_EXPENSE_CATEGORIES, Expense, expense_category_options
from app.routers import finance, subscriptions
from app.schemas import BulkSubscriptionAmountRequest, ExpenseRequest, UpdateTahfizSettingsRequest


class FinanceSchemaTests(unittest.TestCase):
    def test_expense_requires_positive_amount_and_closed_payment_method(self):
        with self.assertRaises(ValidationError):
            ExpenseRequest(
                name="إيجار",
                category_id="rent",
                amount_minor=0,
                expense_date=date(2026, 8, 1),
                payment_method="cash",
            )
        with self.assertRaises(ValidationError):
            ExpenseRequest(
                name="إيجار",
                category_id="rent",
                amount_minor=100,
                expense_date=date(2026, 8, 1),
                payment_method="card",
            )

    def test_bulk_correction_requires_distinct_nonzero_source(self):
        with self.assertRaises(ValidationError):
            BulkSubscriptionAmountRequest(period=date(2026, 8, 1), from_fee_minor=0, to_fee_minor=100)
        with self.assertRaises(ValidationError):
            BulkSubscriptionAmountRequest(period=date(2026, 8, 1), from_fee_minor=100, to_fee_minor=100)

    def test_settings_accept_ordered_enabled_categories(self):
        request = UpdateTahfizSettingsRequest(expense_categories=[
            {"id": "rent", "label": "إيجار", "enabled": True},
            {"id": "other", "label": "أخرى", "enabled": False},
        ])
        self.assertEqual([category.id for category in request.expense_categories], ["rent", "other"])


class FinanceContractTests(unittest.TestCase):
    def test_default_categories_and_serialization_are_stable(self):
        tahfiz = SimpleNamespace(expense_categories=json.dumps(DEFAULT_EXPENSE_CATEGORIES, ensure_ascii=False))
        self.assertEqual(expense_category_options(tahfiz), DEFAULT_EXPENSE_CATEGORIES)
        expense = SimpleNamespace(
            id=1,
            name="إيجار المقر",
            category_id="rent",
            category_label_snapshot="إيجار",
            amount_minor=150000,
            currency="EGP",
            expense_date=date(2026, 8, 1),
            payment_method="bank_transfer",
            note=None,
            created_at=datetime(2026, 8, 1),
            updated_at=datetime(2026, 8, 1),
        )
        context = SimpleNamespace(tahfiz=tahfiz)
        self.assertEqual(finance.serialize_expense(expense, context)["amount_minor"], 150000)

    def test_finance_routes_are_admin_scoped_and_audited(self):
        source = inspect.getsource(finance)
        for route in (
            '@router.get("/overview")',
            '@router.get("/expenses")',
            '@router.post("/expenses", status_code=201)',
            '@router.patch("/expenses/{expense_id}")',
            '@router.delete("/expenses/{expense_id}", status_code=204)',
        ):
            self.assertIn(route, source)
        self.assertGreaterEqual(source.count("Expense.tahfiz_id == context.tahfiz_id"), 4)
        self.assertGreaterEqual(source.count("Depends(require_tenant_admin)"), 6)
        for action in ("finance.expense_created", "finance.expense_updated", "finance.expense_deleted"):
            self.assertIn(action, source)

    def test_cash_overview_uses_transaction_dates(self):
        source = inspect.getsource(finance.overview)
        self.assertIn("StudentSubscription.payment_date >= start", source)
        self.assertIn("Expense.expense_date >= start", source)
        self.assertIn('"net_cash_minor": cash_collected - expenses', source)

    def test_bulk_correction_protects_paid_and_custom_fees(self):
        source = inspect.getsource(subscriptions.bulk_correct_amount)
        self.assertIn("StudentSubscription.is_paid.is_(False)", source)
        self.assertIn("StudentSubscription.amount_due_minor == body.from_fee_minor", source)
        self.assertIn("Student.subscription_fee_override_minor.is_(None)", source)
        self.assertIn("subscriptions.bulk_amount_corrected", source)

    def test_expense_model_and_migration_keep_soft_delete_history(self):
        self.assertIn("ck_expenses_amount_positive", {constraint.name for constraint in Expense.__table__.constraints})
        migration = (Path(__file__).parents[1] / "migrations/versions/20260803_13_finance_expenses.py").read_text()
        for expected in ('down_revision = "20260801_12"', '"expenses"', '"expense_categories"', '"deleted_at"'):
            self.assertIn(expected, migration)

    def test_migration_upgrades_existing_tahfiz(self):
        migration = importlib.import_module("migrations.versions.20260803_13_finance_expenses")
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE tahfiz (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"))
            connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
            connection.execute(text("INSERT INTO tahfiz (id, name) VALUES (1, 'اختبار')"))
            operations = Operations(MigrationContext.configure(connection))
            original_op = migration.op
            migration.op = operations
            try:
                migration.upgrade()
            finally:
                migration.op = original_op
            self.assertIn("expenses", sqlalchemy_inspect(connection).get_table_names())
            stored = connection.execute(text("SELECT expense_categories FROM tahfiz WHERE id = 1")).scalar_one()
            self.assertEqual(json.loads(stored), DEFAULT_EXPENSE_CATEGORIES)
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
