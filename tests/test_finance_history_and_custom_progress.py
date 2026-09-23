import json
import importlib
import unittest
from datetime import date
from types import SimpleNamespace

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from app.database import Base
from app.models import QuranProgressEntry, Session as StudySession, Student, StudentStatus, StudentSubscription, StudentQuranPlan, Tahfiz, User, UserRole, WardIncrementUnit, progress_category_options
from app.routers import finance, progress, subscriptions
from app.routers.auth import TenantContext
from app.schemas import BulkSubscriptionPaymentRequest, QuranProgressBatchRequest, QuranProgressItem, SubscriptionPaymentRequest


class FinanceHistoryAndCustomProgressTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        with Session(self.engine) as db:
            db.add(Tahfiz(id=1, name="اختبار", month_start_day=1, subscriptions_enabled=True,
                          subscription_default_fee_minor=15000,
                          progress_tracking_enabled=True,
                          progress_categories=json.dumps(["new_memorization", "recent_revision", "تثبيت"], ensure_ascii=False)))
            db.add(User(id=1, username="admin", password_hash="unused", role=UserRole.admin, tahfiz_id=1))
            db.add_all([
                Student(id=1, name="قديم", tahfiz_id=1, status=StudentStatus.enrolled, registration_date=date(2026, 7, 10)),
                Student(id=2, name="جديد", tahfiz_id=1, status=StudentStatus.enrolled, registration_date=date(2026, 9, 1)),
                Student(id=3, name="منقطع", tahfiz_id=1, status=StudentStatus.discontinued, registration_date=date(2026, 7, 1)),
            ])
            db.commit()

    async def asyncTearDown(self):
        self.engine.dispose()

    async def test_historical_generation_is_scoped_and_idempotent(self):
        with Session(self.engine, expire_on_commit=False) as session:
            db = AsyncSessionAdapter(session)
            tahfiz = session.get(Tahfiz, 1)
            user = session.get(User, 1)
            context = SimpleNamespace(tahfiz_id=1, tahfiz=tahfiz, user=user)
            self.assertEqual(await subscriptions.ensure_subscription_records(
                db, context, date(2026, 8, 1), date(2026, 8, 31), date(2026, 8, 31)), 1)
            self.assertEqual(await subscriptions.ensure_subscription_records(
                db, context, date(2026, 8, 1), date(2026, 8, 31), date(2026, 8, 31)), 0)
            await db.commit()
            rows = (await db.execute(select(StudentSubscription))).scalars().all()
            self.assertEqual([(row.student_snapshot_id, row.period_start, row.amount_due_minor) for row in rows],
                             [(1, date(2026, 8, 1), 15000)])

    async def test_custom_category_is_stored_and_returned(self):
        with Session(self.engine) as db:
            tahfiz = db.get(Tahfiz, 1)
            self.assertEqual(progress_category_options(tahfiz), ["new_memorization", "recent_revision", "تثبيت"])
            db.add(StudentQuranPlan(tahfiz_id=1, student_id=1, category="تثبيت",
                                    increment_unit=WardIncrementUnit.ayahs, increment_amount=1,
                                    next_surah=1, next_ayah=1))
            db.commit()
            plan = db.execute(select(StudentQuranPlan).where(StudentQuranPlan.category == "تثبيت")).scalar_one()
            self.assertEqual(plan.category, "تثبيت")

    async def test_cash_and_bill_totals_use_their_respective_dates(self):
        with Session(self.engine, expire_on_commit=False) as session:
            db = AsyncSessionAdapter(session)
            context = SimpleNamespace(tahfiz_id=1, tahfiz=session.get(Tahfiz, 1), user=session.get(User, 1))
            await subscriptions.ensure_subscription_records(
                db, context, date(2026, 8, 1), date(2026, 8, 31), date(2026, 8, 31))
            await db.commit()
            record = session.execute(select(StudentSubscription)).scalar_one()
            await subscriptions.mark_paid(record.id, SubscriptionPaymentRequest(
                payment_date=date(2026, 9, 5), payment_method="cash"), db, context)
            august = await finance.overview(date(2026, 8, 1), db, context)
            september = await finance.overview(date(2026, 9, 1), db, context)
            self.assertEqual(august["collected_subscriptions_minor"], 15000)
            self.assertEqual(august["cash_collected_minor"], 0)
            self.assertEqual(september["cash_collected_minor"], 15000)

    async def test_bulk_payment_accepts_archived_historical_bill(self):
        with Session(self.engine, expire_on_commit=False) as session:
            db = AsyncSessionAdapter(session)
            context = SimpleNamespace(tahfiz_id=1, tahfiz=session.get(Tahfiz, 1), user=session.get(User, 1))
            session.add(StudentSubscription(tahfiz_id=1, student_id=3, student_snapshot_id=3,
                student_name="منقطع", period_start=date(2026, 8, 1), period_end=date(2026, 8, 31),
                amount_due_minor=15000, currency="EGP"))
            session.commit()
            record = session.execute(select(StudentSubscription)).scalar_one()
            result = await subscriptions.bulk_mark_paid(BulkSubscriptionPaymentRequest(
                record_ids=[record.id], payment_date=date(2026, 8, 10), payment_method="cash"), db, context)
            self.assertEqual(result["updated"], 1)
            self.assertTrue(session.get(StudentSubscription, record.id).is_paid)

    async def test_custom_category_can_be_recorded_in_a_session(self):
        with Session(self.engine, expire_on_commit=False) as session:
            student = session.get(Student, 1)
            student.quran_progress_enabled = True
            session.add(StudySession(id=10, date=date(2026, 9, 1), tahfiz_id=1,
                                     quran_progress_enabled=True, is_confirmed=False))
            session.commit()
            context = TenantContext(user=session.get(User, 1), tahfiz=session.get(Tahfiz, 1))
            db = AsyncSessionAdapter(session)
            result = await progress.save_session_progress(10, QuranProgressBatchRequest(updates=[QuranProgressItem(
                student_id=1, category="تثبيت", range_type="surah_ayah",
                from_surah=1, from_ayah=1, to_surah=1, to_ayah=2, quality_score=4,
            )]), db, context)
            self.assertEqual(result["saved"], 1)
            entry = session.execute(select(QuranProgressEntry)).scalar_one()
            self.assertEqual(progress.serialize_entry(entry)["category"], "تثبيت")


class AsyncSessionAdapter:
    def __init__(self, session: Session):
        self.session = session

    async def execute(self, statement):
        return self.session.execute(statement)

    async def scalar(self, statement):
        return self.session.scalar(statement)

    async def flush(self):
        self.session.flush()

    async def commit(self):
        self.session.commit()

    def add(self, row):
        self.session.add(row)

    def begin_nested(self):
        return AsyncNestedTransactionAdapter(self.session)


class AsyncNestedTransactionAdapter:
    def __init__(self, session: Session):
        self.session = session

    async def __aenter__(self):
        self.transaction = self.session.begin_nested()
        self.transaction.__enter__()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return self.transaction.__exit__(exc_type, exc_value, traceback)


class CustomProgressMigrationTests(unittest.TestCase):
    def test_existing_categories_survive_and_default_review_is_added(self):
        migration = importlib.import_module("migrations.versions.20260923_26_custom_progress_categories")
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE tahfiz (id INTEGER PRIMARY KEY, progress_categories TEXT NOT NULL)"))
            for table in migration.TABLES:
                connection.execute(text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, category VARCHAR(16) NOT NULL)"))
            connection.execute(text("INSERT INTO tahfiz VALUES (1, '[\"new_memorization\"]')"))
            connection.execute(text("INSERT INTO quran_progress_entries VALUES (1, 'old_revision')"))
            operations = Operations(MigrationContext.configure(connection))
            original_op = migration.op
            migration.op = operations
            try:
                migration.upgrade()
            finally:
                migration.op = original_op
            stored = connection.execute(text("SELECT progress_categories FROM tahfiz WHERE id = 1")).scalar_one()
            self.assertEqual(json.loads(stored), ["new_memorization", "recent_revision"])
            self.assertEqual(connection.execute(text("SELECT category FROM quran_progress_entries")).scalar_one(), "old_revision")
            self.assertEqual(inspect(connection).get_columns("quran_progress_entries")[1]["type"].length, 50)
            migration.op = operations
            try:
                migration.downgrade()
            finally:
                migration.op = original_op
            self.assertEqual(inspect(connection).get_columns("quran_progress_entries")[1]["type"].length, 16)
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
