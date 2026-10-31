import importlib
import inspect as python_inspect
import json
import unittest
from datetime import date

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import AuditLog, Student, Tahfiz, Trip, TripCheck, TripGroup, TripParticipant, TripRound, User, UserRole
from app.routers import trips
from app.routers.auth import TenantContext, require_tenant_admin
from tests.test_finance_history_and_custom_progress import AsyncSessionAdapter


class TripTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        @event.listens_for(self.engine, 'connect')
        def foreign_keys(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine, expire_on_commit=False)
        self.session.add_all([Tahfiz(id=1, name='One'), Tahfiz(id=2, name='Two')])
        self.session.flush()
        self.session.add_all([
            User(id=1, username='admin', password_hash='unused', role=UserRole.admin, tahfiz_id=1),
            User(id=2, username='other', password_hash='unused', role=UserRole.admin, tahfiz_id=2),
            Student(id=1, name='أحمد محمد', student_id='123', tahfiz_id=1),
            Student(id=2, name='علي حسن', tahfiz_id=1),
            Student(id=3, name='Other tenant', tahfiz_id=2),
        ])
        self.session.commit()
        self.context = TenantContext(user=self.session.get(User, 1), tahfiz=self.session.get(Tahfiz, 1))
        self.other = TenantContext(user=self.session.get(User, 2), tahfiz=self.session.get(Tahfiz, 2))
        self.db = AsyncSessionAdapter(self.session)

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    async def create(self, context=None):
        result = await trips.create_trip(trips.TripInput(name='رحلة', date=date(2026, 10, 20), fee_minor=15000), self.db, context or self.context)
        return result['id']

    async def detail(self, trip_id, round_id=None):
        # Simulate a new HTTP request/session so tests also exercise fresh reads.
        self.session.expire_all()
        return await trips.trip_detail(trip_id, round_id, self.db, self.context)

    async def roster(self, trip_id):
        await trips.add_participants(trip_id, trips.RosterInput(student_ids=[1, 2], guests=[dict(name='أستاذ خالد', is_adult=True)]), self.db, self.context)
        return (await self.detail(trip_id))['participants']

    async def start(self, trip_id, title='الصباح'):
        detail = await self.detail(trip_id)
        return (await trips.start_round(trip_id, trips.RoundInput(title=title, expected_version=detail['trip']['version']), self.db, self.context))['id']

    async def patch(self, trip_id, person, **values):
        await trips.update_participant(trip_id, person['id'], trips.ParticipantInput(expected_version=person['version'], **values), self.db, self.context)

    async def assert_http(self, code, call):
        with self.assertRaises(HTTPException) as error:
            await call
        self.assertEqual(error.exception.status_code, code)
        self.session.rollback()

    async def test_roster_supports_students_guests_and_scoped_student_search(self):
        trip_id = await self.create()
        people = await self.roster(trip_id)
        self.assertEqual(len(people), 3)
        self.assertEqual({person['kind'] for person in people}, {'student', 'guest'})
        self.assertTrue(next(person for person in people if person['kind'] == 'guest')['is_adult'])
        self.assertEqual({student['id'] for student in await trips.trip_students(self.db, self.context)}, {1, 2})
        await self.assert_http(404, trips.add_participants(trip_id, trips.RosterInput(student_ids=[3]), self.db, self.context))
        await self.assert_http(409, trips.add_participants(trip_id, trips.RosterInput(student_ids=[1]), self.db, self.context))

    async def test_trip_and_all_operations_are_tenant_scoped(self):
        trip_id = await self.create(self.other)
        await self.assert_http(404, trips.trip_detail(trip_id, None, self.db, self.context))
        await self.assert_http(404, trips.add_participants(trip_id, trips.RosterInput(student_ids=[1]), self.db, self.context))
        await self.assert_http(404, trips.add_group(trip_id, trips.GroupInput(name='Bus'), self.db, self.context))
        self.assertEqual(await trips.list_trips(self.db, self.context), [])

    async def test_payment_partial_exemption_and_stale_edits(self):
        trip_id = await self.create()
        person = (await self.roster(trip_id))[0]
        await self.patch(trip_id, person, paid_minor=5000)
        updated = next(p for p in (await self.detail(trip_id))['participants'] if p['id'] == person['id'])
        self.assertEqual(updated['paid_minor'], 5000)
        await self.assert_http(409, trips.update_participant(trip_id, person['id'], trips.ParticipantInput(expected_version=person['version'], paid_minor=0), self.db, self.context))
        await self.patch(trip_id, updated, payment_exempt=True, exemption_reason='إعفاء إداري')
        updated = next(p for p in (await self.detail(trip_id))['participants'] if p['id'] == person['id'])
        self.assertTrue(updated['payment_exempt'])
        self.assertEqual(updated['paid_minor'], 5000)  # Actual collections are preserved.
        await self.assert_http(422, trips.update_participant(trip_id, person['id'], trips.ParticipantInput(expected_version=updated['version'], paid_minor=16000), self.db, self.context))
        audit = self.session.scalars(select(AuditLog).where(AuditLog.action == 'trip.participant_updated')).all()
        self.assertEqual(json.loads(audit[-1].details)['changes']['exemption_reason'], 'إعفاء إداري')

    async def test_new_round_resets_every_check_and_locks_previous_round(self):
        trip_id = await self.create()
        people = await self.roster(trip_id)
        first = await self.start(trip_id)
        await trips.mark_check(trip_id, first, people[0]['id'], trips.CheckInput(status='present', expected_version=1), self.db, self.context)
        second = await self.start(trip_id, 'قبل العودة')
        detail = await self.detail(trip_id)
        self.assertEqual(detail['selected_round_id'], second)
        self.assertEqual([check['status'] for check in detail['checks']], ['pending'] * 3)
        history = await self.detail(trip_id, first)
        self.assertTrue(history['rounds'][1]['closed_at'])
        self.assertEqual(sum(check['status'] == 'present' for check in history['checks']), 1)
        await self.assert_http(409, trips.mark_check(trip_id, first, people[1]['id'], trips.CheckInput(status='present', expected_version=1), self.db, self.context))

    async def test_stale_check_cannot_overwrite_another_organizer(self):
        trip_id = await self.create()
        person = (await self.roster(trip_id))[0]
        current = await self.start(trip_id)
        await trips.mark_check(trip_id, current, person['id'], trips.CheckInput(status='present', expected_version=1), self.db, self.context)
        await self.assert_http(409, trips.mark_check(trip_id, current, person['id'], trips.CheckInput(status='absent', expected_version=1), self.db, self.context))
        check = next(c for c in (await self.detail(trip_id))['checks'] if c['participant_id'] == person['id'])
        self.assertEqual(check['status'], 'present')

    async def test_group_assignment_preserves_historical_bus_and_updates_current_bus(self):
        trip_id = await self.create()
        people = await self.roster(trip_id)
        bus1 = await trips.add_group(trip_id, trips.GroupInput(name='أتوبيس ١'), self.db, self.context)
        bus2 = await trips.add_group(trip_id, trips.GroupInput(name='أتوبيس ٢'), self.db, self.context)
        await trips.assign_group(trip_id, trips.GroupAssignmentInput(group_id=bus1['id'], participants=[dict(id=p['id'], expected_version=p['version']) for p in people]), self.db, self.context)
        first = await self.start(trip_id)
        second = await self.start(trip_id)
        people = (await self.detail(trip_id))['participants']
        await trips.assign_group(trip_id, trips.GroupAssignmentInput(group_id=bus2['id'], participants=[dict(id=people[0]['id'], expected_version=people[0]['version'])]), self.db, self.context)
        old = await self.detail(trip_id, first)
        new = await self.detail(trip_id, second)
        self.assertEqual({c['group_id'] for c in old['checks']}, {bus1['id']})
        self.assertEqual(next(c for c in new['checks'] if c['participant_id'] == people[0]['id'])['group_id'], bus2['id'])

    async def test_guardians_are_optional_active_adults_and_do_not_auto_check_children(self):
        trip_id = await self.create()
        people = await self.roster(trip_id)
        adult = next(p for p in people if p['is_adult'])
        child = next(p for p in people if not p['is_adult'])
        await self.patch(trip_id, child, guardian_id=adult['id'])
        await self.assert_http(409, trips.update_participant(trip_id, adult['id'], trips.ParticipantInput(expected_version=adult['version'], active=False), self.db, self.context))
        await self.assert_http(422, trips.update_participant(trip_id, adult['id'], trips.ParticipantInput(expected_version=adult['version'], guardian_id=adult['id']), self.db, self.context))
        current = await self.start(trip_id)
        await trips.mark_check(trip_id, current, adult['id'], trips.CheckInput(status='present', expected_version=1), self.db, self.context)
        detail = await self.detail(trip_id)
        self.assertEqual(next(c for c in detail['checks'] if c['participant_id'] == child['id'])['status'], 'pending')
        child = next(p for p in detail['participants'] if p['id'] == child['id'])
        await self.patch(trip_id, child, guardian_id=None)
        self.assertIsNone(next(p for p in (await self.detail(trip_id))['participants'] if p['id'] == child['id'])['guardian_id'])

    async def test_reactivating_a_child_requires_an_active_responsible_adult(self):
        trip_id = await self.create()
        people = await self.roster(trip_id)
        adult = next(p for p in people if p['is_adult'])
        child = next(p for p in people if not p['is_adult'])
        await self.patch(trip_id, child, guardian_id=adult['id'], active=False)
        await self.patch(trip_id, adult, active=False)
        child = next(p for p in (await self.detail(trip_id))['participants'] if p['id'] == child['id'])
        await self.assert_http(422, trips.update_participant(trip_id, child['id'], trips.ParticipantInput(expected_version=child['version'], active=True), self.db, self.context))
        # An inactive participant can still have their payment/refund corrected.
        await self.patch(trip_id, child, paid_minor=0)
        child = next(p for p in (await self.detail(trip_id))['participants'] if p['id'] == child['id'])
        await self.patch(trip_id, child, active=True, guardian_id=None)

    async def test_foreign_groups_guardians_and_people_are_rejected(self):
        first = await self.create()
        second = await self.create()
        people = await self.roster(first)
        await self.roster(second)
        group = await trips.add_group(second, trips.GroupInput(name='Other bus'), self.db, self.context)
        other_adult = next(p for p in (await self.detail(second))['participants'] if p['is_adult'])
        await self.assert_http(404, trips.update_participant(first, people[0]['id'], trips.ParticipantInput(expected_version=people[0]['version'], group_id=group['id']), self.db, self.context))
        await self.assert_http(422, trips.update_participant(first, people[0]['id'], trips.ParticipantInput(expected_version=people[0]['version'], guardian_id=other_adult['id']), self.db, self.context))
        await self.assert_http(404, trips.assign_group(second, trips.GroupAssignmentInput(group_id=group['id'], participants=[dict(id=people[0]['id'], expected_version=people[0]['version'])]), self.db, self.context))

    async def test_cancellation_keeps_old_checks_and_payments_but_changes_current_expectation(self):
        trip_id = await self.create()
        person = (await self.roster(trip_id))[0]
        await self.patch(trip_id, person, paid_minor=15000)
        first = await self.start(trip_id)
        await self.start(trip_id)
        person = next(p for p in (await self.detail(trip_id))['participants'] if p['id'] == person['id'])
        await self.patch(trip_id, person, active=False)
        current = await self.detail(trip_id)
        self.assertEqual(len(current['checks']), 2)
        self.assertEqual(next(p for p in current['participants'] if p['id'] == person['id'])['paid_minor'], 15000)
        self.assertEqual(len((await self.detail(trip_id, first))['checks']), 3)

    async def test_late_added_people_are_pending_in_current_round(self):
        trip_id = await self.create()
        await trips.add_participants(trip_id, trips.RosterInput(student_ids=[1]), self.db, self.context)
        await self.start(trip_id)
        await trips.add_participants(trip_id, trips.RosterInput(student_ids=[2]), self.db, self.context)
        self.assertEqual([c['status'] for c in (await self.detail(trip_id))['checks']], ['pending', 'pending'])

    async def test_completed_trip_is_read_only_and_can_be_reopened(self):
        trip_id = await self.create()
        await self.roster(trip_id)
        await self.start(trip_id)
        detail = await self.detail(trip_id)
        await trips.trip_status(trip_id, trips.TripStatusInput(status='completed', expected_version=detail['trip']['version']), self.db, self.context)
        await self.assert_http(409, trips.add_participants(trip_id, trips.RosterInput(guests=[dict(name='Late')]), self.db, self.context))
        detail = await self.detail(trip_id)
        self.assertIsNotNone(detail['rounds'][0]['closed_at'])
        await trips.trip_status(trip_id, trips.TripStatusInput(status='planned', expected_version=detail['trip']['version']), self.db, self.context)
        await self.start(trip_id)

    async def test_every_route_requires_admin_and_sheikh_auditor_are_rejected(self):
        for route in trips.router.routes:
            dependency = python_inspect.signature(route.endpoint).parameters['context'].default
            self.assertIs(dependency.dependency, require_tenant_admin)
        for role in (UserRole.sheikh, UserRole.auditor):
            with self.assertRaises(HTTPException) as error:
                await require_tenant_admin(TenantContext(user=self.context.user, tahfiz=self.context.tahfiz, role=role))
            self.assertEqual(error.exception.status_code, 403)

    def test_validation_rejects_empty_names_invalid_times_and_duplicate_roster(self):
        for values in [dict(name=' ', date='2026-10-20'), dict(name='Trip', date='2026-10-20', departure_time='25:00')]:
            with self.assertRaises(ValidationError): trips.TripInput(**values)
        with self.assertRaises(ValidationError): trips.RosterInput(student_ids=[1, 1])
        with self.assertRaises(ValidationError): trips.ParticipantInput(expected_version=1, paid_minor=None)


class TripMigrationTests(unittest.TestCase):
    def test_upgrade_preserves_existing_data_and_matches_orm_and_downgrades(self):
        engine = create_engine('sqlite:///:memory:')
        trip_tables = {model.__tablename__ for model in (Trip, TripGroup, TripParticipant, TripRound, TripCheck)}
        Base.metadata.create_all(engine, tables=[table for table in Base.metadata.sorted_tables if table.name not in trip_tables])
        with engine.begin() as connection:
            connection.execute(Tahfiz.__table__.insert().values(id=1, name='Existing'))
            module = importlib.import_module('migrations.versions.20261018_32_trips')
            with Operations.context(MigrationContext.configure(connection)):
                module.upgrade(); module.upgrade()
                schema = inspect(connection)
                for model in (Trip, TripGroup, TripParticipant, TripRound, TripCheck):
                    self.assertEqual({c['name'] for c in schema.get_columns(model.__tablename__)}, set(model.__table__.columns.keys()))
                self.assertEqual(connection.scalar(select(Tahfiz.name)), 'Existing')
                module.downgrade()
                self.assertFalse(trip_tables & set(inspect(connection).get_table_names()))
        engine.dispose()
