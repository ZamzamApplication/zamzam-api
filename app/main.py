import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.config import settings
from app.database import init_db
from app.media import validate_media_token
from app.routers import auth, sessions, attendance, reports, management, platform, saved_filters
from app.seed import seed_data

UPLOAD_DIR = Path(settings.UPLOAD_DIR)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Zamzam Tahfiz", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
    await init_db()
    await seed_data()


@app.get("/health")
async def health():
    return {"status": "ok"}
