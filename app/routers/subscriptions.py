from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AuditLog, Expense, Sheikh, Student, StudentStatus, StudentSubscription, User
from app.routers.auth import TenantContext, require_tenant_admin
from app.schemas import (
    BulkSubscriptionAmountRequest,
    BulkSubscriptionPaymentRequest,
    StudentSubscriptionOverrideRequest,
    SubscriptionAmountRequest,
    SubscriptionPaymentRequest,
    SubscriptionSettingsRequest,
)
from app.time import utcnow


router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


def monthly_period(day: date, month_start_day: int) -> tuple[date, date]:
    if day.day >= month_start_day:
        start = date(day.year, day.month, month_start_day)
    else:
        previous = date(day.year, day.month, 1) - timedelta(days=1)
        start = date(previous.year, previous.month, month_start_day)
    next_start = (
        date(start.year + 1, 1, month_start_day)
        if start.month == 12
        else date(start.year, start.month + 1, month_start_day)
    )
    return start, next_start - timedelta(days=1)


def serialize_record(
    record: StudentSubscription,
    student_fee_override_minor: int | None = None,
) -> dict:
    return {
        "id": record.id,
        "student_id": record.student_id,
        "student_name": record.student_name,
        "student_code": record.student_custom_id,
        "student_phone": record.student_phone,
        "sheikh_id": record.sheikh_id_snapshot,
        "sheikh_name": record.sheikh_name,
        "period_start": record.period_start.isoformat(),
        "period_end": record.period_end.isoformat(),
        "fee_minor": record.amount_due_minor,
        "student_fee_override_minor": student_fee_override_minor,
        "currency": record.currency,
        "is_paid": record.is_paid,
        "payment_date": record.payment_date.isoformat() if record.payment_date else None,
        "payment_method": record.payment_method,
        "payment_note": record.payment_note,
        "receipt_number": record.receipt_number,
    }


async def serialize_records(
    db: AsyncSession,
    records: list[StudentSubscription],
) -> list[dict]:
    student_ids = {record.student_id for record in records if record.student_id is not None}
    overrides = {}
    if student_ids:
        overrides = dict((await db.execute(
            select(Student.id, Student.subscription_fee_override_minor).where(Student.id.in_(student_ids))
        )).all())
    return [serialize_record(record, overrides.get(record.student_id)) for record in records]


def serialize_settings(context: TenantContext) -> dict:
    start, end = monthly_period(date.today(), context.tahfiz.month_start_day)
    return {
        "enabled": context.tahfiz.subscriptions_enabled,
        "default_monthly_fee_minor": context.tahfiz.subscription_default_fee_minor,
        "currency": context.tahfiz.subscription_currency,
        "month_start_day": context.tahfiz.month_start_day,
        "current_period_start": start.isoformat(),
        "current_period_end": end.isoformat(),
    }


async def ensure_current_subscription_records(
    db: AsyncSession,
    context: TenantContext,
) -> int:
    if not context.tahfiz.subscriptions_enabled:
        return 0
    today = date.today()
    period_start, period_end = monthly_period(today, context.tahfiz.month_start_day)
    rows = (await db.execute(
        select(Student, Sheikh)
        .outerjoin(Sheikh, Sheikh.id == Student.sheikh_id)
        .where(
            Student.tahfiz_id == context.tahfiz_id,
            Student.status == StudentStatus.enrolled,
            or_(Student.registration_date.is_(None), Student.registration_date <= today),
        )
        .order_by(Student.id)
    )).all()
    existing = set((await db.execute(
        select(StudentSubscription.student_snapshot_id).where(
            StudentSubscription.tahfiz_id == context.tahfiz_id,
            StudentSubscription.period_start == period_start,
        )
    )).scalars().all())
    generated = 0
    for student, sheikh in rows:
        if student.id in existing:
            continue
        amount = (
            student.subscription_fee_override_minor
            if student.subscription_fee_override_minor is not None
            else context.tahfiz.subscription_default_fee_minor
        )
        record = StudentSubscription(
            tahfiz_id=context.tahfiz_id,
            student_id=student.id,
            student_snapshot_id=student.id,
            student_name=student.name,
            student_custom_id=student.student_id,
            student_phone=student.phone,
            sheikh_id_snapshot=student.sheikh_id,
            sheikh_name=sheikh.name if sheikh else None,
            period_start=period_start,
            period_end=period_end,
            amount_due_minor=amount,
            currency=context.tahfiz.subscription_currency,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        try:
            async with db.begin_nested():
                db.add(record)
                await db.flush()
        except IntegrityError:
            continue
        generated += 1
    if generated:
        db.add(AuditLog(
            actor_user_id=context.user.id,
            tahfiz_id=context.tahfiz_id,
            action="subscriptions.period_generated",
            details=f"period={period_start.isoformat()}; generated={generated}",
        ))
    return generated


async def tenant_record(
    db: AsyncSession,
    context: TenantContext,
    record_id: int,
) -> StudentSubscription:
    record = (await db.execute(
        select(StudentSubscription)
        .join(Student, Student.id == StudentSubscription.student_id)
        .where(
        StudentSubscription.id == record_id,
        StudentSubscription.tahfiz_id == context.tahfiz_id,
        Student.tahfiz_id == context.tahfiz_id,
        Student.status == StudentStatus.enrolled,
    ))).scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Subscription record not found")
    return record


def filtered_statement(
    context: TenantContext,
    period: date,
    paid: bool | None,
    sheikh_id: int | None,
    student_id: int | None,
    search: str | None,
):
    statement = select(StudentSubscription).join(
        Student, Student.id == StudentSubscription.student_id
    ).where(
        StudentSubscription.tahfiz_id == context.tahfiz_id,
        StudentSubscription.period_start == period,
        Student.tahfiz_id == context.tahfiz_id,
        Student.status == StudentStatus.enrolled,
    )
    if paid is True:
        statement = statement.where(StudentSubscription.is_paid.is_(True))
    elif paid is False:
        statement = statement.where(
            StudentSubscription.is_paid.is_(False),
            StudentSubscription.amount_due_minor > 0,
        )
    if sheikh_id is not None:
        statement = statement.where(StudentSubscription.sheikh_id_snapshot == sheikh_id)
    if student_id is not None:
        statement = statement.where(StudentSubscription.student_snapshot_id == student_id)
    term = search.strip() if search else ""
    if term:
        like = f"%{term}%"
        statement = statement.where(or_(
            StudentSubscription.student_name.ilike(like),
            StudentSubscription.student_custom_id.ilike(like),
            StudentSubscription.student_phone.ilike(like),
            StudentSubscription.sheikh_name.ilike(like),
        ))
    return statement


def validate_period(period: date | None, context: TenantContext) -> tuple[date, date]:
    if period is None:
        return monthly_period(date.today(), context.tahfiz.month_start_day)
    start, end = monthly_period(period, context.tahfiz.month_start_day)
    if start != period:
        raise HTTPException(status_code=400, detail={
            "code": "invalid_subscription_period",
            "message": "Period must start on the configured Tahfiz month-start day",
        })
    return start, end


@router.get("/settings")
async def get_settings(context: TenantContext = Depends(require_tenant_admin)):
    return serialize_settings(context)


@router.put("/settings")
async def update_settings(
    body: SubscriptionSettingsRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    tahfiz = context.tahfiz
    next_fee = body.default_monthly_fee_minor
    if body.enabled is True and not tahfiz.subscriptions_enabled:
        effective_fee = next_fee if next_fee is not None else tahfiz.subscription_default_fee_minor
        if effective_fee <= 0:
            raise HTTPException(status_code=400, detail={
                "code": "subscription_default_fee_required",
                "message": "A positive default monthly fee is required before activation",
            })
    if body.currency is not None and body.currency.upper() != tahfiz.subscription_currency:
        existing = await db.scalar(select(func.count()).select_from(StudentSubscription).where(
            StudentSubscription.tahfiz_id == context.tahfiz_id,
        ))
        expenses = await db.scalar(select(func.count()).select_from(Expense).where(
            Expense.tahfiz_id == context.tahfiz_id,
        ))
        if existing or expenses:
            raise HTTPException(status_code=409, detail={
                "code": "subscription_currency_locked",
                "message": "Currency cannot change after subscription records exist",
            })
    changed: list[str] = []
    if next_fee is not None and next_fee != tahfiz.subscription_default_fee_minor:
        tahfiz.subscription_default_fee_minor = next_fee
        changed.append("default_monthly_fee_minor")
    if body.currency is not None:
        currency = body.currency.upper()
        if currency != tahfiz.subscription_currency:
            tahfiz.subscription_currency = currency
            changed.append("currency")
    if body.enabled is not None and body.enabled != tahfiz.subscriptions_enabled:
        tahfiz.subscriptions_enabled = body.enabled
        changed.append("enabled")
    if body.enabled is True:
        await ensure_current_subscription_records(db, context)
    if changed:
        db.add(AuditLog(
            actor_user_id=context.user.id,
            tahfiz_id=context.tahfiz_id,
            action="subscriptions.settings_updated",
            details=f"fields={','.join(changed)}",
        ))
    await db.commit()
    return serialize_settings(context)


@router.put("/students/{student_id}/fee")
async def update_student_fee(
    student_id: int,
    body: StudentSubscriptionOverrideRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    student = (await db.execute(select(Student).where(
        Student.id == student_id,
        Student.tahfiz_id == context.tahfiz_id,
    ))).scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    if student.status != StudentStatus.enrolled:
        raise HTTPException(status_code=409, detail={"code": "student_not_enrolled"})
    previous = student.subscription_fee_override_minor
    student.subscription_fee_override_minor = body.monthly_fee_minor
    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz_id,
        action="subscriptions.student_fee_updated",
        details=f"student={student.id}; from={previous}; to={body.monthly_fee_minor}",
    ))
    await db.commit()
    effective = body.monthly_fee_minor if body.monthly_fee_minor is not None else context.tahfiz.subscription_default_fee_minor
    return {"student_id": student.id, "monthly_fee_minor": body.monthly_fee_minor, "effective_fee_minor": effective}


@router.get("/students/{student_id}/current")
async def student_current(
    student_id: int,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    student = (await db.execute(select(Student).where(
        Student.id == student_id,
        Student.tahfiz_id == context.tahfiz_id,
    ))).scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    if student.status != StudentStatus.enrolled:
        raise HTTPException(status_code=409, detail={"code": "student_not_enrolled"})
    if context.tahfiz.subscriptions_enabled:
        await ensure_current_subscription_records(db, context)
        await db.commit()
    start, _ = monthly_period(date.today(), context.tahfiz.month_start_day)
    record = (await db.execute(select(StudentSubscription).where(
        StudentSubscription.tahfiz_id == context.tahfiz_id,
        StudentSubscription.student_snapshot_id == student.id,
        StudentSubscription.period_start == start,
    ))).scalar_one_or_none()
    effective = student.subscription_fee_override_minor
    if effective is None:
        effective = context.tahfiz.subscription_default_fee_minor
    return {
        "enabled": context.tahfiz.subscriptions_enabled,
        "effective_fee_minor": effective,
        "currency": context.tahfiz.subscription_currency,
        "record": serialize_record(record, student.subscription_fee_override_minor) if record else None,
    }


@router.get("/months")
async def list_months(
    period: date | None = Query(default=None),
    paid: bool | None = Query(default=None),
    sheikh_id: int | None = Query(default=None),
    student_id: int | None = Query(default=None),
    search: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    start, _ = validate_period(period, context)
    current_start, _ = monthly_period(date.today(), context.tahfiz.month_start_day)
    if start == current_start and context.tahfiz.subscriptions_enabled:
        await ensure_current_subscription_records(db, context)
        await db.commit()
    statement = filtered_statement(context, start, paid, sheikh_id, student_id, search)
    rows = list((await db.execute(statement.order_by(StudentSubscription.student_name, StudentSubscription.id))).scalars().all())
    expected = sum(row.amount_due_minor for row in rows)
    collected = sum(row.amount_due_minor for row in rows if row.is_paid)
    summary = {
        "expected_minor": expected,
        "collected_minor": collected,
        "unpaid_minor": expected - collected,
        "paid_count": sum(row.is_paid for row in rows),
        "unpaid_count": sum(not row.is_paid and row.amount_due_minor > 0 for row in rows),
    }
    offset = (page - 1) * page_size
    return {
        "items": await serialize_records(db, rows[offset:offset + page_size]),
        "total": len(rows),
        "page": page,
        "page_size": page_size,
        "summary": summary,
    }


@router.post("/months/bulk-mark-paid")
async def bulk_mark_paid(
    body: BulkSubscriptionPaymentRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    if body.payment_date > date.today():
        raise HTTPException(status_code=400, detail={"code": "future_payment_date"})
    rows = list((await db.execute(
        select(StudentSubscription)
        .join(Student, Student.id == StudentSubscription.student_id)
        .where(
        StudentSubscription.tahfiz_id == context.tahfiz_id,
        StudentSubscription.id.in_(body.record_ids),
        Student.tahfiz_id == context.tahfiz_id,
        Student.status == StudentStatus.enrolled,
    ).order_by(StudentSubscription.id))).scalars().all())
    if {row.id for row in rows} != set(body.record_ids):
        raise HTTPException(status_code=404, detail={"code": "subscription_record_not_found"})
    if any(row.is_paid or row.amount_due_minor == 0 for row in rows):
        raise HTTPException(status_code=409, detail={"code": "subscription_batch_stale"})
    for row in rows:
        receipt = row.receipt_number or f"ZM-{context.tahfiz_id}-{row.period_start:%Y%m}-{row.id}"
        result = await db.execute(update(StudentSubscription).where(
            StudentSubscription.id == row.id,
            StudentSubscription.tahfiz_id == context.tahfiz_id,
            StudentSubscription.is_paid.is_(False),
            StudentSubscription.amount_due_minor > 0,
        ).values(
            is_paid=True,
            payment_date=body.payment_date,
            paid_by_id=context.user.id,
            payment_method=body.payment_method,
            payment_note=body.payment_note,
            receipt_number=receipt,
            updated_at=utcnow(),
        ))
        if result.rowcount != 1:
            await db.rollback()
            raise HTTPException(status_code=409, detail={"code": "subscription_batch_stale"})
    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz_id,
        action="subscriptions.bulk_marked_paid",
        details=f"records={','.join(str(item) for item in body.record_ids)}; method={body.payment_method}",
    ))
    await db.commit()
    return {"updated": len(rows)}


@router.patch("/months/bulk-correct-amount")
async def bulk_correct_amount(
    body: BulkSubscriptionAmountRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    period_start, _ = validate_period(body.period, context)
    matching_ids = list((await db.execute(
        select(StudentSubscription.id)
        .outerjoin(Student, Student.id == StudentSubscription.student_id)
        .where(
            StudentSubscription.tahfiz_id == context.tahfiz_id,
            StudentSubscription.period_start == period_start,
            StudentSubscription.is_paid.is_(False),
            StudentSubscription.amount_due_minor == body.from_fee_minor,
            Student.status == StudentStatus.enrolled,
            or_(Student.id.is_(None), Student.subscription_fee_override_minor.is_(None)),
        )
        .order_by(StudentSubscription.id)
    )).scalars().all())
    result = await db.execute(update(StudentSubscription).where(
        StudentSubscription.id.in_(matching_ids),
        StudentSubscription.tahfiz_id == context.tahfiz_id,
        StudentSubscription.period_start == period_start,
        StudentSubscription.is_paid.is_(False),
        StudentSubscription.amount_due_minor == body.from_fee_minor,
    ).values(amount_due_minor=body.to_fee_minor, updated_at=utcnow())) if matching_ids else None
    updated = result.rowcount if result is not None else 0
    total_period = int(await db.scalar(select(func.count()).select_from(StudentSubscription).where(
        StudentSubscription.tahfiz_id == context.tahfiz_id,
        StudentSubscription.period_start == period_start,
    )) or 0)
    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz_id,
        action="subscriptions.bulk_amount_corrected",
        details=f"period={period_start}; from={body.from_fee_minor}; to={body.to_fee_minor}; updated={updated}",
    ))
    await db.commit()
    return {"updated": updated, "skipped": total_period - updated}


@router.patch("/months/{record_id}")
async def update_month_amount(
    record_id: int,
    body: SubscriptionAmountRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    record = await tenant_record(db, context, record_id)
    if record.is_paid:
        raise HTTPException(status_code=409, detail={"code": "paid_subscription_locked"})
    if body.update_future and record.student_id is None:
        raise HTTPException(status_code=409, detail={"code": "subscription_student_deleted"})
    previous = record.amount_due_minor
    result = await db.execute(update(StudentSubscription).where(
        StudentSubscription.id == record.id,
        StudentSubscription.tahfiz_id == context.tahfiz_id,
        StudentSubscription.is_paid.is_(False),
    ).values(amount_due_minor=body.fee_minor, updated_at=utcnow()))
    if result.rowcount != 1:
        await db.rollback()
        raise HTTPException(status_code=409, detail={"code": "paid_subscription_locked"})
    if body.update_future:
        student = (await db.execute(select(Student).where(
            Student.id == record.student_id,
            Student.tahfiz_id == context.tahfiz_id,
        ))).scalar_one_or_none()
        if not student:
            raise HTTPException(status_code=409, detail={"code": "subscription_student_deleted"})
        student.subscription_fee_override_minor = body.future_monthly_fee_minor
    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz_id,
        action="subscriptions.amount_corrected",
        details=f"record={record.id}; from={previous}; to={body.fee_minor}; update_future={body.update_future}",
    ))
    await db.commit()
    updated_record = await tenant_record(db, context, record_id)
    override = None
    if updated_record.student_id is not None:
        override = await db.scalar(select(Student.subscription_fee_override_minor).where(
            Student.id == updated_record.student_id,
            Student.tahfiz_id == context.tahfiz_id,
        ))
    return serialize_record(updated_record, override)


@router.post("/months/{record_id}/mark-paid")
async def mark_paid(
    record_id: int,
    body: SubscriptionPaymentRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    if body.payment_date > date.today():
        raise HTTPException(status_code=400, detail={"code": "future_payment_date"})
    record = await tenant_record(db, context, record_id)
    if record.amount_due_minor == 0:
        raise HTTPException(status_code=400, detail={"code": "subscription_exempt"})
    if record.is_paid:
        raise HTTPException(status_code=409, detail={"code": "subscription_already_paid"})
    receipt = record.receipt_number or f"ZM-{context.tahfiz_id}-{record.period_start:%Y%m}-{record.id}"
    result = await db.execute(update(StudentSubscription).where(
        StudentSubscription.id == record.id,
        StudentSubscription.tahfiz_id == context.tahfiz_id,
        StudentSubscription.is_paid.is_(False),
    ).values(
        is_paid=True,
        payment_date=body.payment_date,
        paid_by_id=context.user.id,
        payment_method=body.payment_method,
        payment_note=body.payment_note,
        receipt_number=receipt,
        updated_at=utcnow(),
    ))
    if result.rowcount != 1:
        await db.rollback()
        raise HTTPException(status_code=409, detail={"code": "subscription_already_paid"})
    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz_id,
        action="subscriptions.marked_paid",
        details=f"record={record.id}; amount={record.amount_due_minor}; method={body.payment_method}; date={body.payment_date}",
    ))
    await db.commit()
    return serialize_record(await tenant_record(db, context, record_id))


@router.post("/months/{record_id}/mark-unpaid")
async def mark_unpaid(
    record_id: int,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    record = await tenant_record(db, context, record_id)
    if not record.is_paid:
        raise HTTPException(status_code=409, detail={"code": "subscription_already_unpaid"})
    result = await db.execute(update(StudentSubscription).where(
        StudentSubscription.id == record.id,
        StudentSubscription.tahfiz_id == context.tahfiz_id,
        StudentSubscription.is_paid.is_(True),
    ).values(
        is_paid=False,
        payment_date=None,
        paid_by_id=None,
        payment_method=None,
        payment_note=None,
        updated_at=utcnow(),
    ))
    if result.rowcount != 1:
        await db.rollback()
        raise HTTPException(status_code=409, detail={"code": "subscription_already_unpaid"})
    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz_id,
        action="subscriptions.marked_unpaid",
        details=f"record={record.id}; receipt={record.receipt_number}",
    ))
    await db.commit()
    return serialize_record(await tenant_record(db, context, record_id))


@router.get("/months/{record_id}/receipt")
async def get_receipt(
    record_id: int,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    record = await tenant_record(db, context, record_id)
    if not record.is_paid:
        raise HTTPException(status_code=409, detail={"code": "receipt_requires_payment"})
    username = await db.scalar(select(User.username).where(User.id == record.paid_by_id)) if record.paid_by_id else None
    return {
        **serialize_record(record),
        "tahfiz_name": context.tahfiz.name,
        "recorded_by_username": username,
    }


@router.get("/export")
async def export_records(
    period: date | None = Query(default=None),
    paid: bool | None = Query(default=None),
    sheikh_id: int | None = Query(default=None),
    student_id: int | None = Query(default=None),
    search: str | None = Query(default=None, max_length=100),
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    start, _ = validate_period(period, context)
    statement = filtered_statement(context, start, paid, sheikh_id, student_id, search)
    rows = list((await db.execute(statement.order_by(StudentSubscription.student_name, StudentSubscription.id))).scalars().all())
    return await serialize_records(db, rows)
