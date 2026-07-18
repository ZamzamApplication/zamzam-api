import unittest
from datetime import date, datetime

from app.models import Tahfiz, TahfizStatus, User, UserRole
from app.routers.auth import TenantContext
from app.routers.reports import circle_attendance_rate
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
