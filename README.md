# Sentinel — Gujarat CCTV Integration & GIS Platform

Sentinel is a unified CCTV management, registry, GIS mapping, and video analytics platform built for Gujarat's statewide surveillance network.

## 👋 New here? (judges & first-time reviewers)

Fastest path to a running app:

1. `cd infra`
2. Create a `SECRET_KEY` (one command, see step 2 below) and save it as `infra/.env`.
3. `docker compose up -d`
4. Open `http://localhost:8000/login` and sign in with `operator1` / `password123`.

That's the whole setup — no local Python install, no manual database steps. Full details in "Quick Start" right below. If something looks confusing or a step doesn't work as written, that's useful feedback in itself.

---

## 🚀 Quick Start (Running with Docker Compose)

The entire platform (PostgreSQL + PostGIS database and the FastAPI application) can be brought up in a single command using Docker Compose.

### Prerequisites
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (with Docker Compose v2+)

### Launch Instructions

1. **Clone & navigate to `infra/`**:
   ```bash
   cd infra
   ```

2. **Set a `SECRET_KEY`** — `docker-compose.yml` refuses to start without one (it signs every login session, so there's no safe default baked in). One command creates `infra/.env` with a real random key (`docker-compose.yml` already defaults `DEBUG=false` on its own, so this is the only variable you need to set to get running):
   ```bash
   # macOS/Linux
   echo "SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')" > .env
   ```
   ```powershell
   # Windows PowerShell
   "SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")" | Out-File -Encoding ascii .env
   ```
   (`../.env.example`, one directory up, documents every other override this file can hold — GRID_HOST, rate-limit tuning, DOMAIN for real HTTPS, etc. — none of the rest are required just to boot the app.)

3. **Start the containers**:
   ```bash
   docker compose up -d
   ```
   *This automatically builds the FastAPI app container (`infra/Dockerfile`) and PostgreSQL + PostGIS + pgvector database container (`infra/Dockerfile.db`), and creates the `sentinel` role/database on first boot — no separate setup step needed.*

   Give it 15-30s on first run (the `db` image build + healthcheck). The `app` image's first build is the slow part — its dependencies include `ultralytics`/PyTorch for the AI detection features, so a first-time `docker compose up -d` can take a few minutes depending on your connection (subsequent builds reuse a pip cache and are much faster, even after changing requirements or code). It's not stuck; `docker compose logs -f app` will show the pip install progress if you want to confirm it's still working. `docker compose ps` should show `db` as `healthy` and `app` as `running` before step 4.

   **You do not need to `pip install` anything on your host machine for this.** The `app` container installs its own dependencies from `model1-registry/requirements.txt`, `model2_analytics/requirements.txt`, and `model3_federation/requirements.txt` inside the build — a local `pip install -r requirements.txt` doesn't feed the Docker build at all and just costs you the same download twice. The "Running Locally Without Docker" section below (a separate, non-Docker workflow for running tests directly on your machine) is the only place a local `pip install` is actually needed.

4. **Access the Web Dashboard**:
   Open your browser and navigate to:
   👉 **`http://localhost:8000`**

    - **Interactive Map Dashboard**: `http://localhost:8000/`
    - **Command Login Portal**: `http://localhost:8000/login`
    - **Camera Registry & CRUD**: `http://localhost:8000/cameras`
    - **Control Room Live Grid (30 Cameras)**: `http://localhost:8000/grid`
    - **Live AI Vehicle Detection (Cam 04 & 22)**: `http://localhost:8000/detection`
    - **Pre-Recorded Video AI Detection**: `http://localhost:8000/recorded-detection`
    - **Vehicle Watchlist (Model 2)**: `http://localhost:8000/watchlist`
    - **Person Watchlist & Biometrics (Model 2)**: `http://localhost:8000/watchlist/persons`
    - **Department Management**: `http://localhost:8000/departments`
    - **District Overview**: `http://localhost:8000/districts`
    - **System Audit Log**: `http://localhost:8000/audit`
    - **Surveillance Gap Analysis**: `http://localhost:8000/gap-analysis`
    - **Swagger OpenAPI Docs**: `http://localhost:8000/docs`

5. **Operational Demo Accounts** (Password: `password123`):
   - `admin_home` (`dept_admin` — Home Department)
   - `admin_rto` (`dept_admin` — Regional Transport Office)
   - `operator1` (`operator`)
   - `viewer1` (`viewer`)

6. **Resetting Database & Seed Data** (if needed):
   ```bash
   docker compose down -v --rmi local
   docker compose up -d
   ```

---

## 🖥️ Running Locally Without Docker

Prefer running the app or tests directly on your machine instead of in containers? You need a local Postgres 16 install with the `postgis`, `pgcrypto`, and `vector` (pgvector) extensions available, then:

```bash
# one-time: creates the `sentinel` role + `sentinel` database (mirrors what
# docker-compose gets automatically from the official Postgres image)
bash scripts/bootstrap_local_db.sh

cd model1-registry
pip install -r requirements-dev.txt
pytest   # also self-bootstraps the sentinel role/db if scripts/bootstrap_local_db.sh wasn't run first
```

See `model1-registry/README.md`'s Testing section for details, including what to check if a run looks stuck.

---

## 🛠️ Technology Stack

- **Backend Framework**: FastAPI (Python 3.12)
- **Database**: PostgreSQL 16 + PostGIS 3.4 + `pgvector` extension
- **ORM & Migrations**: SQLAlchemy 2.0 + GeoAlchemy2
- **Frontend Architecture**: Server-rendered Jinja2 templates + HTMX + Alpine.js (via CDN, no Node build step)
- **Live Video & Analytics**: HLS.js in-browser streaming, RTSP/HLS feeds, ANPR watchlist matching
- **Containerization**: Docker Compose (`infra/docker-compose.yml`)

---

## 📁 Repository Structure

```
├── Project_Context.md       Our working technical specification & architectural decisions
├── HackathonPortal.md       Official hackathon challenge brief
├── docs/
│   ├── API_Contract.md      REST & WebSocket API specification
│   └── DATASET.md           Dataset notes & video stream catalogue
├── shared/                  Shared codebase across models
│   ├── db/                  SQLAlchemy models, schema.sql, triggers.sql, seed.sql
│   ├── schemas/             Pydantic request & response models
│   └── adapters/            VMS adapter interface definitions
├── model1-registry/         Model 1 — Registry & GIS Foundation
│   └── app/                 FastAPI application (routers, templates, static CSS/JS)
├── model2_analytics/        Model 2 — Analytics & Vehicle Tracking (ANPR, Watchlists, Alerts)
│   ├── app/routers/         Watchlist CRUD router
│   └── pipeline/            Analytics & ANPR pipeline architecture
├── model3_federation/       Model 3 — Multi-VMS Federation (adapters, event bus, correlation engine)
│   ├── adapters/            Per-vendor VMS adapters (ONVIF, REST, municipal, police, RTO)
│   └── api/router.py        Federation REST + WebSocket endpoints, mounted into model1's app
├── infra/                   Docker environment (`docker-compose.yml`, `Dockerfile`, `Dockerfile.db`)
└── scripts/                 One-off setup scripts (e.g. `bootstrap_local_db.sh` for non-Docker local dev)
```

---

## 🔌 API Endpoints

The full, authoritative endpoint list — request/response shapes, status markers (decided / draft / open), and WebSocket message contracts — lives in **[`docs/API_Contract.md`](./docs/API_Contract.md)**. Keeping one copy there instead of duplicating it here avoids the two drifting out of sync.

A few to get oriented (all served by the same app on `:8000`):
- `POST /api/v1/auth/login` — sign in, sets an httpOnly JWT cookie
- `GET /` — interactive GIS map dashboard
- `GET /grid` — live multi-camera grid
- `GET /docs` — Swagger UI, generated from the running app (fastest way to browse every route live)

Live Swagger (`/docs`) plus `API_Contract.md` together cover everything; there's no third list to keep updated.

---

## 📄 License & Project Context

See [Project_Context.md](./Project_Context.md) for full architectural background, rationale, and design principles.
