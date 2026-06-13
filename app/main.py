import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db
from app.routers import auth, sessions, attendance, reports, management
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

app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

app.include_router(auth.router)
app.include_router(sessions.router)
app.include_router(attendance.router)
app.include_router(reports.router)
app.include_router(management.router)


@app.on_event("startup")
async def startup():
    await init_db()
    await seed_data()


@app.get("/health")
async def health():
    return {"status": "ok"}
