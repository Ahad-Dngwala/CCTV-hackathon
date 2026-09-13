# Model 1 — Registry & GIS Foundation

Model 1 is the part of Sentinel that answers a question nobody in this
problem space has ever had a straight answer to: *what cameras actually
exist, where are they, whose are they, and can we prove that record is
trustworthy?* Twenty-six departments running independent camera estates
means twenty-six independent answers to that question today — most of
them living in a spreadsheet, if they exist at all. Model 1 replaces
that with one registry: a single source of truth for camera metadata,
laid over a real GIS, with every change to that truth logged and
attributable.

It deliberately does **not** stream or store video. That's Model 2 and
Model 3's job, and the boundary is load-bearing, not incidental — see
[§7](#7-what-model-1-deliberately-does-not-do) before you go looking for
a video buffer in here.

This document covers the feature itself: data model, API surface, the
GIS/gap-analysis engine, and the UI built on top of it. Two adjacent
concerns get their own documents on purpose, because they're bigger
than any one model and will keep growing as Model 2/3 mature:

- **[docs/PLATFORM.md](../PLATFORM.md)** — the shared FastAPI app shell
  (boot sequence, routing, the Model 2 router auto-loader) that Model 1's
  code happens to live inside.
- **[docs/SECURITY.md](../SECURITY.md)** — auth, RBAC, audit trail, and
  the rest of the platform's cybersecurity posture, written cross-model
  since Model 2 and Model 3 both plug into it.

---

## 1. Architecture at a glance

```
Department CCTV Assets                Onboarding & Validation
  (cameras, locations,        ──────▶    bulk CSV · manual entry
   ownership, retention)                  · grid API sync
                                                  │
                                                  ▼
                                        Central Registry
                                    (PostgreSQL + PostGIS,
                                     shared/db/schema.sql)
                                                  │
                          ┌───────────────────────┼───────────────────────┐
                          ▼                       ▼                       ▼
                  GIS Dashboard            REST API (/api/v1)      Audit Trail
              (Leaflet map, filters,     cameras · departments      (status_history,
               clustering, popups)        · districts · gap-        DB-trigger-written)
                                              analysis
```

Everything above the database is FastAPI + Jinja2 + HTMX/Alpine — no
build step, no bundler, server-rendered HTML with just enough client-side
JS to feel alive. That was a deliberate call against the "suggested"
React frontend in `HackathonPortal.md`'s own stack recommendation, and
the reasoning is about where the state actually lives, not about
saving time. Almost everything on these pages — which cameras exist,
who owns them, what status they're in — is a row in Postgres that any
`dept_admin` on the platform can change at any moment. A React app
would need its own client-side copy of that state to render anything,
and now there are two copies of the truth that can quietly drift apart
the instant two people are looking at the same district at once. HTMX
sidesteps that by not keeping a copy at all: a save re-renders the one
table row or map layer that changed, straight from whatever the
database actually says right now, every time. React earns its keep
when the state is genuinely the client's own — a draft, an open modal,
a toggle — and this app already keeps that kind of state in Alpine
locally where it belongs; it's the shared, multi-writer, RBAC-scoped
state that's better off never leaving the server that owns it. The
real trade-off is losing React's ecosystem of ready-made map/table
components and writing a bit more vanilla JS for the Leaflet layer by
hand — a fair price for one less place a stale department list can
hide.

---

## 2. Data model

Four tables carry the whole feature. Full DDL lives in
`shared/db/schema.sql`; a visual ER diagram is at
`docs/schema_erd.svg`. SQLAlchemy models are in `shared/db/models.py`,
under the block explicitly marked `# ── Model 1 — Registry & GIS ──`.

| Table | Owns | Notes |
|---|---|---|
| `departments` | Department name + category | Read-only from Model 1's side; seeded, not user-managed yet |
| `districts` | Name + `MULTIPOLYGON` boundary | See [§3](#3-the-district-boundaries-a-real-data-problem-not-a-toy-one) |
| `cameras` | Registry metadata + geodesic location | The core table — see below |
| `status_history` | One row per tracked field change | Written by a Postgres trigger, not application code |

`cameras` carries three distinct groups of columns, and it's worth
knowing the seam between them even though they live in one table:

1. **Registry fields** — the actual Model 1 payload: `department_id`,
   `district_id`, `location` (a PostGIS `GEOGRAPHY(POINT, 4326)`),
   `camera_type`, `ownership`, `storage_type`, `retention_days`,
   `vms_url`, `connectivity_status`, `is_active` / `decommissioned_at`.
2. **Grid-sync fields** — `source_grid_id`, `codec`, `stream_width`,
   `stream_height`, `stream_fps`, `bitrate_kbps`, `rtsp_url`,
   `whep_url`, `hls_url`, `grid_synced_at`. These are populated by
   Model 2's ingestion poller reading the government camera grid's own
   catalogue API, not by anything in this package. Model 1's registry
   API happily reads and returns them (a camera onboarded through Model
   2's grid sync shows up in Model 1's map like any other), it just
   never writes them.
3. **`vms_system_id`** — a foreign key into `vms_systems`, which is the
   join point Model 3's federation layer uses to tie a registry row to
   a specific external VMS connection. Model 1 doesn't populate or read
   this column either; it exists here because `cameras` is the one
   table every model needs to agree on.

That layering is why `cameras` looks bigger than a pure GIS registry
table "should" be — it's shared infrastructure wearing three hats, and
the schema comment in `shared/db/models.py` says as much: *"Do NOT add
columns here that aren't in schema.sql. The DB is the source of truth;
this file describes it, it doesn't extend it."*

`connectivity_status` is constrained at the database level (`CHECK
... IN ('online', 'offline', 'maintenance')`) — invalid values are
rejected by Postgres itself, not just validated in Pydantic. That
matters once you remember Model 2's grid poller and Model 3's adapters
also write to this table outside of Model 1's own API path.

---

## 3. The district boundaries: a real data problem, not a toy one

The 33 district polygons in `districts.boundary` aren't hand-drawn or
approximated — they're sourced from Esri India's public *India
Administrative Boundaries 2024* dataset, matched to Gujarat's districts
by their official LGD (Local Government Directory) codes so the
mapping is unambiguous rather than name-matched. Raw, that dataset is
generous with vertices — administrative boundary shapefiles usually
are, since they're built for cadastral accuracy, not for a browser to
render 33 times on every page load.

The fix was Shapely's `coverage_simplify()`, run at a 0.002° tolerance
(roughly 200m at Gujarat's latitude) across the whole district
coverage at once rather than polygon-by-polygon, which is the part
that actually matters: simplifying adjacent districts independently
treats each shared border as two separate edges that round differently
under simplification, drifting them apart. `coverage_simplify` treats
the whole set as one topology and simplifies each shared border once,
so neighboring districts keep the same edge between them rather than
two independently-rounded approximations of it — which is what makes
the result usable input for the gap-analysis math in
[§5](#5-gap-analysis-the-postgis-part) rather than just a
nicer-looking map layer. That trip
took the boundary set from a multi-megabyte source shapefile down to
roughly 150KB of `MULTIPOLYGON` WKT — the single `INSERT INTO
districts` statement in `shared/db/seed.sql` — small enough to seed on
every fresh database and light enough for Leaflet to render all 33
districts without stuttering, while keeping enough fidelity that the
map still looks like Gujarat and not a politician's approximation of
it.

The alternative here was to serve boundaries as a static GeoJSON file
and skip the database entirely — simpler, and it's a legitimate choice
for a pure map layer. It wasn't the right one here because gap-analysis
needs the boundary *in the database*, as a real `geography` column
PostGIS can run `ST_Difference` and `ST_Area` against — a static file
would mean maintaining the same geometry in two places and one of them
inevitably drifting from the other.

---

## 4. API reference

Base path: `/api/v1`. All endpoints require an authenticated session
(httpOnly JWT cookie or `Authorization: Bearer` header — see
[docs/SECURITY.md](../SECURITY.md)) unless noted. Full request/response
shapes are defined in `shared/schemas/camera.py`,
`shared/schemas/department.py`, and `shared/schemas/district.py`; this
section documents behavior, not just shape.

### 4.1 Cameras — `app/routers/cameras.py`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/cameras` | any role | List/filter cameras |
| `POST` | `/cameras` | `dept_admin` | Manual onboarding |
| `POST` | `/cameras/bulk` | `dept_admin` | CSV bulk onboarding |
| `GET` | `/cameras/{id}` | any role | Camera detail |
| `PATCH` | `/cameras/{id}` | `dept_admin` | Partial update |
| `DELETE` | `/cameras/{id}` | `dept_admin` | Soft delete |
| `GET` | `/cameras/{id}/history` | any role | Per-camera audit trail |

**`GET /cameras`** — filters: `department_id`, `district_id`,
`connectivity_status`, `is_active` (defaults to active-only when
omitted), `limit` (1–1000, default 100), `offset`. Returns the full
`Camera` schema per row, with `department_name`/`district_name` already
joined in and `location` translated from PostGIS geography to a plain
GeoJSON `Point`:

```json
GET /api/v1/cameras?district_id=<uuid>&connectivity_status=online

[
  {
    "id": "c3f1...-...-...",
    "name": "06 Timbavadi Gate",
    "department_id": "b8a2...",
    "department_name": "Home Department (Police)",
    "district_id": "d901...",
    "district_name": "Junagadh",
    "location": { "type": "Point", "coordinates": [70.4521, 21.5222] },
    "location_label": "Timbavadi gate-Junagadh",
    "camera_type": "PTZ",
    "ownership": "government",
    "connectivity_status": "online",
    "storage_type": "cloud",
    "retention_days": 15,
    "vms_url": null,
    "is_active": true,
    "source_grid_id": "06",
    "codec": "h264",
    "created_at": "2026-08-01T09:12:00Z",
    "updated_at": "2026-08-30T14:03:11Z"
  }
]
```

**`POST /cameras`** — `dept_admin` only, and scoped: a department-bound
admin can't create a camera in someone else's department (`403`), and
if they leave `department_id` blank it's filled in as their own rather
than left null — a camera with no owning department is a camera no
`dept_admin` could ever manage afterward, which is a worse failure mode
than assuming the obvious default.

**`POST /cameras/bulk`** — CSV onboarding. Deliberately the simplest
thing that could work: `.csv` only, 5MB cap (checked twice — once
against the declared upload size, once against the actual byte count,
since `UploadFile.size` isn't always trustworthy), one row per camera,
department/district resolved by name lookup rather than requiring the
caller to know internal UUIDs. Each row is inserted in its own
`SAVEPOINT`, so one malformed row (bad `retention_days`, an unknown
department name, whatever) fails and is reported by row number without
rolling back the rows around it. Response is a plain tally:

```json
{ "created": 27, "skipped": 0, "errored": 3,
  "errors": ["Row 4: missing 'name'", "Row 11: cannot import camera for another department", "..."] }
```

There's no upload wizard, no preview-before-commit step, and that's a
conscious scope cut rather than an oversight — see
`Project_Context.md`'s explicit list of what's stubbed for this build.
The honest trade-off: a wizard would catch row-level mistakes before
they hit the database and give a friendlier error surface, at the cost
of a multi-step UI this timeline didn't have room for. What's here
instead is a still-safe fallback — nothing commits until the file's
been fully parsed and validated row-by-row, so a bad file degrades to
"fewer rows imported," never to a half-written camera.

Worth being precise about what this endpoint onboards, since a
similarly-named onboarding path exists one layer up: this creates
`cameras` rows directly, with `vms_system_id` left `NULL` — a manually
registered camera, not tied to any VMS integration. That's a different
object from a `vms_systems` row (a VMS *connection* — vendor, protocol,
which department runs it), which Model 3 lets a `dept_admin` register
separately. The two aren't competing ways to do the same thing: this
endpoint is for "this camera exists, here's its metadata," Model 3's is
for "this department also runs a VMS we should know about." A camera
onboarded here can still be linked to a VMS system later by setting its
`vms_system_id` — Model 1's own API just doesn't expose that field for
editing yet, since nothing has needed it to until now.

**`PATCH /cameras/{id}`** — partial update (`exclude_unset`, so
omitted fields are left alone, not nulled). `latitude`/`longitude` are
accepted as plain floats and translated into the PostGIS point
server-side. A `dept_admin` can't move a camera into a different
department than the one they administer, and can't touch a camera
that isn't theirs to begin with — both return `403`, matching the
scoping rule in `POST`.

**`DELETE /cameras/{id}`** — soft delete only (`is_active = false`).
A Postgres trigger (`shared/db/triggers.sql`) stamps
`decommissioned_at` and writes the `status_history` row automatically
— the API layer doesn't do either of those itself, which is the point:
audit logging that depends on every call site remembering to log is
audit logging that will eventually have a gap.

**`GET /cameras/{id}/history`** — returns every `status_history` row
for that camera, most recent first. Worth flagging plainly rather than
glossing over: this endpoint checks *authentication* but not
*department scope* — any logged-in user, including a `viewer`, can pull
the change history for any camera by ID. That's a narrower surface
than it sounds (you already need the camera's UUID, and the UI never
links to another department's camera detail for a scoped user), but
it's a real asymmetry against the *global* `/audit` endpoint below,
which does enforce both role and department scope. If cross-department
history visibility ever needs tightening, this is the specific line to
change.

### 4.2 Departments & Districts — read models

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/departments` | any role | List departments + active camera count |
| `GET` | `/districts` | any role | List districts + camera count + boundary GeoJSON |

Both are intentionally read-only from Model 1's API today — department
and district records are seed data, not something the UI lets you
create yet. `/districts` runs `ST_AsGeoJSON` server-side so the map
never has to convert PostGIS WKB itself; at 33 rows this is cheap
enough to do on every request rather than caching it.

### 4.3 Gap analysis — `app/routers/gap_analysis.py`

```
GET /api/v1/gap-analysis?radius_km=1.0
```

`radius_km` (default `1.0`, range `0.1`–`10.0`) is the effective
monitoring radius assumed around every active camera — not a spec read
off the camera itself, but the planning assumption that a camera
watches its surroundings out to roughly this distance, which is what
turns a set of points into an actual coverage area. Returns, per
district, sorted worst-covered first:

```json
{
  "district_id": "...",
  "district_name": "Dahod",
  "camera_count": 1,
  "district_area_sq_km": 3641.44,
  "uncovered_area_sq_km": 3627.91,
  "coverage_pct": 0.37,
  "uncovered_geojson": { "type": "MultiPolygon", "coordinates": [...] }
}
```

See [§5](#5-gap-analysis-the-postgis-part) for how the number is
actually computed.

### 4.4 Audit — `app/routers/audit.py`

```
GET /api/v1/audit?limit=200
```

Role-gated to `dept_admin` and `operator` (`viewer` gets `403` —
a read-only account isn't meant to pull a cross-department change feed
in one request). Department-bound callers see only their own
department's history; callers with no `department_id` (global staff)
see everything. This is the endpoint `/cameras/{id}/history` is *not*
as strict as — see the callout in [§4.1](#41-cameras--approuterscamerasp).

### 4.5 Auth — `app/routers/auth.py`

```
POST /api/v1/auth/login   { "username": "...", "password": "..." }
POST /api/v1/auth/logout
```

Not a Model 1 feature per se (every model sits behind it), documented
in full in [docs/SECURITY.md](../SECURITY.md).

---

## 5. Gap analysis: the PostGIS part

This is the one place in Model 1 that's doing real spatial computation
rather than CRUD-with-a-map-on-top, and it's a good example of what
"GIS foundation" is supposed to mean beyond pins on a map:

1. Every active camera with a location gets a circular buffer —
   `ST_Buffer(location::geography, radius_meters)` — computed in
   `geography` mode, which means the buffer radius is a true geodesic
   distance (accounting for the earth's curvature) rather than a
   flat-plane approximation.
2. All of one district's camera buffers are merged with `ST_Union`.
3. That merged coverage shape is subtracted from the district's own
   boundary with `ST_Difference` — what's left over is the uncovered
   area, as an actual polygon, not just a percentage.
4. `ST_Area` on the result (cast back to `geography`) gives uncovered
   km², divided against the district's total area for a coverage
   percentage.

The one deliberate simplification worth naming: steps 2–3 run in
`geometry` mode (raw lat/lng math) rather than `geography` mode, after
the buffers themselves are computed geodesically. Doing the union and
difference in flat coordinate space introduces a small distortion over
large polygons — negligible at Gujarat's scale and at a 1km monitoring
radius, but not geodesically exact. The more rigorous version would
reproject everything into a local planar system (UTM zone 43N,
`EPSG:32643`, covers Gujarat cleanly) before the union/difference step
and back to `4326` for the response — that's the natural next
refinement if this ever needs to hold up at a scale where the
distortion stops being negligible, and it's a contained change, not a
redesign: it touches this one query, not the schema or the API shape.

The whole thing runs as a single SQL statement — one `GROUP BY`
across all 33 districts, buffered/unioned/differenced inside Postgres
itself — not a loop in application code that pulls cameras out district
by district and does the geometry in Python. That's the difference
that actually matters for scale: PostGIS's buffer/union/difference
operations are implemented in C and built for exactly this kind of
set-based spatial aggregation, so handing the whole computation to one
query lets Postgres's own planner parallelize and optimize it, rather
than paying per-row overhead for every camera in every district
separately. At the district/camera counts in play today, and comfortably
past them, that's not a close call.

What this endpoint doesn't yet do is *cache* — it recomputes the same
answer on every request, even when nothing about the camera set has
changed since the last one. That's the one real refinement left on the
table, and it's a small one: store each district's last result and
invalidate it when a camera in that district is added, moved, or
deactivated, rather than recomputing all 33 on every page view — a
natural next step once traffic on this endpoint outgrows "recompute on
page load," not a redesign of the query itself.

---

## 6. Pages

| Path | Template | Notes |
|---|---|---|
| `/` | `map.html` | Leaflet + OSM base layer, marker clustering (`Leaflet.markercluster`), department/district/status filters, click-through popups with full camera metadata and an optional outbound link to the camera's native VMS |
| `/cameras` | `cameras_list.html` + `cameras_table_partial.html` | HTMX-swapped, sortable/filterable table over the same filters as the map |
| `/cameras/new`, `/cameras/{id}/edit` | `camera_form.html` | Alpine.js modal form; only rendered for `dept_admin`, and only offers departments/districts the caller is actually allowed to save against — mirrors the API's own 403 rules instead of rendering a form guaranteed to fail on submit |
| `/departments` | `departments_list.html` | Read view |
| `/districts` | `districts_list.html` | Read view |
| `/audit` | `audit.html` | Same role/department scoping as `GET /api/v1/audit`; a `viewer` is redirected home rather than shown an empty table |
| `/gap-analysis` | `gap_analysis.html` | Renders the §5 computation as a map overlay + per-district table |

Custom marker iconography (status- and department-specific, not a
tinted default Leaflet pin) is the one place UI polish was deliberately
front-loaded over feature count — the map is the page an operator
actually watches during a shift, and a screen full of identical pins
tells them nothing until they click each one; distinct icons per
department and connectivity status turn "is anything offline right
now" into something answerable at a glance, before a single popup
opens.

---

## 7. What Model 1 deliberately does not do

- **No centralized video.** Registry-only, by design — this is the
  line `HackathonPortal.md`'s own Model 1 description draws
  ("does not involve centralised live video streaming or recording"),
  and it's the reason `vms_url` exists as an optional outbound link
  rather than an embedded player.
- **No live stream relay**, even though one lives in this same
  package. `app/routers/streams.py` (the MJPEG/HLS relay behind `/live`)
  and the shared page router's Model 2/3 routes are Model 2 and Model 3
  concerns that happen to be wired into the same FastAPI app for
  deployment convenience. They're documented separately: the shared
  app shell in [docs/PLATFORM.md](../PLATFORM.md), and what specifically
  belongs to each other model in [`docs/model2/NOTES.md`](../model2/NOTES.md) /
  [`docs/model3/NOTES.md`](../model3/NOTES.md) (working notes, not
  polished documentation yet).
- **No department/district management API.** Both are read-only from
  Model 1 today; they're seed data, not something the current UI
  creates or edits.

---

## 8. Testing

`model1-registry/tests/` runs against a real Postgres + PostGIS
database (`sentinel_test`), not SQLite or mocks — the feature set here
leans on PostGIS geography functions and Postgres triggers with no
SQLite equivalent, so anything less wouldn't actually exercise the code
paths that matter (RBAC scoping, geodesic gap-analysis math, the
audit-log trigger).

```bash
cd model1-registry
pip install -r requirements-dev.txt
pytest
```

Each test runs inside its own transaction + `SAVEPOINT`, rolled back
afterward — so tests can freely create/update/delete through the real
API without leaking state between runs or needing a reseed per test.
Coverage: auth (login/logout/role checks), camera CRUD + department
RBAC (including cross-department 403s and bulk import), districts
(with a regression guard for the empty-`districts`-table seed bug),
and gap-analysis geodesic math (coverage bounds, radius scaling,
real-world area sanity checks per district). Full setup notes —
`psql` path issues, missing Postgres extensions, what to do if a run
hangs — are in `model1-registry/README.md`.
