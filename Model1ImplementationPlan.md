# Model 1 — Registry & GIS Foundation: Implementation Plan (Phase 1)

Repo: `Vishmayraj/MyFirstPythonCalculator`. Read `Project_Context.md` in
full before starting . **Phase 1 only**: map + camera list + CRUD + read-only
views over every table in `shared/db/schema.sql`. Explicitly deferred to
Phase 2 (do not build now): login/RBAC, audit-log UI, gap-analysis.

Stack, non-negotiable (`Project_Context.md` §2, §10 — do not re-litigate):
FastAPI, Jinja2 templates, HTMX + Alpine.js via CDN, Leaflet + OSM.
No React, no Django, no Node build step, no npm/node_modules.

**Coordinates are already handled** — `shared/db/seed.sql` now sets a
real `location` (`ST_GeogFromText('SRID=4326;POINT(lon lat)')`) and
`district_id` directly in the camera INSERTs, hand-placed rather than
geocoded. No backfill step needed; if any camera still has `location
IS NULL` by the time you seed, treat it as "not yet placed" and just
exclude it from the map (see Phase 5), don't block on it.

---

## Phase 1 — Backend scaffold

Directory layout (fill in the `.gitkeep` stubs in `model1-registry/app/`
and `shared/`):

```
shared/
  db/
    models.py          SQLAlchemy models mirroring schema.sql exactly
    session.py         engine + SessionLocal + get_db() dependency
  schemas/
    camera.py           Pydantic Camera / CameraCreate / CameraUpdate
    department.py
    district.py
model1-registry/
  app/
    main.py             FastAPI() instance, mounts routers + static, templates config
    config.py            settings via pydantic-settings (DATABASE_URL, etc.)
    routers/
      cameras.py
      departments.py
      districts.py
      pages.py           the HTML page routes (map, list, forms) — separate from the /api/v1 routers
    templates/
      base.html          nav bar, HTMX + Alpine + Leaflet CDN includes
      map.html
      cameras_list.html
      camera_form.html    shared create/edit form, HTMX partial
      departments_list.html
      districts_list.html
    static/
      css/main.css
      js/map.js           Leaflet init, marker rendering, filter fetches
```

Dependencies to add (`model1-registry/requirements.txt` or root
`pyproject.toml`, your call, but pick one and be consistent):
`fastapi`, `uvicorn[standard]`, `sqlalchemy>=2.0`, `geoalchemy2` (needed
for the `GEOGRAPHY(POINT, 4326)` column type), `psycopg2-binary`,
`pydantic-settings`, `jinja2`, `python-multipart` (form posts),
`shapely` (geoalchemy2 pulls this in for geometry serialization).

`shared/db/models.py` must mirror `schema.sql` column-for-column. Don't
invent extra fields Alembic would fight later — this is the same rule
`Project_Context.md` applies to `docs/API_Contract.md`: the DB is the
source of truth, this file describes it, it doesn't extend it.

Acceptance: `uvicorn app.main:app --reload` boots clean against the
existing `db` container from `infra/docker-compose.yml`, and
`GET /api/v1/departments` returns the 5 seeded rows as JSON.

---

## Phase 2 — Camera API (CRUD + list/filter + bulk import)

Build against `docs/API_Contract.md` §1 exactly — these are marked ✅
decided, build against them as-is:

| Endpoint | Notes |
|---|---|
| `GET /api/v1/cameras` | Query params: `department_id`, `district_id`, `connectivity_status`. Returns the Camera object shape from the contract doc as-is. |
| `POST /api/v1/cameras` | Manual entry. |
| `POST /api/v1/cameras/bulk` | CSV upload. Keep this genuinely simple per `Project_Context.md` §8 — parse rows, validate, insert, return a count of created/skipped/errored. No wizard, no preview step. |
| `GET /api/v1/cameras/{id}` | Full detail incl. `vms_url`. |
| `PATCH /api/v1/cameras/{id}` | Partial update. The DB triggers in `shared/db/triggers.sql` already write `status_history` automatically on the fields that matter — don't duplicate that logging in the API layer. |
| `DELETE /api/v1/cameras/{id}` | This is still 🚧 in the contract doc. Implement as **soft delete**: set `is_active = false`, which the trigger already timestamps into `decommissioned_at`. Update the contract doc's status to ✅ once you've implemented it, since you're the one resolving that open question. |

For `PATCH`, remember the trigger reads `app.current_user_id` via
`SET LOCAL` — since Phase 1 has no auth, just don't set it; the trigger
already falls back to `NULL` cleanly (see `triggers.sql` comment), so
`changed_by` will be `NULL` on every audit row for now. That's expected
and fine until Phase 2's login work lands.

Acceptance: full CRUD cycle works via `curl` or the FastAPI `/docs`
Swagger UI before touching any HTML.

---

## Phase 3 — Department & District read APIs

`GET /api/v1/departments` and `GET /api/v1/districts` — simple list
endpoints, no filters needed yet. `districts` includes `boundary` per
the contract doc, but it's `NULL` for all 33 rows right now (no
shapefile sourced — `Project_Context.md` §9 open question), so just
return it as `null` in the GeoJSON-ish shape, don't error on it.

---

## Phase 4 — Frontend shell

`base.html`: nav bar with links to **Map** (home, `/`), **Cameras**
(`/cameras`), **Departments** (`/departments`), **Districts**
(`/districts`), plus the Phase-2 placeholders below. Pull in via CDN:
Leaflet + Leaflet.markercluster CSS/JS, HTMX, Alpine.js. No bundler, no
build step — literal `<script src="https://unpkg.com/...">` tags, per
`Project_Context.md` §2.

Architectural note worth being explicit about in the plan: **use HTMX
for the list/CRUD pages** (server renders and swaps HTML partials —
that's what HTMX is for), but **use plain `fetch()` + Leaflet JS for
the map's dynamic filtering** (department toggle, district dropdown).
HTMX swaps DOM nodes; Leaflet needs JS marker objects, not HTML, so
filter changes on the map page should `fetch('/api/v1/cameras?...')`
and redraw the layer in `static/js/map.js`, not go through HTMX.
Don't mix these up or you'll fight the wrong tool on both pages.

---

## Phase 5 — Map dashboard (home page, `/`)

- Leaflet map, OSM tile layer, centered on Gujarat.
- On load, `fetch('/api/v1/cameras')`, plot every camera that has a
  non-null `location`. If any camera still lacks one, don't invent a
  placeholder pin for it — it just doesn't appear on the map, and
  shows up in the Phase 6 list view instead with an "unmapped" badge.
- Marker icon: use `L.divIcon` with an emoji per `connectivity_status`
  as a placeholder — e.g. 🟢 online, 🔴 offline, 🟡 maintenance. This is
  explicitly a placeholder; `Project_Context.md` §9 has custom icon
  design as a still-open decision, don't over-invest here.
- Wrap markers in `Leaflet.markercluster` for the "flock" clustering
  effect at low zoom (`Project_Context.md` §3).
- Click a marker → popup with: name, department, district, camera
  type, ownership, connectivity status, storage/retention, and — if
  `vms_url` is set — a hyperlink out to the native VMS viewer, opening
  in a new tab.
- Controls: a department layer-toggle (Leaflet layer control, one
  overlay group per department) and a district `<select>` dropdown.
  Both trigger a re-fetch + redraw, not a page reload.

---

## Phase 6 — Camera list/table view (`/cameras`)

- Sortable, filterable HTML table (HTMX-driven — filter form submits,
  server returns the updated `<tbody>` partial).
- Columns: name, department, district, connectivity_status (badge),
  camera_type, ownership, location (or an "unmapped" badge if
  `location IS NULL`), updated_at.
- Row actions: Edit (opens `camera_form.html` partial via HTMX),
  Deactivate (calls the soft-delete `DELETE` endpoint, HTMX swaps the
  row to reflect `is_active = false`).

---

## Phase 7 — Camera CRUD forms

- One shared `camera_form.html` partial for both create and edit,
  HTMX-posted (`hx-post` / `hx-patch`), server-side validation errors
  re-rendered inline in the same partial (standard HTMX pattern —
  return the form again with error text on 422, don't redirect to a
  separate error page).
- Fields: everything in the registry/onboarding half of the `cameras`
  table (`Project_Context.md` §3) — name, department, district,
  camera_type, ownership, storage_type, retention_days, vms_url,
  connectivity_status. Leave the grid-catalogue fields (`rtsp_url`,
  `codec`, etc.) read-only/hidden in this form — those are mirrored
  from `/api/ingest`, not something an operator hand-edits.
- Bulk CSV import: a simple upload form on the `/cameras` page, no
  preview/wizard step (per §8) — post the file, show the created/
  skipped/errored counts the API returns.

---

## Phase 8 — Read-only views for Departments & Districts

Since every table in `schema.sql` needs a view this phase (per your
scope), but only `cameras` gets CRUD:

- `/departments` — plain table: name, category, camera count per
  department (a simple `COUNT` join, not a new endpoint if you can
  compute it client-side from the cameras list, otherwise add a small
  `?include=camera_count` param to keep it in one place).
- `/districts` — plain table: all 33 names, camera count per district,
  and a visible "no boundary data yet" note next to `boundary` — don't
  hide that this column is empty, it's a known open item (§9).
- `users` and `status_history` are **not** built this phase — those
  belong to the login and audit-log work you've deferred to Phase 2.

---

## Phase 9 — Placeholder nav stubs for teammates

Add empty "coming soon" page routes + nav links so Model 2 folks (and
your own Phase 2 self) have a URL to build into without you having to
hand-restructure the nav later: `/detections`, `/watchlist`, `/alerts`
— each just renders a `base.html` with a one-line "Model 2 — not built
yet, see docs/API_Contract.md §2" placeholder. Don't wire these to any
real endpoint, they don't exist yet (`docs/DATASET.md` §2 confirms the
Model 2 schema itself isn't even decided).

---

## Phase 10 — Wire up docker-compose

Uncomment and fill in the `app:` service in `infra/docker-compose.yml`
(currently commented-out skeleton), pointing at a `Dockerfile` in
`model1-registry/` (or repo root, your call), `depends_on: db` with
`condition: service_healthy`, port `8000:8000`, `DATABASE_URL` pointing
at the `db` service's internal hostname. Confirm `docker compose up -d`
brings up both `db` and `app` clean from an empty volume, seed included.

---

## Manual QA checklist before you report back

- [ ] Fresh `docker compose down -v && docker compose up -d` → map
      shows real pins from the seeded coordinates, not zero.
- [ ] Every marker's popup shows correct metadata + working VMS link
      (or no link, gracefully, when `vms_url` is null).
- [ ] Department toggle and district filter both work without a full
      page reload.
- [ ] Create → edit → deactivate a camera end to end via the UI, then
      confirm a `status_history` row was written for each change via
      `psql` (this is the trigger doing its job, not app code you wrote
      — just confirming it still fires with no `changed_by` set).
- [ ] CSV bulk import creates rows and reports counts correctly on a
      small test file with one deliberately bad row.
- [ ] `/departments` and `/districts` both render with counts.
- [ ] `/detections`, `/watchlist`, `/alerts` exist as inert placeholders.
- [ ] `docs/API_Contract.md` updated: `DELETE /cameras/{id}` marked ✅.

**Explicitly out of scope for this pass** (your call, next phase):
login/RBAC, `status_history` audit-log UI, `GET /api/v1/gap-analysis`,
`GET /api/v1/export`, custom (non-emoji) marker icon design.