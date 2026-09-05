# Model 1 — Registry & GIS Foundation

Full spec: `Project_Context.md` §3 & `Model1ImplementationPlan.md`.

## What this owns

The camera registry and the GIS map dashboard. This handles camera onboarding, metadata tracking, status management, spatial visualization across Gujarat, department/district categorization, and audit logging.

## Features Implemented

- **Interactive GIS Map (`/`)**: Leaflet + OpenStreetMap, marker clustering via `Leaflet.markercluster`, connectivity status markers (🟢 online, 🔴 offline, 🟡 maintenance), district dropdown filtering, department layer toggles, and rich popup cards with VMS stream viewer links.
- **Camera Registry & Table View (`/cameras`)**: HTMX-driven sortable/filterable table, soft delete (`is_active = false`), and bulk CSV import (`/api/v1/cameras/bulk`).
- **Camera CRUD Modal Forms**: Alpine.js v3 + HTMX modal for creating and updating camera metadata, writing automated audit logs to `status_history`.
- **Department View (`/departments`)**: Read-only view with active camera counts per department.
- **District View (`/districts`)**: Coverage view for all 33 Gujarat districts.
- **Model 2 Stubs**: Inert navigation links for `/detections`, `/watchlist`, `/alerts`.

## Stack

FastAPI + Jinja2 templates + HTMX + Alpine.js (no Node build step). PostgreSQL + PostGIS via `shared/db/`.

## Directory layout

```
model1-registry/
└── app/
    ├── routers/     FastAPI routers — cameras, departments, districts, pages
    ├── templates/   Jinja2 HTML templates (map.html, cameras_list.html, camera_form.html, etc.)
    └── static/      Leaflet map logic (map.js) & CSS design system (main.css)
```

## Status

✅ **Completed — Phase 1 & Foundation Built**. Full CRUD, GIS map dashboard, dark theme glassmorphism UI, seed data, and docker setup are operational.

## Testing

The test suite runs against a real Postgres + PostGIS database (`sentinel_test`), not sqlite or mocks — the app relies on PostGIS geography functions and Postgres triggers with no sqlite equivalent, so testing against anything else wouldn't exercise the code paths that actually matter (RBAC scoping, geodesic gap-analysis math, audit-log triggers).

```bash
pip install -r requirements-dev.txt

# one-time: create the test role/db if it doesn't exist yet
psql -h 127.0.0.1 -U postgres -c "CREATE DATABASE sentinel_test OWNER sentinel;"

pytest
```

`tests/conftest.py` shells out to `psql` itself (to build `sentinel_test` from the real schema/triggers/seed - see below), so `psql` needs to be resolvable when you run `pytest`, not just available for the one-time setup command above. It's found automatically if it's on your `PATH` (`shutil.which("psql")`, checked first) or, on Windows, in the default install location (`C:\Program Files\PostgreSQL\<version>\bin`). If neither applies - e.g. a portable/zip install, or a terminal that was already open before installing Postgres and hasn't picked up the updated `PATH` - set `PSQL_PATH` to `psql`'s full path (`psql.exe` on Windows) before running `pytest`, and it'll be used directly with no PATH changes needed:

```powershell
$env:PSQL_PATH = "C:\Program Files\PostgreSQL\16\bin\psql.exe"
pytest
```

Each test runs inside its own transaction + `SAVEPOINT` that's rolled back afterward, so tests can freely create/update/delete rows (including through the real API, which calls `db.commit()`) without leaking state between tests or needing a reseed per test. `tests/conftest.py` applies `shared/db/schema.sql` → `triggers.sql` → `seed.sql` once per test session — exactly what `docker-compose` does in production — so the fixtures exercise the real seeded departments/districts/cameras.

Coverage: auth (login/logout/role checks), camera CRUD + department-scoped RBAC (create/update/delete cross-department 403s, bulk import), districts (including a regression guard for the empty-`districts`-table seed bug), and gap-analysis geodesic math (coverage bounds, radius scaling, real-world area sanity checks per district).
