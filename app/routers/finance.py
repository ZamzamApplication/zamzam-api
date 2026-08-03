from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AuditLog, Expense, StudentSubscription, expense_category_options
from app.routers.auth import TenantContext, require_tenant_admin
from app.routers.subscriptions import ensure_current_subscription_records, monthly_period
from app.schemas import ExpenseRequest
from app.time import utcnow


router = APIRouter(prefix="/finance", tags=["finance"])
PAYMENT_METHODS = ("cash", "bank_transfer", "mobile_wallet", "other")


def validate_period(period: date | None, context: TenantContext) -> tuple[date, date]:
    if period is None:
        return monthly_period(date.today(), context.tahfiz.month_start_day)
    start, end = monthly_period(period, context.tahfiz.month_start_day)
    if period != start:
        raise HTTPException(status_code=400, detail={"code": "invalid_finance_period"})
    return start, end


def category_map(context: TenantContext) -> dict[str, dict]:
    return {category["id"]: category for category in expense_category_options(context.tahfiz)}


def serialize_expense(expense: Expense, context: TenantContext) -> dict:
    category = category_map(context).get(expense.category_id)
    return {
        "id": expense.id,
        "name": expense.name,
        "category_id": expense.category_id,
        "category_label": category["label"] if category else expense.category_label_snapshot,
        "amount_minor": expense.amount_minor,
        "currency": expense.currency,
        "expense_date": expense.expense_date.isoformat(),
        "payment_method": expense.payment_method,
        "note": expense.note,
        "created_at": expense.created_at.isoformat(),
        "updated_at": expense.updated_at.isoformat(),
    }


async def tenant_expense(db: AsyncSession, context: TenantContext, expense_id: int) -> Expense:
    expense = (await db.execute(select(Expense).where(
        Expense.id == expense_id,
        Expense.tahfiz_id == context.tahfiz_id,
        Expense.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if expense is None:
        raise HTTPException(status_code=404, detail={"code": "expense_not_found"})
    return expense


def expense_filters(
    context: TenantContext,
    start: date,
    end: date,
    category_id: str | None,
    payment_method: str | None,
    search: str | None,
):
    conditions = [
        Expense.tahfiz_id == context.tahfiz_id,
        Expense.deleted_at.is_(None),
        Expense.expense_date >= start,
        Expense.expense_date <= end,
    ]
    if category_id:
        conditions.append(Expense.category_id == category_id)
    if payment_method:
        if payment_method not in PAYMENT_METHODS:
            raise HTTPException(status_code=400, detail={"code": "invalid_payment_method"})
        conditions.append(Expense.payment_method == payment_method)
    term = search.strip() if search else ""
    if term:
        like = f"%{term}%"
        conditions.append(or_(Expense.name.ilike(like), Expense.note.ilike(like)))
    return conditions


@router.get("/overview")
async def overview(
    period: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    start, end = validate_period(period, context)
    current_start, _ = monthly_period(date.today(), context.tahfiz.month_start_day)
    if start == current_start and context.tahfiz.subscriptions_enabled:
        await ensure_current_subscription_records(db, context)
        await db.commit()

    subscription_rows = (await db.execute(select(
        StudentSubscription.amount_due_minor,
        StudentSubscription.is_paid,
    ).where(
        StudentSubscription.tahfiz_id == context.tahfiz_id,
        StudentSubscription.period_start == start,
    ))).all()
    expected = sum(row.amount_due_minor for row in subscription_rows)
    collected_for_bills = sum(row.amount_due_minor for row in subscription_rows if row.is_paid)

    income_rows = (await db.execute(select(
        StudentSubscription.payment_method,
        func.coalesce(func.sum(StudentSubscription.amount_due_minor), 0),
    ).where(
        StudentSubscription.tahfiz_id == context.tahfiz_id,
        StudentSubscription.is_paid.is_(True),
        StudentSubscription.payment_date >= start,
        StudentSubscription.payment_date <= end,
    ).group_by(StudentSubscription.payment_method))).all()
    expense_rows = (await db.execute(select(
        Expense.payment_method,
        func.coalesce(func.sum(Expense.amount_minor), 0),
    ).where(
        Expense.tahfiz_id == context.tahfiz_id,
        Expense.deleted_at.is_(None),
        Expense.expense_date >= start,
        Expense.expense_date <= end,
    ).group_by(Expense.payment_method))).all()
    income_by_method = {method or "other": int(amount) for method, amount in income_rows}
    expense_by_method = {method: int(amount) for method, amount in expense_rows}
    methods = [
        {
            "method": method,
            "income_minor": income_by_method.get(method, 0),
            "expenses_minor": expense_by_method.get(method, 0),
            "net_minor": income_by_method.get(method, 0) - expense_by_method.get(method, 0),
        }
        for method in PAYMENT_METHODS
    ]
    cash_collected = sum(item["income_minor"] for item in methods)
    expenses = sum(item["expenses_minor"] for item in methods)
    return {
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "currency": context.tahfiz.subscription_currency,
        "cash_collected_minor": cash_collected,
        "expenses_minor": expenses,
        "net_cash_minor": cash_collected - expenses,
        "expected_subscriptions_minor": expected,
        "collected_subscriptions_minor": collected_for_bills,
        "outstanding_subscriptions_minor": expected - collected_for_bills,
        "payment_methods": methods,
    }


@router.get("/expenses")
async def list_expenses(
    period: date | None = Query(default=None),
    category_id: str | None = Query(default=None, max_length=80),
    payment_method: str | None = Query(default=None),
    search: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    start, end = validate_period(period, context)
    filters = expense_filters(context, start, end, category_id, payment_method, search)
    total = int(await db.scalar(select(func.count()).select_from(Expense).where(*filters)) or 0)
    rows = list((await db.execute(
        select(Expense).where(*filters)
        .order_by(Expense.expense_date.desc(), Expense.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all())
    total_minor = int(await db.scalar(select(func.coalesce(func.sum(Expense.amount_minor), 0)).where(*filters)) or 0)
    return {
        "items": [serialize_expense(row, context) for row in rows],
        "total": total,
        "total_minor": total_minor,
        "page": page,
        "page_size": page_size,
    }


@router.get("/expenses/export")
async def export_expenses(
    period: date | None = Query(default=None),
    category_id: str | None = Query(default=None, max_length=80),
    payment_method: str | None = Query(default=None),
    search: str | None = Query(default=None, max_length=100),
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    start, end = validate_period(period, context)
    rows = list((await db.execute(
        select(Expense).where(*expense_filters(context, start, end, category_id, payment_method, search))
        .order_by(Expense.expense_date, Expense.id)
    )).scalars().all())
    return [serialize_expense(row, context) for row in rows]


def validated_category(context: TenantContext, category_id: str, *, allow_disabled: bool = False) -> dict:
    category = category_map(context).get(category_id)
    if category is None or (not allow_disabled and not category["enabled"]):
        raise HTTPException(status_code=400, detail={"code": "invalid_expense_category"})
    return category


@router.post("/expenses", status_code=201)
async def create_expense(
    body: ExpenseRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    if body.expense_date > date.today():
        raise HTTPException(status_code=400, detail={"code": "future_expense_date"})
    category = validated_category(context, body.category_id)
    expense = Expense(
        tahfiz_id=context.tahfiz_id,
        name=body.name,
        category_id=body.category_id,
        category_label_snapshot=category["label"],
        amount_minor=body.amount_minor,
        currency=context.tahfiz.subscription_currency,
        expense_date=body.expense_date,
        payment_method=body.payment_method,
        note=body.note,
        created_by_id=context.user.id,
        updated_by_id=context.user.id,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(expense)
    await db.flush()
    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz_id,
        action="finance.expense_created",
        details=f"expense={expense.id}; amount={expense.amount_minor}; method={expense.payment_method}",
    ))
    await db.commit()
    await db.refresh(expense)
    return serialize_expense(expense, context)


@router.patch("/expenses/{expense_id}")
async def update_expense(
    expense_id: int,
    body: ExpenseRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    expense = await tenant_expense(db, context, expense_id)
    if body.expense_date > date.today():
        raise HTTPException(status_code=400, detail={"code": "future_expense_date"})
    category = validated_category(
        context,
        body.category_id,
        allow_disabled=body.category_id == expense.category_id,
    )
    previous = f"name={expense.name}; amount={expense.amount_minor}; date={expense.expense_date}; method={expense.payment_method}; category={expense.category_id}"
    expense.name = body.name
    expense.category_id = body.category_id
    expense.category_label_snapshot = category["label"]
    expense.amount_minor = body.amount_minor
    expense.expense_date = body.expense_date
    expense.payment_method = body.payment_method
    expense.note = body.note
    expense.updated_by_id = context.user.id
    expense.updated_at = utcnow()
    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz_id,
        action="finance.expense_updated",
        details=f"expense={expense.id}; from=({previous}); to_amount={expense.amount_minor}; to_date={expense.expense_date}; to_method={expense.payment_method}; to_category={expense.category_id}",
    ))
    await db.commit()
    await db.refresh(expense)
    return serialize_expense(expense, context)


@router.delete("/expenses/{expense_id}", status_code=204)
async def delete_expense(
    expense_id: int,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    expense = await tenant_expense(db, context, expense_id)
    result = await db.execute(update(Expense).where(
        Expense.id == expense.id,
        Expense.tahfiz_id == context.tahfiz_id,
        Expense.deleted_at.is_(None),
    ).values(deleted_at=utcnow(), deleted_by_id=context.user.id, updated_at=utcnow()))
    if result.rowcount != 1:
        await db.rollback()
        raise HTTPException(status_code=409, detail={"code": "expense_already_deleted"})
    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz_id,
        action="finance.expense_deleted",
        details=f"expense={expense.id}; amount={expense.amount_minor}",
    ))
    await db.commit()
    return Response(status_code=204)
