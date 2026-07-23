from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import monotonic

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import (
    AuditLog,
    Tahfiz,
    TahfizStatus,
    User,
    UserRole,
    UserTahfizMembership,
    attendance_status_options,
)
from app.schemas import LoginRequest, SignupRequest, Token

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
# Fixed non-secret hash used only to keep invalid-login timing uniform.
DUMMY_PASSWORD_HASH = "$2b$12$4z4Ywktu8JVT1WHg0GCS0uccQT3JwUbOQPUK3UGo3xadxsaJvtN1O"
__all__ = ["pwd_context"]


class InMemoryRateLimiter:
    """Small per-process limiter; production edge limiting can be layered on later."""

    def __init__(self) -> None:
        self._attempts: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window_seconds: int) -> None:
        now = monotonic()
        attempts = self._attempts.get(key)
        if not attempts:
            return
        while attempts and attempts[0] <= now - window_seconds:
            attempts.popleft()
        if not attempts:
            self._attempts.pop(key, None)
            return
        if len(attempts) >= limit:
            retry_after = max(1, int(window_seconds - (now - attempts[0])))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many attempts. Please try again later.",
                headers={"Retry-After": str(retry_after)},
            )

    def record(self, key: str) -> None:
        self._attempts[key].append(monotonic())

    def clear(self, key: str) -> None:
        self._attempts.pop(key, None)


rate_limiter = InMemoryRateLimiter()


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


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


async def get_current_user(token: str, db: AsyncSession) -> User:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        subject = payload.get("sub")
        if subject is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except JWTError:
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
    return user


async def get_current_user_depends(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    return await get_current_user(credentials.credentials, db)


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
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    username = body.username.strip()
    rate_key = f"login:{client_ip(request)}"
    rate_limiter.check(
        rate_key,
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
        rate_limiter.record(rate_key)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    rate_limiter.clear(rate_key)
    token = create_access_token({
        "sub": str(user.id),
        "uid": user.id,
        "username": user.username,
        "role": user.role.value,
    })
    return Token(access_token=token)


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(body: SignupRequest, request: Request, db: AsyncSession = Depends(get_db)):
    rate_key = f"signup:{client_ip(request)}"
    rate_limiter.check(
        rate_key,
        settings.SIGNUP_RATE_LIMIT_ATTEMPTS,
        settings.SIGNUP_RATE_LIMIT_WINDOW_SECONDS,
    )
    rate_limiter.record(rate_key)
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
    return {
        "message": "Signup request submitted for approval",
        "tahfiz_id": tahfiz.id,
        "status": tahfiz.status.value,
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
            "progress_tracking_enabled": tahfiz.progress_tracking_enabled,
        } if tahfiz else None),
    }
