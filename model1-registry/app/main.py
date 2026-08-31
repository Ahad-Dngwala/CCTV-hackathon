"""
Sentinel — Model 1 Registry & GIS
FastAPI application entry point.

Boots the app, mounts routers, configures templates and static files.
Run with:  uvicorn app.main:app --reload
"""

import os
import sys
import importlib.util as _ilu
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

# ── Model 1 Routers ──────────────────────────────────────────────

app.include_router(auth.router)
app.include_router(audit.router)
app.include_router(cameras.router)
app.include_router(departments.router)
app.include_router(districts.router)
app.include_router(gap_analysis.router)
app.include_router(pages.router)

# ── Model 2 Routers (auto-discovery) ─────────────────────────────
# Every *.py file in model2-analytics/app/routers/ that exposes a
# `router` attribute is automatically loaded and mounted here.
#
# Adding a new Model 2 feature:
#   1. Create  model2-analytics/app/routers/<feature>.py
#   2. Define  router = APIRouter(...)  inside it
#   Done — no changes to this file needed.
#
# Works both in Docker (/model2-analytics/app/routers/)
# and locally (<repo_root>/model2-analytics/app/routers/).

_M2_ROUTERS_DIR_CANDIDATES = [
    Path("/model2-analytics/app/routers"),                              # Docker
    local_repo_root / "model2-analytics" / "app" / "routers",          # Local dev
]
_m2_routers_dir = next((p for p in _M2_ROUTERS_DIR_CANDIDATES if p.is_dir()), None)

if _m2_routers_dir:
    for _router_file in sorted(_m2_routers_dir.glob("*.py")):
        if _router_file.name.startswith("_"):       # skip __init__.py, etc.
            continue
        try:
            _spec = _ilu.spec_from_file_location(
                f"model2.routers.{_router_file.stem}", _router_file
            )
            _mod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            if hasattr(_mod, "router"):
                app.include_router(_mod.router)
                print(f"[model2] mounted : {_router_file.name}")
            else:
                print(f"[model2] skipped  : {_router_file.name}  (no `router` attribute)")
        except Exception as _exc:
            print(f"[model2] ERROR    : {_router_file.name}  → {_exc}")
else:
    print("[model2] routers directory not found — Model 2 endpoints unavailable.")
