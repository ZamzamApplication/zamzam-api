import json
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models import (SessionSchedule, SessionOccurrence, Session, Student, StudentCategory,
                        Attendance, QuranProgressEntry, AuditLog)
from app.routers.auth import TenantContext, require_tenant_admin
from app.schemas import SessionScheduleRequest, SkipOccurrenceRequest
from app.session_scheduler import generate_schedule, local_today, occurrence_dates, lock_schedule
from app.time import utcnow

router = APIRouter(prefix='/session-schedules', tags=['session-schedules'])


async def output(db, row):
    today = local_today(row)
    receipts = (await db.execute(select(SessionOccurrence).where(
        SessionOccurrence.schedule_id == row.id, SessionOccurrence.tahfiz_id == row.tahfiz_id,
        SessionOccurrence.date >= today, SessionOccurrence.date <= today + timedelta(days=7)
    ).order_by(SessionOccurrence.date))).scalars().all()
    upcoming = [{'date': receipt.date.isoformat(), 'session_id': receipt.session_id, 'status': receipt.status} for receipt in receipts]
    return dict(id=row.id, name=row.name, weekdays=json.loads(row.weekdays), start_date=row.start_date.isoformat(),
                end_date=row.end_date.isoformat() if row.end_date else None, timezone=row.timezone,
                membership_mode=row.membership_mode, member_ids=json.loads(row.member_ids),
                is_active=row.is_active, version=row.version, upcoming=upcoming)


async def validate_members(db, body, context):
    if body.is_active and body.membership_mode != 'all' and not context.tahfiz.multiple_sessions_per_day_enabled:
        raise HTTPException(422, 'اختيار الطلاب يتطلب تفعيل تعدد الحلقات اليومية')
    if body.membership_mode == 'all':
        return
    model = Student if body.membership_mode == 'students' else StudentCategory
    ids = set((await db.execute(select(model.id).where(model.tahfiz_id == context.tahfiz_id, model.id.in_(body.member_ids)))).scalars().all())
    if ids != set(body.member_ids):
        raise HTTPException(404, 'بعض الطلاب أو التصنيفات غير موجودة')


def apply(row, body):
    for field in ('name', 'start_date', 'end_date', 'timezone', 'membership_mode', 'is_active'):
        setattr(row, field, getattr(body, field))
    row.weekdays = json.dumps(sorted(body.weekdays))
    row.member_ids = json.dumps(body.member_ids)


def audit(db, context, row, action, details=''):
    db.add(AuditLog(actor_user_id=context.user.id, tahfiz_id=context.tahfiz_id,
                    action=f'schedule.{action}', details=f'schedule={row.id}; {details}'))


@router.get('')
async def list_schedules(db: AsyncSession = Depends(get_db), context: TenantContext = Depends(require_tenant_admin)):
    rows = (await db.execute(select(SessionSchedule).where(SessionSchedule.tahfiz_id == context.tahfiz_id).order_by(SessionSchedule.id))).scalars().all()
    return [await output(db, row) for row in rows]


@router.post('')
async def create_schedule(body: SessionScheduleRequest, db: AsyncSession = Depends(get_db), context: TenantContext = Depends(require_tenant_admin)):
    await validate_members(db, body, context)
    row = SessionSchedule(tahfiz_id=context.tahfiz_id, created_by_id=context.user.id)
    apply(row, body)
    db.add(row)
    await db.flush()
    audit(db, context, row, 'created')
    await generate_schedule(db, row)
    result = await output(db, row)
    await db.commit()
    return result


@router.put('/{schedule_id}')
async def update_schedule(schedule_id: int, body: SessionScheduleRequest, db: AsyncSession = Depends(get_db), context: TenantContext = Depends(require_tenant_admin)):
    row = await lock_schedule(db, schedule_id, context.tahfiz_id)
    if row is None:
        raise HTTPException(404, 'الجدول غير موجود')
    if body.expected_version != row.version:
        raise HTTPException(409, 'تغير الجدول. أعد تحميله قبل التعديل')
    await validate_members(db, body, context)
    apply(row, body)
    row.version += 1
    audit(db, context, row, 'updated')
    await db.flush()
    await generate_schedule(db, row)
    result = await output(db, row)
    await db.commit()
    return result


@router.post('/{schedule_id}/skip')
async def skip_occurrence(schedule_id: int, body: SkipOccurrenceRequest, db: AsyncSession = Depends(get_db), context: TenantContext = Depends(require_tenant_admin)):
    row = await lock_schedule(db, schedule_id, context.tahfiz_id)
    if row is None:
        raise HTTPException(404, 'الجدول غير موجود')
    if row.version != body.expected_version:
        raise HTTPException(409, 'تغير الجدول. أعد تحميله قبل التعديل')
    if body.date not in occurrence_dates(row, local_today(row)):
        raise HTTPException(422, 'اختر موعداً قادماً خلال الأسبوع')
    receipt = await db.scalar(select(SessionOccurrence).where(SessionOccurrence.schedule_id == row.id, SessionOccurrence.date == body.date))
    if receipt and receipt.status == 'created' and receipt.session_id:
        session = await db.scalar(select(Session).where(Session.id == receipt.session_id, Session.tahfiz_id == context.tahfiz_id).with_for_update())
        changed_attendance = await db.scalar(select(Attendance.id).where(Attendance.session_id == receipt.session_id, Attendance.revision > 1).limit(1))
        progress = await db.scalar(select(QuranProgressEntry.id).where(QuranProgressEntry.session_id == receipt.session_id).limit(1))
        if session and (session.is_confirmed or session.version or session.archived_at or changed_attendance or progress):
            raise HTTPException(409, 'لا يمكن تخطي حلقة بدأ تسجيلها. استخدم إدارة الحلقة')
        if session:
            session.archived_at = utcnow()
            session.version += 1
            audit(db, context, row, 'occurrence_archived', f'session={session.id}; date={body.date}')
    if receipt is None:
        receipt = SessionOccurrence(schedule_id=row.id, tahfiz_id=row.tahfiz_id, date=body.date)
        db.add(receipt)
    receipt.status = 'skipped'
    row.version += 1
    audit(db, context, row, 'skipped', f'date={body.date}')
    await db.flush()
    result = await output(db, row)
    await db.commit()
    return result
