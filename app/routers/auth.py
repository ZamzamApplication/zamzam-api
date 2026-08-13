from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jwt import InvalidTokenError, decode as jwt_decode, encode as jwt_encode
from passlib.context import CryptContext
from sqlalchemy import and_, delete, false, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import (
    AuditLog,
    AuthRateLimit,
    DeviceSession,
    Tahfiz,
    TahfizStatus,
    Student,
    User,
    UserRole,
    UserTahfizMembership,
    absent_status_option,
    attendance_status_options,
    attendance_status_color_options,
    attendance_streak_status_option,
    present_status_option,
    excel_export_template_options,
    excused_absence_reset_status_options,
)
from app.schemas import (
    CreateTahfizRequest,
    LoginRequest,
    RefreshTokenRequest,
    RevokeDeviceRequest,
    SetDefaultTahfizRequest,
    SignupRequest,
    Token,
)

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer(auto_error=False)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
ACCESS_COOKIE_NAME = "zamzam_access"
CSRF_COOKIE_NAME = "zamzam_csrf"
# Fixed non-secret hash used only to keep invalid-login timing uniform.
DUMMY_PASSWORD_HASH = "$2b$12$4z4Ywktu8JVT1WHg0GCS0uccQT3JwUbOQPUK3UGo3xadxsaJvtN1O"
__all__ = ["pwd_context"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def rate_limit_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


async def check_rate_limit(
    db: AsyncSession,
    key: str,
    limit: int,
    window_seconds: int,
) -> None:
    now = utcnow()
    key_hash = rate_limit_hash(key)
    entry = await db.get(AuthRateLimit, key_hash)
    if not entry or entry.expires_at <= now:
        return
    if entry.attempts >= limit:
        retry_after = max(1, int((entry.expires_at - now).total_seconds()))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )


async def record_rate_limit(
    db: AsyncSession,
    key: str,
    window_seconds: int,
) -> None:
    now = utcnow()
    key_hash = rate_limit_hash(key)
    entry = await db.get(AuthRateLimit, key_hash)
    if not entry or entry.expires_at <= now:
        if entry:
            await db.delete(entry)
        db.add(AuthRateLimit(
            key_hash=key_hash,
            attempts=1,
            window_started_at=now,
            expires_at=now + timedelta(seconds=window_seconds),
        ))
    else:
        entry.attempts += 1
    await db.execute(delete(AuthRateLimit).where(AuthRateLimit.expires_at <= now))
    await db.commit()


async def clear_rate_limit(db: AsyncSession, key: str) -> None:
    await db.execute(delete(AuthRateLimit).where(
        AuthRateLimit.key_hash == rate_limit_hash(key)
    ))
    await db.commit()


def client_ip(request: Request) -> str:
    # Fly sets this header at the trusted edge. Locally, fall back to the socket peer.
    return request.headers.get("fly-client-ip") or (request.client.host if request.client else "unknown")


@dataclass(frozen=True)
class TenantContext:
    user: User
    tahfiz: Tahfiz
    role: UserRole | None = None
    sheikh_id: int | None = None

    @property
    def tahfiz_id(self) -> int:
        return self.tahfiz.id

    @property
    def effective_role(self) -> UserRole:
        return self.role or self.user.role

    @property
    def restricts_sheikh_students(self) -> bool:
        return (
            self.effective_role == UserRole.sheikh
            and self.tahfiz.restrict_sheikh_student_access is not False
        )


def student_scope_clause(context: TenantContext, student_model=Student):
    """Tenant and optional assigned-sheikh boundary for every student query."""
    clauses = [student_model.tahfiz_id == context.tahfiz_id]
    if context.restricts_sheikh_students:
        clauses.append(
            student_model.sheikh_id == context.sheikh_id
            if context.sheikh_id is not None
            else false()
        )
    return and_(*clauses)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt_encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def set_web_session(response: Response, token: str) -> None:
    production = settings.APP_ENV.lower() == "production" or bool(os.getenv("FLY_APP_NAME"))
    max_age = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    response.set_cookie(
        ACCESS_COOKIE_NAME,
        token,
        max_age=max_age,
        httponly=True,
        secure=production,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        secrets.token_urlsafe(32),
        max_age=max_age,
        httponly=False,
        secure=production,
        samesite="lax",
        path="/",
    )


def clear_web_session(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")


def refresh_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_refresh_token(user_id: int, device_id: str, device_name: str | None = None) -> tuple[str, DeviceSession]:
    raw_token = secrets.token_urlsafe(48)
    now = utcnow()
    return raw_token, DeviceSession(
        user_id=user_id,
        token_hash=refresh_token_hash(raw_token),
        device_id=device_id,
        device_name=device_name,
        expires_at=now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        last_used_at=now,
        created_at=now,
    )


def token_response(user: User, refresh_token: str | None = None) -> Token:
    token = create_access_token({
        "sub": str(user.id),
        "uid": user.id,
        "username": user.username,
        "role": user.role.value,
        "ver": user.auth_version,
    })
    return Token(
        access_token=token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


async def get_current_user(token: str, db: AsyncSession) -> User:
    try:
        payload = jwt_decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        subject = payload.get("sub")
        if subject is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    # Tokens issued from this version use an immutable numeric subject. The
    # username fallback keeps already-issued production tokens valid.
    user_id = payload.get("uid")
    if isinstance(user_id, int):
        result = await db.execute(select(User).where(User.id == user_id))
    else:
        result = await db.execute(select(User).where(User.username == str(subject)))
    user = result.scalar_one_or_none()
    if user is None or user.is_active is False:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if payload.get("ver", 0) != user.auth_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session has been revoked")
    return user


async def get_current_user_depends(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = credentials.credentials if credentials else request.cookies.get(ACCESS_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return await get_current_user(token, db)


async def require_admin(current_user: User = Depends(get_current_user_depends)) -> User:
    if current_user.role not in (UserRole.admin, UserRole.super_admin):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


async def require_super_admin(current_user: User = Depends(get_current_user_depends)) -> User:
    if current_user.role != UserRole.super_admin:
        raise HTTPException(status_code=403, detail="Platform administrator access required")
    return current_user


async def get_tenant_context(
    current_user: User = Depends(get_current_user_depends),
    db: AsyncSession = Depends(get_db),
    support_tahfiz_id: int | None = Header(default=None, alias="X-Tahfiz-ID"),
) -> TenantContext:
    tahfiz_id = support_tahfiz_id or current_user.default_tahfiz_id or current_user.tahfiz_id
    membership_role: UserRole | None = None
    membership_sheikh_id: int | None = None
    if current_user.role == UserRole.super_admin:
        tahfiz_id = support_tahfiz_id
        if not tahfiz_id:
            raise HTTPException(status_code=400, detail="Select a Tahfiz support workspace")
        membership_role = UserRole.super_admin
    else:
        if not tahfiz_id:
            raise HTTPException(status_code=403, detail="User is not assigned to a Tahfiz")
        membership = await db.scalar(
            select(UserTahfizMembership).where(
                UserTahfizMembership.user_id == current_user.id,
                UserTahfizMembership.tahfiz_id == tahfiz_id,
            )
        )
        if membership:
            if not membership.is_active:
                raise HTTPException(status_code=403, detail="Tahfiz access has been revoked")
            membership_role = membership.role
            membership_sheikh_id = membership.sheikh_id
        elif tahfiz_id == current_user.tahfiz_id:
            # One-release compatibility fallback for databases that have not
            # completed the membership backfill yet.
            membership_role = current_user.role
            membership_sheikh_id = current_user.sheikh_id
        else:
            raise HTTPException(status_code=403, detail="User is not assigned to this Tahfiz")

    result = await db.execute(select(Tahfiz).where(Tahfiz.id == tahfiz_id))
    tahfiz = result.scalar_one_or_none()
    if not tahfiz:
        raise HTTPException(status_code=404, detail="Tahfiz not found")
    if tahfiz.status != TahfizStatus.active:
        raise HTTPException(
            status_code=403,
            detail={"code": "tahfiz_inactive", "status": tahfiz.status.value, "reason": tahfiz.status_reason},
        )
    if current_user.role == UserRole.super_admin:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5)
        recent_audit = await db.execute(
            select(AuditLog.id)
            .where(
                AuditLog.actor_user_id == current_user.id,
                AuditLog.tahfiz_id == tahfiz.id,
                AuditLog.action == "tahfiz.support_context",
                AuditLog.created_at >= cutoff,
            )
            .limit(1)
        )
        if recent_audit.scalar_one_or_none() is None:
            db.add(AuditLog(
                actor_user_id=current_user.id,
                tahfiz_id=tahfiz.id,
                action="tahfiz.support_context",
                details="Automatic audit from X-Tahfiz-ID support context",
            ))
            await db.commit()
    return TenantContext(
        user=current_user,
        tahfiz=tahfiz,
        role=membership_role,
        sheikh_id=membership_sheikh_id,
    )


async def require_tenant_admin(context: TenantContext = Depends(get_tenant_context)) -> TenantContext:
    if context.effective_role not in (UserRole.admin, UserRole.super_admin):
        raise HTTPException(status_code=403, detail="Tahfiz administrator access required")
    return context


@router.post("/login", response_model=Token)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    username = body.username.strip()
    ip_rate_key = f"login-ip:{client_ip(request)}"
    account_rate_key = f"login-account:{username.casefold()}"
    await check_rate_limit(
        db,
        ip_rate_key,
        settings.LOGIN_RATE_LIMIT_ATTEMPTS,
        settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    )
    await check_rate_limit(
        db,
        account_rate_key,
        settings.LOGIN_RATE_LIMIT_ATTEMPTS,
        settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    )
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    password_matches = pwd_context.verify(
        body.password,
        user.password_hash if user and user.is_active is not False else DUMMY_PASSWORD_HASH,
    )
    if not user or user.is_active is False or not password_matches:
        await record_rate_limit(db, ip_rate_key, settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS)
        await record_rate_limit(db, account_rate_key, settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    await clear_rate_limit(db, ip_rate_key)
    await clear_rate_limit(db, account_rate_key)
    refresh_token = None
    if body.device_id:
        refresh_token, device_session = issue_refresh_token(
            user.id,
            body.device_id,
            body.device_name,
        )
        # A fresh login for the same installation replaces older refresh
        # sessions, limiting replay after an app reinstall or credential reset.
        await db.execute(
            update(DeviceSession)
            .where(
                DeviceSession.user_id == user.id,
                DeviceSession.device_id == body.device_id,
                DeviceSession.revoked_at.is_(None),
            )
            .values(revoked_at=utcnow())
        )
        db.add(device_session)
        await db.commit()
    token = token_response(user, refresh_token)
    if not body.device_id:
        set_web_session(response, token.access_token)
    return token


@router.post("/refresh", response_model=Token)
async def refresh_access_token(body: RefreshTokenRequest, db: AsyncSession = Depends(get_db)):
    now = utcnow()
    device_session = await db.scalar(select(DeviceSession).where(
        DeviceSession.token_hash == refresh_token_hash(body.refresh_token),
        DeviceSession.device_id == body.device_id,
        DeviceSession.revoked_at.is_(None),
        DeviceSession.expires_at > now,
    ))
    if not device_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    user = await db.get(User, device_session.user_id)
    if not user or user.is_active is False:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    replacement, replacement_session = issue_refresh_token(
        user.id,
        device_session.device_id,
        device_session.device_name,
    )
    device_session.revoked_at = now
    device_session.last_used_at = now
    db.add(replacement_session)
    await db.commit()
    return token_response(user, replacement)


@router.post("/revoke-device", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_device(body: RevokeDeviceRequest, db: AsyncSession = Depends(get_db)):
    session = await db.scalar(select(DeviceSession).where(
        DeviceSession.token_hash == refresh_token_hash(body.refresh_token),
        DeviceSession.revoked_at.is_(None),
    ))
    if session:
        session.revoked_at = utcnow()
        await db.commit()


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    user: User = Depends(get_current_user_depends),
    db: AsyncSession = Depends(get_db),
):
    user.auth_version += 1
    await db.execute(
        update(DeviceSession)
        .where(DeviceSession.user_id == user.id, DeviceSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    await db.commit()
    clear_web_session(response)


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(body: SignupRequest, request: Request, db: AsyncSession = Depends(get_db)):
    rate_key = f"signup:{client_ip(request)}"
    await check_rate_limit(
        db,
        rate_key,
        settings.SIGNUP_RATE_LIMIT_ATTEMPTS,
        settings.SIGNUP_RATE_LIMIT_WINDOW_SECONDS,
    )
    await record_rate_limit(db, rate_key, settings.SIGNUP_RATE_LIMIT_WINDOW_SECONDS)
    username = body.username.strip()
    tahfiz_name = body.tahfiz_name.strip()
    if len(username) < 3 or len(body.password) < 8 or len(tahfiz_name) < 2:
        raise HTTPException(
            status_code=400,
            detail="Username must be 3+ characters, password 8+ characters, and Tahfiz name is required",
        )
    existing = await db.execute(select(User.id).where(User.username == username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Username already exists")

    tahfiz = Tahfiz(
        name=tahfiz_name,
        contact_phone=body.contact_phone,
        status=TahfizStatus.pending,
    )
    db.add(tahfiz)
    await db.flush()
    owner = User(
        username=username,
        password_hash=pwd_context.hash(body.password),
        role=UserRole.admin,
        tahfiz_id=tahfiz.id,
        default_tahfiz_id=tahfiz.id,
    )
    db.add(owner)
    await db.flush()
    db.add(UserTahfizMembership(
        user_id=owner.id,
        tahfiz_id=tahfiz.id,
        role=UserRole.admin,
        is_active=True,
        created_by_id=owner.id,
    ))
    tahfiz.owner_user_id = owner.id
    await db.commit()
    await clear_rate_limit(db, rate_key)
    return {
        "message": "Signup request submitted for approval",
        "tahfiz_id": tahfiz.id,
        "status": tahfiz.status.value,
    }


@router.post("/tahfiz", status_code=status.HTTP_201_CREATED)
async def create_linked_tahfiz(
    body: CreateTahfizRequest,
    user: User = Depends(get_current_user_depends),
    db: AsyncSession = Depends(get_db),
):
    if user.role == UserRole.super_admin:
        raise HTTPException(status_code=409, detail="Platform administrators use support workspaces")
    pending = await db.scalar(select(Tahfiz.id).where(
        Tahfiz.owner_user_id == user.id,
        Tahfiz.status == TahfizStatus.pending,
    ))
    if pending:
        raise HTTPException(status_code=409, detail="You already have a Tahfiz awaiting approval")
    name = body.name.strip()
    if len(name) < 2:
        raise HTTPException(status_code=422, detail="Tahfiz name is required")
    tahfiz = Tahfiz(
        name=name,
        contact_phone=body.contact_phone.strip() or None if body.contact_phone else None,
        status=TahfizStatus.pending,
        owner_user_id=user.id,
    )
    db.add(tahfiz)
    await db.flush()
    membership = UserTahfizMembership(
        user_id=user.id,
        tahfiz_id=tahfiz.id,
        role=UserRole.admin,
        is_active=True,
        created_by_id=user.id,
    )
    db.add(membership)
    db.add(AuditLog(
        actor_user_id=user.id,
        tahfiz_id=tahfiz.id,
        action="tahfiz.created",
        details="Linked to existing user account; awaiting platform approval",
    ))
    await db.commit()
    await db.refresh(membership)
    return {
        "message": "Tahfiz request submitted for approval",
        "tahfiz_id": tahfiz.id,
        "membership_id": membership.id,
        "status": tahfiz.status.value,
        "role": membership.role.value,
    }


@router.get("/me")
async def get_me(
    user: User = Depends(get_current_user_depends),
    db: AsyncSession = Depends(get_db),
    active_tahfiz_id: int | None = Header(default=None, alias="X-Tahfiz-ID"),
):
    membership_rows: list[tuple[UserTahfizMembership, Tahfiz]] = []
    if user.role != UserRole.super_admin:
        membership_rows = (await db.execute(
            select(UserTahfizMembership, Tahfiz)
            .join(Tahfiz, Tahfiz.id == UserTahfizMembership.tahfiz_id)
            .where(
                UserTahfizMembership.user_id == user.id,
                UserTahfizMembership.is_active == True,
            )
            .order_by(Tahfiz.name)
        )).all()

    active_membership = next(
        (membership for membership, _ in membership_rows if membership.tahfiz_id == active_tahfiz_id),
        None,
    )
    if active_membership is None:
        preferred_id = user.default_tahfiz_id or user.tahfiz_id
        active_membership = next(
            (membership for membership, _ in membership_rows if membership.tahfiz_id == preferred_id),
            membership_rows[0][0] if membership_rows else None,
        )

    tahfiz = next(
        (
            membership_tahfiz
            for membership, membership_tahfiz in membership_rows
            if active_membership and membership.id == active_membership.id
        ),
        None,
    )
    if tahfiz is None and user.role != UserRole.super_admin and user.tahfiz_id:
        # Compatibility for an account observed between schema deployment and
        # completion of the startup backfill.
        tahfiz = await db.get(Tahfiz, user.tahfiz_id)

    effective_role = (
        UserRole.super_admin
        if user.role == UserRole.super_admin
        else active_membership.role
        if active_membership
        else user.role
    )
    effective_sheikh_id = active_membership.sheikh_id if active_membership else user.sheikh_id
    capabilities = (
        ["platform_admin"]
        if effective_role == UserRole.super_admin
        else ["tenant_admin", "attendance_editor", "report_viewer"]
        if effective_role == UserRole.admin
        else ["attendance_editor", "report_viewer"]
    )
    return {
        "id": user.id,
        "username": user.username,
        "role": effective_role.value,
        "global_role": user.role.value,
        "sheikh_id": effective_sheikh_id,
        "tahfiz_id": tahfiz.id if tahfiz else None,
        "default_tahfiz_id": user.default_tahfiz_id or user.tahfiz_id,
        "capabilities": capabilities,
        "memberships": [
            {
                "id": membership.id,
                "tahfiz_id": membership.tahfiz_id,
                "tahfiz_name": membership_tahfiz.name,
                "tahfiz_status": membership_tahfiz.status.value,
                "role": membership.role.value,
                "sheikh_id": membership.sheikh_id,
            }
            for membership, membership_tahfiz in membership_rows
        ],
        "tahfiz": ({
            "id": tahfiz.id,
            "name": tahfiz.name,
            "status": tahfiz.status.value,
            "status_reason": tahfiz.status_reason,
            "week_start_day": tahfiz.week_start_day,
            "month_start_day": tahfiz.month_start_day,
            "attendance_statuses": attendance_status_options(tahfiz),
            "attendance_status_colors": attendance_status_color_options(tahfiz),
            "excel_export_templates": excel_export_template_options(tahfiz),
            "excused_absence_streak_limit": tahfiz.excused_absence_streak_limit,
            "excused_absence_reset_statuses": excused_absence_reset_status_options(tahfiz),
            "attendance_streak_alert_enabled": tahfiz.attendance_streak_alert_enabled,
            "attendance_sheikh_selection_enabled": tahfiz.attendance_sheikh_selection_enabled,
            "restrict_sheikh_student_access": tahfiz.restrict_sheikh_student_access is not False,
            "attendance_streak_status": attendance_streak_status_option(tahfiz),
            "attendance_streak_limit": tahfiz.excused_absence_streak_limit,
            "attendance_streak_reset_statuses": excused_absence_reset_status_options(tahfiz),
            "present_status": present_status_option(tahfiz),
            "absent_status": absent_status_option(tahfiz),
            "multiple_sessions_per_day_enabled": tahfiz.multiple_sessions_per_day_enabled is True,
            "session_name_options": json.loads(tahfiz.session_name_options or "[]"),
            "sheikh_custom_fields_enabled": tahfiz.sheikh_custom_fields_enabled is True,
            "whatsend_enabled": tahfiz.whatsend_enabled,
            "progress_tracking_enabled": tahfiz.progress_tracking_enabled,
        } if tahfiz else None),
    }


@router.post("/default-tahfiz")
async def set_default_tahfiz(
    body: SetDefaultTahfizRequest,
    user: User = Depends(get_current_user_depends),
    db: AsyncSession = Depends(get_db),
):
    if user.role == UserRole.super_admin:
        raise HTTPException(status_code=409, detail="Platform administrators use support workspaces")
    membership = await db.scalar(select(UserTahfizMembership).where(
        UserTahfizMembership.user_id == user.id,
        UserTahfizMembership.tahfiz_id == body.tahfiz_id,
        UserTahfizMembership.is_active == True,
    ))
    tahfiz = await db.get(Tahfiz, body.tahfiz_id)
    if not membership or not tahfiz or tahfiz.status != TahfizStatus.active:
        raise HTTPException(status_code=404, detail="Active Tahfiz membership not found")
    user.default_tahfiz_id = body.tahfiz_id
    db.add(AuditLog(
        actor_user_id=user.id,
        tahfiz_id=body.tahfiz_id,
        action="membership.default_changed",
        details=f"default_tahfiz_id={body.tahfiz_id}",
    ))
    await db.commit()
    return {"tahfiz_id": body.tahfiz_id, "message": "Default Tahfiz updated"}
