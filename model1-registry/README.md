# Model 1 — Registry & GIS Foundation

The camera registry and GIS dashboard: onboarding, metadata, spatial
visualization, department/district structure, gap analysis, audit
trail. FastAPI + Jinja2/HTMX/Alpine, PostgreSQL + PostGIS via
`shared/db/`.

This package also hosts the shared app shell (auth, page routing, the
Model 2 router auto-loader) since every model runs as one process —
that's not part of Model 1's own feature set, and it's documented
separately rather than folded in here.

**Full documentation:**

- [`docs/model1/README.md`](../docs/model1/README.md) — the actual
  feature: data model, every API endpoint, the gap-analysis math, the
  page list, what's deliberately out of scope.
- [`docs/PLATFORM.md`](../docs/PLATFORM.md) — the shared app shell this
  package's `main.py`/`auth/`/`pages.py` provide for every model.
- [`docs/SECURITY.md`](../docs/SECURITY.md) — auth, RBAC, audit trail,
  and the rest of the platform's security posture.

## Directory layout

```
model1-registry/
└── app/
    ├── routers/     FastAPI routers — cameras, departments, districts,
    │                gap_analysis, audit, auth, pages, streams
    ├── auth/        JWT session auth, RBAC dependencies, login rate limiting
    ├── templates/   Jinja2 templates for every model's pages
    └── static/      Leaflet map logic (map.js) & CSS design system (main.css)
```

## Running the tests

Runs against a real Postgres + PostGIS database (`sentinel_test`), not
SQLite or mocks — see `docs/model1/README.md` §8 for why.

```bash
pip install -r requirements-dev.txt
pytest
```

By default the suite targets `127.0.0.1:5432` — a local, non-Docker
Postgres install. `tests/conftest.py` bootstraps the `sentinel` role
and `sentinel` database itself the first time it notices they're
missing (via `../scripts/bootstrap_local_db.sh`), and rebuilds
`sentinel_test` fresh from `shared/db/{schema,triggers,seed}.sql`
every test session. It does **not** install Postgres itself — you
still need a Postgres 16 server with the `postgis`, `pgcrypto`, and
`vector` extensions available.

### Testing against docker-compose's `db` instead of a local Postgres

`infra/docker-compose.yml` exposes its `db` service on **host port
`5433`**, not `5432` (so it can run alongside a local Postgres install
without colliding). Point the suite at it instead of a local Postgres
with one env var:

```bash
cd infra
SECRET_KEY=local-dev-only-not-secret docker compose up -d db
cd ../model1-registry
TEST_DB_PORT=5433 pytest
```

`TEST_DB_HOST`, `TEST_DB_USER`, and `TEST_DB_PASSWORD` are overridable
the same way if you've changed any of those from their
`docker-compose.yml` defaults.

### `psql` not on `PATH`

`tests/conftest.py` shells out to `psql` (both for bootstrap and to
build `sentinel_test`). Found automatically via `PATH`
(`shutil.which("psql")`) or, on Windows, the default install location;
otherwise set `PSQL_PATH` to its full path before running `pytest`.

### Missing a Postgres extension (`postgis` / `vector` not available)

`pgcrypto` ships with vanilla Postgres; `postgis` and `vector`
(pgvector) don't. If `pytest` fails partway through applying
`schema.sql` with `extension "..." is not available`, the error names
the missing one. Easiest fix, especially on Windows where pgvector
needs a full compile: use docker-compose's `db` service above instead
— its image already bundles all three. Otherwise it's a one-line
package install on Linux/macOS (`postgresql-16-postgis-3` +
`postgresql-16-pgvector` on Debian/Ubuntu, `postgis` + `pgvector` via
Homebrew on macOS).

### If `pytest` seems to hang

Every `psql` call has a hard timeout, so a genuinely broken connection
fails loudly rather than hanging. If a run still looks stuck:

- **A stale connection blocking `DROP DATABASE sentinel_test`** from a
  previously-killed run — `tests/conftest.py` terminates other
  backends on it before dropping, so this should be rare.
- **No network access** for the camera-catalogue poller's startup
  HTTPS call (`app/main.py`'s `lifespan()`, normal in production) —
  `tests/conftest.py` sets `DISABLE_CATALOGUE_POLL=true` before any
  app import to skip this during tests; running the app itself with no
  network will still hit it.
- **A schema-less dev database.** `model3_federation`'s federation
  startup (also in `lifespan()`) writes straight through
  `shared/db/session.py`'s module-level session, bypassing this suite's
  isolation — it targets whatever `DATABASE_URL` points at (the dev
  `sentinel` database) and errors if that database hasn't had
  `schema.sql` applied. `tests/conftest.py` sets
  `DISABLE_FEDERATION_STARTUP=true` before any app import to skip this
  during tests.

Each test runs inside its own transaction + `SAVEPOINT`, rolled back
afterward — so tests can freely create/update/delete through the real
API without leaking state between runs or needing a reseed per test.

Coverage: auth (login/logout/role checks), camera CRUD + department
RBAC (including cross-department 403s and bulk import), districts
(with a regression guard for the empty-`districts`-table seed bug),
and gap-analysis geodesic math (coverage bounds, radius scaling,
real-world area sanity checks per district).
