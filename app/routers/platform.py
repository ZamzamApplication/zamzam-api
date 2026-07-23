from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AuditLog, Sheikh, Tahfiz, TahfizStatus, User, UserRole, UserTahfizMembership
from app.routers.auth import require_super_admin
from app.schemas import PlatformTahfizActionRequest, UpsertUserTahfizMembershipRequest

router = APIRouter(prefix="/platform", tags=["platform"])


def serialize_membership(membership: UserTahfizMembership, tahfiz: Tahfiz) -> dict:
    return {
        "id": membership.id,
        "tahfiz_id": tahfiz.id,
        "tahfiz_name": tahfiz.name,
        "tahfiz_status": tahfiz.status.value,
        "role": membership.role.value,
        "sheikh_id": membership.sheikh_id,
        "is_active": membership.is_active,
    }


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


@router.get("/users")
async def list_platform_users(
    query: str | None = Query(default=None, max_length=100),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_super_admin),
):
    statement = (
        select(User)
        .where(User.role != UserRole.super_admin)
        .order_by(User.username)
        .limit(100)
    )
    if query and query.strip():
        statement = statement.where(User.username.ilike(f"%{query.strip()}%"))
    users = (await db.execute(statement)).scalars().all()
    user_ids = [user.id for user in users]
    rows = (await db.execute(
        select(UserTahfizMembership, Tahfiz)
        .join(Tahfiz, Tahfiz.id == UserTahfizMembership.tahfiz_id)
        .where(UserTahfizMembership.user_id.in_(user_ids))
        .order_by(Tahfiz.name)
    )).all() if user_ids else []
    memberships_by_user: dict[int, list[dict]] = {}
    for membership, tahfiz in rows:
        memberships_by_user.setdefault(membership.user_id, []).append(
            serialize_membership(membership, tahfiz)
        )
    return [
        {
            "id": user.id,
            "username": user.username,
            "is_active": user.is_active,
            "default_tahfiz_id": user.default_tahfiz_id or user.tahfiz_id,
            "memberships": memberships_by_user.get(user.id, []),
        }
        for user in users
    ]


async def validate_membership_input(
    body: UpsertUserTahfizMembershipRequest,
    db: AsyncSession,
) -> tuple[Tahfiz, UserRole]:
    if body.role not in (UserRole.admin.value, UserRole.sheikh.value):
        raise HTTPException(status_code=400, detail="Invalid tenant role")
    tahfiz = await db.get(Tahfiz, body.tahfiz_id)
    if not tahfiz:
        raise HTTPException(status_code=404, detail="Tahfiz not found")
    if body.sheikh_id is not None:
        sheikh = await db.scalar(select(Sheikh).where(
            Sheikh.id == body.sheikh_id,
            Sheikh.tahfiz_id == body.tahfiz_id,
        ))
        if not sheikh:
            raise HTTPException(status_code=404, detail="Sheikh not found in this Tahfiz")
    if body.role == UserRole.sheikh.value and body.sheikh_id is None:
        raise HTTPException(status_code=400, detail="A sheikh membership requires a sheikh")
    return tahfiz, UserRole(body.role)


@router.post("/users/{user_id}/memberships")
async def grant_user_membership(
    user_id: int,
    body: UpsertUserTahfizMembershipRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin),
):
    user = await db.get(User, user_id)
    if not user or user.role == UserRole.super_admin:
        raise HTTPException(status_code=404, detail="Tenant user not found")
    tahfiz, role = await validate_membership_input(body, db)
    membership = await db.scalar(select(UserTahfizMembership).where(
        UserTahfizMembership.user_id == user.id,
        UserTahfizMembership.tahfiz_id == tahfiz.id,
    ))
    action = "membership.updated" if membership else "membership.granted"
    if membership:
        membership.role = role
        membership.sheikh_id = body.sheikh_id
        membership.is_active = True
    else:
        membership = UserTahfizMembership(
            user_id=user.id,
            tahfiz_id=tahfiz.id,
            role=role,
            sheikh_id=body.sheikh_id,
            is_active=True,
            created_by_id=admin.id,
        )
        db.add(membership)
    if user.default_tahfiz_id is None:
        user.default_tahfiz_id = tahfiz.id
    user.is_active = True
    db.add(AuditLog(
        actor_user_id=admin.id,
        tahfiz_id=tahfiz.id,
        action=action,
        details=f"user={user.id}; role={role.value}; sheikh={body.sheikh_id}",
    ))
    await db.commit()
    await db.refresh(membership)
    return serialize_membership(membership, tahfiz)


@router.put("/users/{user_id}/memberships/{tahfiz_id}")
async def update_user_membership(
    user_id: int,
    tahfiz_id: int,
    body: UpsertUserTahfizMembershipRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin),
):
    if body.tahfiz_id != tahfiz_id:
        raise HTTPException(status_code=400, detail="Tahfiz ID does not match the route")
    return await grant_user_membership(user_id, body, db, admin)


@router.delete("/users/{user_id}/memberships/{tahfiz_id}")
async def revoke_user_membership(
    user_id: int,
    tahfiz_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin),
):
    tahfiz = await db.get(Tahfiz, tahfiz_id)
    membership = await db.scalar(select(UserTahfizMembership).where(
        UserTahfizMembership.user_id == user_id,
        UserTahfizMembership.tahfiz_id == tahfiz_id,
        UserTahfizMembership.is_active == True,
    ))
    if not tahfiz or not membership:
        raise HTTPException(status_code=404, detail="Active membership not found")
    if tahfiz.owner_user_id == user_id:
        raise HTTPException(status_code=409, detail="Transfer Tahfiz ownership before revoking the owner")
    if membership.role == UserRole.admin:
        admin_count = await db.scalar(select(func.count(UserTahfizMembership.id)).where(
            UserTahfizMembership.tahfiz_id == tahfiz_id,
            UserTahfizMembership.role == UserRole.admin,
            UserTahfizMembership.is_active == True,
        ))
        if (admin_count or 0) <= 1:
            raise HTTPException(status_code=409, detail="A Tahfiz must keep at least one admin")
    membership.is_active = False
    user = await db.get(User, user_id)
    if user and user.default_tahfiz_id == tahfiz_id:
        next_membership = await db.scalar(select(UserTahfizMembership).where(
            UserTahfizMembership.user_id == user_id,
            UserTahfizMembership.is_active == True,
            UserTahfizMembership.id != membership.id,
        ).order_by(UserTahfizMembership.id))
        user.default_tahfiz_id = next_membership.tahfiz_id if next_membership else None
        if next_membership is None:
            user.is_active = False
    db.add(AuditLog(
        actor_user_id=admin.id,
        tahfiz_id=tahfiz_id,
        action="membership.revoked",
        details=f"user={user_id}",
    ))
    await db.commit()
    return {"message": "Membership revoked"}


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
