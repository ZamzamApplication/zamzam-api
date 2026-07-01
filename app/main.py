import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.config import settings
from app.database import init_db
from app.routers import auth, sessions, attendance, reports, management, saved_filters
from app.seed import seed_data

UPLOAD_DIR = Path(settings.UPLOAD_DIR)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Quran Circle Tracker", version="1.0.0")

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


@app.get("/uploads/{filepath:path}")
async def serve_upload(filepath: str):
    file = UPLOAD_DIR / filepath
    if not file.exists() or not file.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(file))


@app.on_event("startup")
async def startup():
    await init_db()
    await seed_data()


@app.get("/health")
async def health():
    return {"status": "ok"}
