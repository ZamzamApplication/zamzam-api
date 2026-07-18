from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AuditLog, Tahfiz, TahfizStatus, User
from app.routers.auth import require_super_admin
from app.schemas import PlatformTahfizActionRequest

router = APIRouter(prefix="/platform", tags=["platform"])


def serialize_tahfiz(tahfiz: Tahfiz, owner_username: str | None = None) -> dict:
    return {
        "id": tahfiz.id,
        "name": tahfiz.name,
        "description": tahfiz.description,
        "contact_phone": tahfiz.contact_phone,
        "status": tahfiz.status.value,
        "status_reason": tahfiz.status_reason,
        "owner_user_id": tahfiz.owner_user_id,
        "owner_username": owner_username,
        "created_at": tahfiz.created_at.isoformat(),
        "approved_at": tahfiz.approved_at.isoformat() if tahfiz.approved_at else None,
    }


@router.get("/tahfiz")
async def list_tahfiz(
    status: TahfizStatus | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_super_admin),
):
    query = (
        select(Tahfiz, User.username)
        .outerjoin(User, User.id == Tahfiz.owner_user_id)
        .order_by(Tahfiz.created_at.desc())
    )
    if status:
        query = query.where(Tahfiz.status == status)
    rows = (await db.execute(query)).all()
    return [serialize_tahfiz(tahfiz, username) for tahfiz, username in rows]


async def set_status(
    tahfiz_id: int,
    next_status: TahfizStatus,
    action: str,
    body: PlatformTahfizActionRequest,
    admin: User,
    db: AsyncSession,
) -> dict:
    tahfiz = await db.get(Tahfiz, tahfiz_id)
    if not tahfiz:
        raise HTTPException(status_code=404, detail="Tahfiz not found")
    tahfiz.status = next_status
    tahfiz.status_reason = body.reason
    if next_status == TahfizStatus.active:
        tahfiz.approved_at = datetime.utcnow()
        tahfiz.approved_by_id = admin.id
    db.add(AuditLog(
        actor_user_id=admin.id,
        tahfiz_id=tahfiz.id,
        action=action,
        details=body.reason,
    ))
    await db.commit()
    return serialize_tahfiz(tahfiz)


@router.post("/tahfiz/{tahfiz_id}/approve")
async def approve_tahfiz(
    tahfiz_id: int,
    body: PlatformTahfizActionRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin),
):
    return await set_status(tahfiz_id, TahfizStatus.active, "tahfiz.approved", body, admin, db)


@router.post("/tahfiz/{tahfiz_id}/reject")
async def reject_tahfiz(
    tahfiz_id: int,
    body: PlatformTahfizActionRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin),
):
    if not body.reason:
        raise HTTPException(status_code=400, detail="Rejection reason is required")
    return await set_status(tahfiz_id, TahfizStatus.rejected, "tahfiz.rejected", body, admin, db)


@router.post("/tahfiz/{tahfiz_id}/suspend")
async def suspend_tahfiz(
    tahfiz_id: int,
    body: PlatformTahfizActionRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin),
):
    if not body.reason:
        raise HTTPException(status_code=400, detail="Suspension reason is required")
    return await set_status(tahfiz_id, TahfizStatus.suspended, "tahfiz.suspended", body, admin, db)


@router.post("/tahfiz/{tahfiz_id}/reactivate")
async def reactivate_tahfiz(
    tahfiz_id: int,
    body: PlatformTahfizActionRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin),
):
    return await set_status(tahfiz_id, TahfizStatus.active, "tahfiz.reactivated", body, admin, db)


@router.post("/tahfiz/{tahfiz_id}/support-access")
async def record_support_access(
    tahfiz_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin),
):
    tahfiz = await db.get(Tahfiz, tahfiz_id)
    if not tahfiz:
        raise HTTPException(status_code=404, detail="Tahfiz not found")
    db.add(AuditLog(
        actor_user_id=admin.id,
        tahfiz_id=tahfiz.id,
        action="tahfiz.support_access",
    ))
    await db.commit()
    return {"tahfiz_id": tahfiz.id, "name": tahfiz.name}
