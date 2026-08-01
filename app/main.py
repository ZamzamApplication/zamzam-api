import logging
import os
import asyncio
import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.config import settings
from sqlalchemy import text

from app.database import async_session, init_db
from app.backup_scheduler import backup_loop
from app.media import validate_media_token
from app.routers.auth import ACCESS_COOKIE_NAME, CSRF_COOKIE_NAME
from app.routers import auth, sessions, attendance, reports, management, platform, progress, saved_filters, invitations, sync, feedback, subscriptions
from app.seed import seed_data

logger = logging.getLogger(__name__)
backup_task: asyncio.Task | None = None
UPLOAD_DIR = Path(settings.UPLOAD_DIR)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Zamzam Tahfiz", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(sessions.router)
app.include_router(attendance.router)
app.include_router(reports.router)
app.include_router(management.router)
app.include_router(subscriptions.router)
app.include_router(saved_filters.router)
app.include_router(platform.router)
app.include_router(progress.router)
app.include_router(invitations.router)
app.include_router(sync.router)
app.include_router(feedback.router)

CSRF_EXEMPT_PATHS = {
    "/auth/login",
    "/auth/signup",
    "/auth/refresh",
    "/auth/revoke-device",
}


@app.middleware("http")
async def enforce_cookie_csrf(request: Request, call_next):
    cookie_authenticated = bool(request.cookies.get(ACCESS_COOKIE_NAME))
    bearer_authenticated = request.headers.get("authorization", "").lower().startswith("bearer ")
    invitation_registration = request.url.path.startswith("/invitations/register/")
    if (
        request.method in {"POST", "PUT", "PATCH", "DELETE"}
        and cookie_authenticated
        and not bearer_authenticated
        and request.url.path not in CSRF_EXEMPT_PATHS
        and not invitation_registration
    ):
        cookie_token = request.cookies.get(CSRF_COOKIE_NAME, "")
        header_token = request.headers.get("x-csrf-token", "")
        if not cookie_token or not header_token or not secrets.compare_digest(cookie_token, header_token):
            return JSONResponse(status_code=403, content={"detail": "Invalid CSRF token"})
    return await call_next(request)


@app.get("/uploads/{filepath:path}")
async def serve_upload(filepath: str, token: str):
    try:
        tahfiz_id = validate_media_token(token, filepath)
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid or expired media link")
    file = (UPLOAD_DIR / filepath).resolve()
    upload_root = UPLOAD_DIR.resolve()
    if upload_root not in file.parents or not file.exists() or not file.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    # New uploads are tenant-prefixed. Legacy root files remain protected by
    # the signed token's tenant claim during the compatibility migration.
    if "/" in filepath and filepath.split("/", 1)[0] != str(tahfiz_id):
        raise HTTPException(status_code=403, detail="Media does not belong to this Tahfiz")
    return FileResponse(str(file))


@app.on_event("startup")
async def startup():
    global backup_task
    production = settings.APP_ENV.lower() == "production" or bool(os.getenv("FLY_APP_NAME"))
    security_issues = settings.security_issues()
    if security_issues and production:
        message = "Unsafe production security configuration: " + "; ".join(security_issues)
        raise RuntimeError(message)
    await init_db()
    await seed_data()
    backup_task = asyncio.create_task(backup_loop(), name="sqlite-backup-loop")


@app.on_event("shutdown")
async def shutdown():
    if backup_task:
        backup_task.cancel()
        try:
            await backup_task
        except asyncio.CancelledError:
            pass


@app.get("/health")
async def health():
    try:
        async with async_session() as db:
            await db.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return {"status": "ok", "database": "ok"}
