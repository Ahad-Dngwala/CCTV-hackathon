"""
Sentinel — Model 1 Registry & GIS
FastAPI application entry point.

Boots the app, mounts routers, configures templates and static files.
Run with:  uvicorn app.main:app --reload
"""

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# ── Make `shared` importable when running locally ─────────────────
current_dir = Path(__file__).resolve().parent
local_repo_root = current_dir.parent.parent
if (local_repo_root / "shared").exists() and str(local_repo_root) not in sys.path:
    sys.path.insert(0, str(local_repo_root))

from app.config import settings  # noqa: E402
from app.routers import audit, auth, cameras, departments, districts, gap_analysis, pages  # noqa: E402
from shared.db.session import init_engine  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise the DB engine once at startup."""
    init_engine(settings.DATABASE_URL)
    yield


app = FastAPI(
    title="Sentinel — Registry & GIS",
    description="Model 1: Camera registry, GIS mapping, and department/district management for Gujarat's CCTV network.",
    version="0.1.0",
    lifespan=lifespan,
)

# ── Templates & static ──────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent
app.state.templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# ── Routers ──────────────────────────────────────────────────────

app.include_router(auth.router)
app.include_router(audit.router)
app.include_router(cameras.router)
app.include_router(departments.router)
app.include_router(districts.router)
app.include_router(gap_analysis.router)
app.include_router(pages.router)
