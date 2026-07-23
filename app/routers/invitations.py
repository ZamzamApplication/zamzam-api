import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.config import settings
from app.models import (
    AuditLog,
    Sheikh,
    TahfizInvitation,
    User,
    UserRole,
    UserTahfizMembership,
)
from app.routers.auth import (
    TenantContext,
    client_ip,
    create_access_token,
    get_current_user_depends,
    pwd_context,
    rate_limiter,
    require_tenant_admin,
)
from app.schemas import CreateTahfizInvitationRequest, InvitationRegistrationRequest

router = APIRouter(prefix="/invitations", tags=["invitations"])


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def invitation_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def invitation_status(invitation: TahfizInvitation, now: datetime | None = None) -> str:
    now = now or utcnow()
    if invitation.used_at:
        return "used"
    if invitation.revoked_at:
        return "revoked"
    if invitation.expires_at <= now:
        return "expired"
    return "active"


def serialize_invitation(
    invitation: TahfizInvitation,
    creator_username: str | None = None,
    sheikh_name: str | None = None,
) -> dict:
    return {
        "id": invitation.id,
        "tahfiz_id": invitation.tahfiz_id,
        "role": invitation.role.value,
        "sheikh_id": invitation.sheikh_id,
        "sheikh_name": sheikh_name,
        "status": invitation_status(invitation),
        "created_by_id": invitation.created_by_id,
        "creator_username": creator_username,
        "created_at": invitation.created_at.isoformat(),
        "expires_at": invitation.expires_at.isoformat(),
        "used_at": invitation.used_at.isoformat() if invitation.used_at else None,
        "used_by_id": invitation.used_by_id,
        "revoked_at": invitation.revoked_at.isoformat() if invitation.revoked_at else None,
    }


async def validate_invitation_role(
    role_value: str,
    sheikh_id: int | None,
    tahfiz_id: int,
    db: AsyncSession,
) -> tuple[UserRole, Sheikh | None]:
    if role_value not in (UserRole.admin.value, UserRole.sheikh.value):
        raise HTTPException(status_code=400, detail="Invitation role must be admin or sheikh")
    sheikh = None
    if sheikh_id is not None:
        sheikh = await db.scalar(select(Sheikh).where(
            Sheikh.id == sheikh_id,
            Sheikh.tahfiz_id == tahfiz_id,
        ))
        if not sheikh:
            raise HTTPException(status_code=404, detail="Sheikh not found in this Tahfiz")
    if role_value == UserRole.admin.value and sheikh_id is not None:
        raise HTTPException(status_code=400, detail="Admin invitations cannot be assigned to a sheikh")
    return UserRole(role_value), sheikh


@router.get("/")
async def list_invitations(
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    rows = (await db.execute(
        select(TahfizInvitation, User.username, Sheikh.name)
        .join(User, User.id == TahfizInvitation.created_by_id)
        .outerjoin(Sheikh, Sheikh.id == TahfizInvitation.sheikh_id)
        .where(TahfizInvitation.tahfiz_id == context.tahfiz_id)
        .order_by(TahfizInvitation.created_at.desc())
        .limit(100)
    )).all()
    return [
        serialize_invitation(invitation, username, sheikh_name)
        for invitation, username, sheikh_name in rows
    ]


@router.post("/")
async def create_invitation(
    body: CreateTahfizInvitationRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    role, sheikh = await validate_invitation_role(
        body.role,
        body.sheikh_id,
        context.tahfiz_id,
        db,
    )
    raw_token = secrets.token_urlsafe(32)
    invitation = TahfizInvitation(
        tahfiz_id=context.tahfiz_id,
        token_hash=invitation_token_hash(raw_token),
        role=role,
        sheikh_id=sheikh.id if sheikh else None,
        created_by_id=context.user.id,
        expires_at=utcnow() + timedelta(hours=body.expires_hours),
    )
    db.add(invitation)
    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz_id,
        action="invitation.created",
        details=f"role={role.value}; sheikh={body.sheikh_id}; expires_hours={body.expires_hours}",
    ))
    await db.commit()
    await db.refresh(invitation)
    result = serialize_invitation(
        invitation,
        context.user.username,
        sheikh.name if sheikh else None,
    )
    result.update({"token": raw_token, "path": f"/invite/{raw_token}"})
    return result


@router.get("/preview/{token}")
async def preview_invitation(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    invitation = await db.scalar(
        select(TahfizInvitation)
        .options(
            selectinload(TahfizInvitation.tahfiz),
            selectinload(TahfizInvitation.sheikh),
        )
        .where(TahfizInvitation.token_hash == invitation_token_hash(token))
    )
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    return {
        **serialize_invitation(
            invitation,
            sheikh_name=invitation.sheikh.name if invitation.sheikh else None,
        ),
        "tahfiz_name": invitation.tahfiz.name,
        "available": invitation_status(invitation) == "active",
    }


@router.post("/register/{token}")
async def register_with_invitation(
    token: str,
    body: InvitationRegistrationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    rate_key = f"invite-register:{client_ip(request)}"
    rate_limiter.check(
        rate_key,
        settings.SIGNUP_RATE_LIMIT_ATTEMPTS,
        settings.SIGNUP_RATE_LIMIT_WINDOW_SECONDS,
    )
    rate_limiter.record(rate_key)
    username = body.username.strip()
    if len(username) < 3 or len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Username must be 3+ characters and password 8+ characters")
    existing_user = await db.scalar(select(User.id).where(User.username == username))
    if existing_user:
        raise HTTPException(status_code=409, detail="Username already exists")

    token_hash = invitation_token_hash(token)
    invitation = await db.scalar(select(TahfizInvitation).where(
        TahfizInvitation.token_hash == token_hash,
    ))
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if invitation_status(invitation) != "active":
        raise HTTPException(status_code=409, detail=f"Invitation is {invitation_status(invitation)}")

    user = User(
        username=username,
        password_hash=pwd_context.hash(body.password),
        role=invitation.role,
        sheikh_id=invitation.sheikh_id,
        tahfiz_id=invitation.tahfiz_id,
        default_tahfiz_id=invitation.tahfiz_id,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    now = utcnow()
    consumed = await db.execute(
        update(TahfizInvitation)
        .where(
            TahfizInvitation.id == invitation.id,
            TahfizInvitation.used_at.is_(None),
            TahfizInvitation.revoked_at.is_(None),
            TahfizInvitation.expires_at > now,
        )
        .values(used_at=now, used_by_id=user.id)
    )
    if consumed.rowcount != 1:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Invitation has already been used")

    db.add(UserTahfizMembership(
        user_id=user.id,
        tahfiz_id=invitation.tahfiz_id,
        role=invitation.role,
        sheikh_id=invitation.sheikh_id,
        is_active=True,
        created_by_id=invitation.created_by_id,
    ))
    db.add(AuditLog(
        actor_user_id=user.id,
        tahfiz_id=invitation.tahfiz_id,
        action="invitation.registered",
        details=f"invitation={invitation.id}; role={invitation.role.value}",
    ))
    await db.commit()
    rate_limiter.clear(rate_key)
    return {
        "access_token": create_access_token({
            "sub": str(user.id),
            "uid": user.id,
            "username": user.username,
            "role": user.role.value,
        }),
        "token_type": "bearer",
    }


@router.post("/accept/{token}")
async def accept_invitation(
    token: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user_depends),
):
    if user.role == UserRole.super_admin:
        raise HTTPException(status_code=409, detail="Platform administrators do not accept tenant invitations")
    token_hash = invitation_token_hash(token)
    invitation = await db.scalar(select(TahfizInvitation).where(
        TahfizInvitation.token_hash == token_hash,
    ))
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if invitation_status(invitation) != "active":
        raise HTTPException(status_code=409, detail=f"Invitation is {invitation_status(invitation)}")

    membership = await db.scalar(select(UserTahfizMembership).where(
        UserTahfizMembership.user_id == user.id,
        UserTahfizMembership.tahfiz_id == invitation.tahfiz_id,
    ))
    if membership and membership.is_active:
        raise HTTPException(status_code=409, detail="User is already a member of this Tahfiz")

    now = utcnow()
    consumed = await db.execute(
        update(TahfizInvitation)
        .where(
            TahfizInvitation.id == invitation.id,
            TahfizInvitation.used_at.is_(None),
            TahfizInvitation.revoked_at.is_(None),
            TahfizInvitation.expires_at > now,
        )
        .values(used_at=now, used_by_id=user.id)
    )
    if consumed.rowcount != 1:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Invitation has already been used")

    if membership:
        membership.role = invitation.role
        membership.sheikh_id = invitation.sheikh_id
        membership.is_active = True
    else:
        membership = UserTahfizMembership(
            user_id=user.id,
            tahfiz_id=invitation.tahfiz_id,
            role=invitation.role,
            sheikh_id=invitation.sheikh_id,
            is_active=True,
            created_by_id=invitation.created_by_id,
        )
        db.add(membership)
    if user.default_tahfiz_id is None:
        user.default_tahfiz_id = invitation.tahfiz_id
    user.is_active = True
    db.add(AuditLog(
        actor_user_id=user.id,
        tahfiz_id=invitation.tahfiz_id,
        action="invitation.accepted",
        details=f"invitation={invitation.id}; role={invitation.role.value}",
    ))
    await db.commit()
    return {
        "message": "Invitation accepted",
        "tahfiz_id": invitation.tahfiz_id,
        "role": invitation.role.value,
    }


@router.delete("/{invitation_id}")
async def revoke_invitation(
    invitation_id: int,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    invitation = await db.scalar(select(TahfizInvitation).where(
        TahfizInvitation.id == invitation_id,
        TahfizInvitation.tahfiz_id == context.tahfiz_id,
    ))
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if invitation.used_at:
        raise HTTPException(status_code=409, detail="Used invitations cannot be revoked")
    if invitation.revoked_at is None:
        invitation.revoked_at = utcnow()
        db.add(AuditLog(
            actor_user_id=context.user.id,
            tahfiz_id=context.tahfiz_id,
            action="invitation.revoked",
            details=f"invitation={invitation.id}",
        ))
        await db.commit()
    return {"message": "Invitation revoked"}


@router.post("/{invitation_id}/resend")
async def resend_invitation(
    invitation_id: int,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    invitation = await db.scalar(select(TahfizInvitation).where(
        TahfizInvitation.id == invitation_id,
        TahfizInvitation.tahfiz_id == context.tahfiz_id,
    ))
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if invitation.used_at:
        raise HTTPException(status_code=409, detail="Used invitations cannot be resent")
    invitation.revoked_at = invitation.revoked_at or utcnow()
    raw_token = secrets.token_urlsafe(32)
    replacement = TahfizInvitation(
        tahfiz_id=context.tahfiz_id,
        token_hash=invitation_token_hash(raw_token),
        role=invitation.role,
        sheikh_id=invitation.sheikh_id,
        created_by_id=context.user.id,
        expires_at=utcnow() + timedelta(hours=48),
    )
    db.add(replacement)
    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz_id,
        action="invitation.resent",
        details=f"previous={invitation.id}; role={invitation.role.value}; sheikh={invitation.sheikh_id}",
    ))
    await db.commit()
    await db.refresh(replacement)
    sheikh = await db.get(Sheikh, invitation.sheikh_id) if invitation.sheikh_id else None
    result = serialize_invitation(
        replacement,
        context.user.username,
        sheikh.name if sheikh else None,
    )
    result.update({"token": raw_token, "path": f"/invite/{raw_token}"})
    return result
