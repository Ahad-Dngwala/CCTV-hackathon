# Sentinel - Gujarat CCTV Integration & GIS Platform

Sentinel is a unified CCTV management, registry, GIS mapping, and video analytics platform built for Gujarat's statewide surveillance network.

---

## Quick Start (Docker Compose)

Brings up Postgres + PostGIS and the FastAPI app in one command.

Prerequisites: [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Compose v2+)

1. Copy the env file and set a real `SECRET_KEY`:
   ```bash
   cp .env.example infra/.env
   ```
   Open `infra/.env` and replace the `SECRET_KEY` line with a random value:
   ```bash
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```
   Everything else in `.env.example` already has a working default, so `SECRET_KEY` is the only line you need to touch. `docker-compose.yml` refuses to start without it.

2. Start the containers:
   ```bash
   cd infra
   docker compose up -d
   ```
   The first run builds the app image and the Postgres + PostGIS + pgvector database image, and creates the `sentinel` role/database automatically. The app image's first build can take a few minutes (its dependencies include PyTorch for the AI detection features) - `docker compose logs -f app` shows the install progress if you want to confirm it's still working. `docker compose ps` should show `db` as `healthy` and `app` as `running` before moving on.

   You do not need to `pip install` anything on your host for this - the app container installs its own dependencies during the build.

3. Open the dashboard at `http://localhost:8000`:
   - Map dashboard: `/`
   - Login: `/login`
   - Camera registry: `/cameras`
   - Live grid (30 cameras): `/grid`
   - Live AI vehicle detection: `/detection`
   - Pre-recorded video AI detection: `/recorded-detection`
   - Vehicle watchlist: `/watchlist`
   - Person watchlist & biometrics: `/watchlist/persons`
   - Departments: `/departments`
   - Districts: `/districts`
   - Audit log: `/audit`
   - Gap analysis: `/gap-analysis`
   - API docs (Swagger): `/docs`

4. Demo accounts (password: `password123`):
   - `admin_home` (`dept_admin` - Home Department)
   - `admin_rto` (`dept_admin` - Regional Transport Office)
   - `operator1` (`operator`)
   - `viewer1` (`viewer`)

5. Reset the database and seed data if needed:
   ```bash
   docker compose down -v --rmi local
   docker compose up -d
   ```

---

## Running Locally Without Docker

Needs a local Postgres 16 with the `postgis`, `pgcrypto`, and `vector` (pgvector) extensions installed.

```bash
bash scripts/bootstrap_local_db.sh   # one-time: creates the sentinel role + database

cd model1-registry
pip install -r requirements-dev.txt
pytest
```

See `model1-registry/README.md`'s Testing section for details, including what to check if a run looks stuck.

---

## Running the Tests

The easiest way to run the full test suite locally is to reuse the same Postgres + PostGIS + pgvector database container used by the application.

From the repository root:

```bash
cd infra
docker compose up -d
```

The first run builds the database image and starts Postgres with the required `postgis` and `pgvector` extensions. Wait until the database is healthy:

```bash
docker compose ps
```

Then return to the repository root and install the development dependencies for **all three models**:

```bash
cd ..

pip install -r model1-registry/requirements-dev.txt
pip install -r model2_analytics/requirements-dev.txt
pip install -r model3_federation/requirements-dev.txt
```

The three models have separate development requirement files because their test and development dependencies are maintained independently.

On Windows, the Docker database is exposed on host port `5433`. Set the test database port before running the suite:

```cmd
set TEST_DB_PORT=5433
pytest -v
```

On PowerShell:

```powershell
$env:TEST_DB_PORT = "5433"
pytest -v
```

Running `pytest -v` from the repository root runs the test suites across Model 1, Model 2, and Model 3.

If you need to completely reset the Docker database and start fresh:

```bash
cd infra
docker compose down -v
docker compose up -d
```

---

## Technology Stack

- Backend Framework: FastAPI (Python 3.12)
- Database: PostgreSQL 16 + PostGIS 3.4 + `pgvector` extension
- ORM & Migrations: SQLAlchemy 2.0 + GeoAlchemy2
- Frontend Architecture: Server-rendered Jinja2 templates + HTMX + Alpine.js (via CDN, no Node build step)
- Live Video & Analytics: HLS.js in-browser streaming, RTSP/HLS feeds, ANPR watchlist matching
- Containerization: Docker Compose (`infra/docker-compose.yml`)

---

## Repository Structure

```
Project_Context.md        Working technical specification & architectural decisions
HackathonPortal.md         Hackathon challenge brief
docs/
    model1/README.md       Model 1 - full feature documentation (data model, every endpoint, GIS/gap-analysis internals)
    PLATFORM.md             The shared FastAPI app shell every model runs inside
    SECURITY.md             Auth, RBAC, audit trail & cybersecurity posture (cross-model)
    API_Contract.md        REST & WebSocket API specification
    DATASET.md              Dataset notes & video stream catalogue
shared/                     Shared codebase across models
    db/                     SQLAlchemy models, schema.sql, triggers.sql, seed.sql
    schemas/                Pydantic request & response models
    adapters/               VMS adapter interface definitions
model1-registry/           Model 1 - Registry & GIS Foundation
    app/                    FastAPI application (routers, templates, static CSS/JS)
model2_analytics/          Model 2 - Analytics & Vehicle Tracking (ANPR, Watchlists, Alerts)
    app/routers/            Watchlist CRUD router
    pipeline/               Analytics & ANPR pipeline architecture
model3_federation/         Model 3 - Multi-VMS Federation (adapters, event bus, correlation engine)
    adapters/               Per-vendor VMS adapters (ONVIF, REST, municipal, police, RTO)
    api/router.py           Federation REST + WebSocket endpoints, mounted into model1's app
infra/                      Docker environment (docker-compose.yml, Dockerfile, Dockerfile.db)
scripts/                    One-off setup scripts (e.g. bootstrap_local_db.sh for non-Docker local dev)
```

---

## API Endpoints Summary

### Model 1 - Registry, Auth & GIS
*(Full documentation, request/response examples, and RBAC rules: [`docs/model1/README.md`](docs/model1/README.md))*
- `POST /api/v1/auth/login` - Authenticate user and set httpOnly JWT cookie
- `POST /api/v1/auth/logout` - Log out user and clear session cookie
- `GET /api/v1/cameras` - List, filter by department, district, and status
- `POST /api/v1/cameras` - Create new camera (manual entry, `dept_admin` scoped)
- `POST /api/v1/cameras/bulk` - CSV bulk camera import (`dept_admin` scoped)
- `GET /api/v1/cameras/{id}` - Get camera detail & VMS stream URL
- `PATCH /api/v1/cameras/{id}` - Update camera (writes `status_history` audit log)
- `DELETE /api/v1/cameras/{id}` - Soft delete camera (`is_active = false`)
- `GET /api/v1/cameras/{id}/history` - Camera audit history
- `GET /api/v1/audit` - System-wide audit trail logs
- `GET /api/v1/departments` - List departments with active camera counts
- `GET /api/v1/districts` - List all 33 Gujarat districts with camera counts and GeoJSON boundaries
- `GET /api/v1/gap-analysis` - PostGIS spatial camera coverage calculation (1km buffer)

### Model 2 - Live Grid, AI Detection & Video Analytics
- `GET /grid` - Control-Room Multi-Camera Live Grid UI (2x2, 3x3, 4x4 matrix views)
- `GET /api/ingest` - Hackathon ingestion contract - returns all cameras with RTSP/WHEP/HLS URLs
- `GET /api/v1/grid/streams` - JSON API: all active camera stream URLs (with dept/district filters)
- `POST /api/v1/grid/sync` - Sync camera catalogue from external source into DB
- `GET /detections` or `GET /detection` - Live AI Vehicle Detection Dashboard
- `GET /api/v1/detections` - Paginated vehicle detection audit history from DB
- `GET /api/v1/detections/stats` - Real-time vehicle detection counts and active tracks
- `WS /ws/detections` - WebSocket stream for live bounding boxes, track IDs, and sightings
- `GET /recorded-detection` - Pre-Recorded Video AI Detection Dashboard UI
- `POST /api/v1/recorded/upload` - Multipart video upload (up to 2 GB) with OpenCV metadata extraction
- `GET /api/v1/recorded/cameras` - List active cameras for location association
- `POST /api/v1/recorded/start` - Start isolated background video analysis worker
- `POST /api/v1/recorded/pause` / `resume` / `stop` - Execution controls
- `GET /api/v1/recorded/status/{job_id}` - Query status, frame count, processing FPS
- `WS /ws/recorded/{job_id}` - Real-time video frame and bounding box WebSocket stream
- `GET /api/v1/watchlist/vehicles` - List & search vehicle targets (filter by `category`, `status`, `plate_number`, `department_id`)
- `POST /api/v1/watchlist/vehicles` - Add new vehicle target (with Indian plate format validation & duplicate checks)
- `GET /api/v1/watchlist/vehicles/{id}` - Get single watchlist target detail
- `PATCH /api/v1/watchlist/vehicles/{id}` - Update target case status (`active` / `resolved`) or details
- `DELETE /api/v1/watchlist/vehicles/{id}` - Delete watchlist target and cascade associated alerts
- `GET /detection-image/{file_path}` - Authenticated serving of vehicle/plate cropped detection images
- `GET /face-detection` - Surveillance Video Face Detection & Watchlist Alerting Dashboard UI
- `GET /api/v1/face-detection/active-jobs` - List all ongoing and ready face processing jobs
- `POST /api/v1/face-detection/upload` - Upload surveillance footage (up to 2 GB) with OpenCV metadata probing
- `POST /api/v1/face-detection/start` - Start background face detection & watchlist matching worker (1x, 2x, max speed)
- `POST /api/v1/face-detection/pause` / `resume` / `stop` - Execution controls for face analysis worker
- `GET /api/v1/face-detection/status/{job_id}` - Query face processing status, detected face counts, and watchlist hits
- `GET /api/v1/face-detection/alerts` - Paginated person watchlist match alerts with confidence scores and distance metrics
- `GET /api/v1/face-detection/crops/{filename}` - Authenticated serving of detected face match crop thumbnails
- `WS /api/v1/face-detection/ws/{job_id}` - Real-time WebSocket channel streaming frames, face bounding boxes, and instant watchlist match alerts
- `GET /api/v1/watchlist/persons` - List & filter person targets (filter by `category`, `status`, `name`)
- `POST /api/v1/watchlist/persons` - Register person target with 5-gate AI quality validation (YuNet + solvePnP 3D pose), 10 MB photo limit, and 512-d InceptionResnetV1 embedding in `pgvector`
- `GET /api/v1/watchlist/persons/{id}` - Get single person watchlist target detail
- `PATCH /api/v1/watchlist/persons/{id}` - Update person details or toggle status (`active` / `resolved`)
- `DELETE /api/v1/watchlist/persons/{id}` - Remove person target and disk reference photo
- `GET /api/v1/watchlist/persons/photos/{photo_filename}` - Authenticated serving of reference face portrait

---

## License & Project Context

See [Project_Context.md](./Project_Context.md) for full architectural background, rationale, and design principles. For Model 1 specifically, [`docs/model1/README.md`](docs/model1/README.md) is the authoritative reference - Project_Context.md is our working spec and may run ahead of or behind what's actually implemented.
