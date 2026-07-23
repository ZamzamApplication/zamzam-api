import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.config import settings
from sqlalchemy import text

from app.database import async_session, init_db
from app.media import validate_media_token
from app.routers import auth, sessions, attendance, reports, management, platform, progress, saved_filters, invitations
from app.seed import seed_data

logger = logging.getLogger(__name__)
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
app.include_router(saved_filters.router)
app.include_router(platform.router)
app.include_router(progress.router)
app.include_router(invitations.router)


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
    production = settings.APP_ENV.lower() == "production" or bool(os.getenv("FLY_APP_NAME"))
    security_issues = settings.security_issues()
    if security_issues and production:
        message = "Unsafe production security configuration: " + "; ".join(security_issues)
        if settings.STRICT_SECURITY_VALIDATION:
            raise RuntimeError(message)
        logger.critical("%s. Set STRICT_SECURITY_VALIDATION=true after correcting it.", message)
    await init_db()
    await seed_data()


@app.get("/health")
async def health():
    try:
        async with async_session() as db:
            await db.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return {"status": "ok", "database": "ok"}
