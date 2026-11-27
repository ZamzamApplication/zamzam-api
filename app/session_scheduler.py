"""Database-backed weekly scheduling. Every occurrence is committed with its session."""
import asyncio
import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete as sa_delete, select, update
from app.database import async_session
from app.models import (ACTIVE_STUDENT_STATUSES, Attendance, QuranProgressEntry, SessionSchedule,
                        SessionOccurrence, Student, StudentCategoryMembership, Tahfiz, User, Session)
from app.routers.auth import TenantContext
from app.schemas import CreateSessionRequest
from app.routers.sessions import create_session_record
from app.time import utcnow

logger = logging.getLogger(__name__)


def local_today(schedule):
    return datetime.now(ZoneInfo(schedule.timezone)).date()


def occurrence_dates(schedule, today):
    # Recurring halaqat are generated on the day itself, never in advance.
    start = max(schedule.start_date, today)
    end = min(schedule.end_date or today, today)
    weekdays = json.loads(schedule.weekdays)
    while start <= end:
        if (start.weekday() + 1) % 7 in weekdays:
            yield start
        start += timedelta(days=1)


async def lock_schedule(db, schedule_id, tenant_id):
    # A write lock also works on SQLite, where SELECT FOR UPDATE is ignored.
    await db.execute(update(SessionSchedule).where(
        SessionSchedule.id == schedule_id, SessionSchedule.tahfiz_id == tenant_id
    ).values(version=SessionSchedule.version).execution_options(synchronize_session=False))
    return await db.scalar(select(SessionSchedule).where(
        SessionSchedule.id == schedule_id, SessionSchedule.tahfiz_id == tenant_id
    ).execution_options(populate_existing=True))


async def prune_future_occurrences(db, row, today):
    """Remove sessions generated ahead of their day by the old lookahead window."""
    receipts = (await db.execute(select(SessionOccurrence).where(
        SessionOccurrence.schedule_id == row.id, SessionOccurrence.tahfiz_id == row.tahfiz_id,
        SessionOccurrence.date > today, SessionOccurrence.status == 'created',
        SessionOccurrence.session_id.is_not(None)))).scalars().all()
    for receipt in receipts:
        session = await db.scalar(select(Session).where(
            Session.id == receipt.session_id, Session.tahfiz_id == row.tahfiz_id).with_for_update())
        if session is None:
            await db.execute(sa_delete(SessionOccurrence).where(SessionOccurrence.id == receipt.id))
            continue
        changed_attendance = await db.scalar(select(Attendance.id).where(
            Attendance.session_id == session.id, Attendance.revision > 1).limit(1))
        progress = await db.scalar(select(QuranProgressEntry.id).where(
            QuranProgressEntry.session_id == session.id).limit(1))
        if session.is_confirmed or session.version or session.archived_at or changed_attendance or progress:
            continue  # Preserve sessions the center already touched.
        session.archived_at = utcnow()
        session.version += 1
        await db.execute(sa_delete(SessionOccurrence).where(SessionOccurrence.id == receipt.id))


async def generate_schedule(db, row, today=None):
    today = today or local_today(row)
    await prune_future_occurrences(db, row, today)
    if not row.is_active:
        return
    tahfiz = await db.scalar(select(Tahfiz).where(Tahfiz.id == row.tahfiz_id))
    if row.membership_mode != 'all' and not tahfiz.multiple_sessions_per_day_enabled:
        # Never broaden a selected roster if the center disables multiple sessions.
        return
    creator = await db.scalar(select(User).where(User.id == row.created_by_id))
    context = TenantContext(user=creator, tahfiz=tahfiz)
    for day in occurrence_dates(row, today):
        exists = await db.scalar(select(SessionOccurrence.id).where(
            SessionOccurrence.schedule_id == row.id, SessionOccurrence.date == day))
        if exists:
            continue
        if not tahfiz.multiple_sessions_per_day_enabled:
            duplicate = await db.scalar(select(Session.id).where(Session.tahfiz_id == row.tahfiz_id, Session.date == day))
            if duplicate:
                db.add(SessionOccurrence(schedule_id=row.id, tahfiz_id=row.tahfiz_id, date=day, status='conflict'))
                continue
        ids = None
        if tahfiz.multiple_sessions_per_day_enabled:
            query = select(Student.id).where(Student.tahfiz_id == row.tahfiz_id, Student.status.in_(ACTIVE_STUDENT_STATUSES))
            if row.membership_mode == 'students':
                query = query.where(Student.id.in_(json.loads(row.member_ids)))
            elif row.membership_mode == 'categories':
                query = query.where(Student.id.in_(select(StudentCategoryMembership.student_id).where(
                    StudentCategoryMembership.tahfiz_id == row.tahfiz_id,
                    StudentCategoryMembership.category_id.in_(json.loads(row.member_ids)))))
            ids = list((await db.execute(query)).scalars().all())
            if not ids:
                continue  # Retry if active students become available later.
        result = await create_session_record(CreateSessionRequest(session_date=day, name=row.name, student_ids=ids), db, context, commit=False)
        db.add(SessionOccurrence(schedule_id=row.id, tahfiz_id=row.tahfiz_id, date=day, session_id=result['id'], status='created'))
        await db.flush()


async def scheduler_tick():
    async with async_session() as db:
        ids = (await db.execute(select(SessionSchedule.id, SessionSchedule.tahfiz_id))).all()
    for schedule_id, tenant_id in ids:
        try:
            async with async_session() as db:
                row = await lock_schedule(db, schedule_id, tenant_id)
                if row:
                    await generate_schedule(db, row)
                await db.commit()
        except Exception:
            logger.exception('Unable to generate weekly schedule %s', schedule_id)


async def schedule_loop():
    while True:
        try:
            await scheduler_tick()
        except Exception:
            logger.exception('Weekly scheduler failed; retrying next minute')
        await asyncio.sleep(60)
