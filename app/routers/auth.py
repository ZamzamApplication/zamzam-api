from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import Tahfiz, TahfizStatus, User, UserRole
from app.schemas import LoginRequest, SignupRequest, Token

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
__all__ = ["pwd_context"]


@dataclass(frozen=True)
class TenantContext:
    user: User
    tahfiz: Tahfiz

    @property
    def tahfiz_id(self) -> int:
        return self.tahfiz.id


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


async def get_current_user(token: str, db: AsyncSession) -> User:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user is None:
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
    tahfiz_id = current_user.tahfiz_id
    if current_user.role == UserRole.super_admin:
        tahfiz_id = support_tahfiz_id
        if not tahfiz_id:
            raise HTTPException(status_code=400, detail="Select a Tahfiz support workspace")
    if not tahfiz_id:
        raise HTTPException(status_code=403, detail="User is not assigned to a Tahfiz")

    result = await db.execute(select(Tahfiz).where(Tahfiz.id == tahfiz_id))
    tahfiz = result.scalar_one_or_none()
    if not tahfiz:
        raise HTTPException(status_code=404, detail="Tahfiz not found")
    if tahfiz.status != TahfizStatus.active:
        raise HTTPException(
            status_code=403,
            detail={"code": "tahfiz_inactive", "status": tahfiz.status.value, "reason": tahfiz.status_reason},
        )
    return TenantContext(user=current_user, tahfiz=tahfiz)


async def require_tenant_admin(context: TenantContext = Depends(get_tenant_context)) -> TenantContext:
    if context.user.role not in (UserRole.admin, UserRole.super_admin):
        raise HTTPException(status_code=403, detail="Tahfiz administrator access required")
    return context


@router.post("/login", response_model=Token)
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == request.username))
    user = result.scalar_one_or_none()
    if not user or not pwd_context.verify(request.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_access_token({
        "sub": user.username,
        "role": user.role.value,
        "tahfiz_id": user.tahfiz_id,
    })
    return Token(access_token=token)


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(request: SignupRequest, db: AsyncSession = Depends(get_db)):
    username = request.username.strip()
    tahfiz_name = request.tahfiz_name.strip()
    if len(username) < 3 or len(request.password) < 8 or len(tahfiz_name) < 2:
        raise HTTPException(
            status_code=400,
            detail="Username must be 3+ characters, password 8+ characters, and Tahfiz name is required",
        )
    existing = await db.execute(select(User.id).where(User.username == username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Username already exists")

    tahfiz = Tahfiz(
        name=tahfiz_name,
        contact_phone=request.contact_phone,
        status=TahfizStatus.pending,
    )
    db.add(tahfiz)
    await db.flush()
    owner = User(
        username=username,
        password_hash=pwd_context.hash(request.password),
        role=UserRole.admin,
        tahfiz_id=tahfiz.id,
    )
    db.add(owner)
    await db.flush()
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
):
    tahfiz = None
    if user.tahfiz_id:
        tahfiz = await db.get(Tahfiz, user.tahfiz_id)
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role.value,
        "sheikh_id": user.sheikh_id,
        "tahfiz_id": user.tahfiz_id,
        "tahfiz": ({
            "id": tahfiz.id,
            "name": tahfiz.name,
            "status": tahfiz.status.value,
            "status_reason": tahfiz.status_reason,
        } if tahfiz else None),
    }
