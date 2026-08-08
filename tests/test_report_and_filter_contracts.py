import unittest
from collections import Counter
from datetime import date, datetime

from app.models import DEFAULT_ATTENDANCE_STATUSES, Tahfiz, TahfizStatus, User, UserRole, attendance_status_options
from app.routers.auth import TenantContext
from app.routers.reports import attendance_report_metrics, circle_attendance_rate
from app.routers.saved_filters import create_saved_filter, list_saved_filters
from app.schemas import CreateSavedFilterRequest


def make_context(tahfiz_id: int = 1) -> TenantContext:
    user = User(
        id=11,
        username="tenant-admin",
        password_hash="not-used-in-contract-tests",
        role=UserRole.admin,
        tahfiz_id=tahfiz_id,
    )
    tahfiz = Tahfiz(
        id=tahfiz_id,
        name="Tenant",
        status=TahfizStatus.active,
    )
    return TenantContext(user=user, tahfiz=tahfiz)


class _RowsResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _ScalarsResult:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


class _SequencedSession:
    def __init__(self, results):
        self.results = iter(results)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return next(self.results)


class _SavedFilterSession:
    def __init__(self):
        self.added = None
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _ScalarsResult([])

    def add(self, value):
        self.added = value

    async def commit(self):
        return None

    async def refresh(self, value):
        value.id = 91
        value.created_at = datetime(2026, 1, 1)


class MonthlyReportContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_attendance_rate_query_includes_both_month_boundaries(self):
        date_from = date(2026, 7, 1)
        date_to = date(2026, 7, 31)
        db = _SequencedSession([
            _RowsResult([(25,)]),
            _RowsResult([]),
        ])

        response = await circle_attendance_rate(
            circle_id=1,
            date_from=date_from,
            date_to=date_to,
            db=db,
            context=make_context(),
        )

        attendance_query = db.statements[1]
        query_text = str(attendance_query)
        query_params = list(attendance_query.compile().params.values())
        self.assertIn("sessions.date >=", query_text)
        self.assertIn("sessions.date <=", query_text)
        self.assertIn(date_from, query_params)
        self.assertIn(date_to, query_params)
        self.assertEqual(response["total_attendance_records"], 0)


class AttendanceStatusSettingsTests(unittest.TestCase):
    def test_defaults_match_existing_attendance_options(self):
        tahfiz = Tahfiz(name="Tenant", status=TahfizStatus.active)
        self.assertEqual(attendance_status_options(tahfiz), DEFAULT_ATTENDANCE_STATUSES)

    def test_custom_statuses_are_trimmed_and_preserve_order(self):
        tahfiz = Tahfiz(
            name="Tenant",
            status=TahfizStatus.active,
            attendance_statuses='[" حاضر ", "عن بعد"]',
        )
        self.assertEqual(attendance_status_options(tahfiz), ["حاضر", "عن بعد"])

    def test_report_metrics_follow_renamed_statuses_and_preserve_order(self):
        tahfiz = Tahfiz(
            name="Tenant",
            status=TahfizStatus.active,
            attendance_statuses='["موجود", "متغيب", "بعذر", "عن بعد"]',
            attendance_status_colors='{"موجود":"green","متغيب":"slate","بعذر":"amber","عن بعد":"violet"}',
        )

        metrics = attendance_report_metrics(
            Counter({"موجود": 4, "متغيب": 2, "بعذر": 1, "عن بعد": 3}),
            tahfiz,
        )

        self.assertEqual(
            metrics["status_counts"],
            {"موجود": 4, "متغيب": 2, "بعذر": 1, "عن بعد": 3},
        )
        self.assertEqual(metrics["total_records"], 10)
        self.assertEqual(metrics["attendance_rate"], 50.0)
        self.assertEqual(metrics["present"], 4)
        self.assertEqual(metrics["excused"], 1)

    def test_report_metrics_follow_configured_present_status_without_label_or_color(self):
        tahfiz = Tahfiz(
            name="Tenant",
            status=TahfizStatus.active,
            attendance_statuses='["✓", "غياب"]',
            attendance_status_colors='{"✓":"violet","غياب":"slate"}',
            present_status="✓",
        )

        metrics = attendance_report_metrics(
            Counter({"✓": 5, "غياب": 2}),
            tahfiz,
        )

        self.assertEqual(metrics["present"], 5)
        self.assertEqual(metrics["attendance_rate"], 71.4)


class SavedFilterTenantContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_is_scoped_to_current_tahfiz(self):
        db = _SavedFilterSession()

        result = await list_saved_filters(db=db, context=make_context(tahfiz_id=8))

        self.assertEqual(result, [])
        statement = db.statements[0]
        self.assertIn("saved_filters.tahfiz_id", str(statement))
        self.assertIn(8, statement.compile().params.values())

    async def test_create_assigns_current_user_and_tahfiz(self):
        db = _SavedFilterSession()
        context = make_context(tahfiz_id=8)

        result = await create_saved_filter(
            body=CreateSavedFilterRequest(name="July", data='{"groups": []}'),
            db=db,
            context=context,
        )

        self.assertEqual(db.added.user_id, context.user.id)
        self.assertEqual(db.added.tahfiz_id, 8)
        self.assertEqual(result["name"], "July")


if __name__ == "__main__":
    unittest.main()
