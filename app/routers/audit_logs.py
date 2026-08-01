from datetime import date, datetime, time, timedelta
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AuditLog, User
from app.routers.auth import TenantContext, require_tenant_admin
from app.schemas import AuditLogPageOut


router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


def serialize_audit_log(log: AuditLog, actor_username: str) -> dict:
    return {
        "id": log.id,
        "actor_user_id": log.actor_user_id,
        "actor_username": actor_username,
        "action": log.action,
        "details": log.details,
        "created_at": log.created_at,
    }


@router.get("", response_model=AuditLogPageOut)
async def list_audit_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    action: str | None = Query(default=None, max_length=100),
    actor_user_id: int | None = Query(default=None, ge=1),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    query: str | None = Query(default=None, max_length=100),
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(status_code=400, detail={
            "code": "invalid_audit_date_range",
            "message": "The start date must be on or before the end date",
        })
    filters = [AuditLog.tahfiz_id == context.tahfiz_id]
    if action:
        filters.append(AuditLog.action == action.strip())
    if actor_user_id is not None:
        filters.append(AuditLog.actor_user_id == actor_user_id)
    if date_from is not None:
        filters.append(AuditLog.created_at >= datetime.combine(date_from, time.min))
    if date_to is not None:
        filters.append(AuditLog.created_at < datetime.combine(date_to + timedelta(days=1), time.min))
    if query and query.strip():
        needle = f"%{query.strip()}%"
        filters.append(or_(
            AuditLog.action.ilike(needle),
            AuditLog.details.ilike(needle),
            User.username.ilike(needle),
        ))

    total = int(await db.scalar(
        select(func.count(AuditLog.id)).join(User, User.id == AuditLog.actor_user_id).where(*filters)
    ) or 0)
    rows = (await db.execute(
        select(AuditLog, User.username)
        .join(User, User.id == AuditLog.actor_user_id)
        .where(*filters)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )).all()
    actions = list((await db.execute(
        select(AuditLog.action)
        .where(AuditLog.tahfiz_id == context.tahfiz_id)
        .distinct()
        .order_by(AuditLog.action)
    )).scalars().all())
    actor_rows = (await db.execute(
        select(User.id, User.username)
        .join(AuditLog, AuditLog.actor_user_id == User.id)
        .where(AuditLog.tahfiz_id == context.tahfiz_id)
        .distinct()
        .order_by(User.username)
    )).all()

    return {
        "items": [serialize_audit_log(log, username) for log, username in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, ceil(total / page_size)),
        "actions": actions,
        "actors": [{"id": user_id, "username": username} for user_id, username in actor_rows],
    }
