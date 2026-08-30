# Model 1 — Registry & GIS Foundation: Implementation Plan (Phase 2)

Continuation of Phase 1 (map, camera CRUD, department/district views, all
merged and reviewed). This phase covers exactly the three things you
named: login/RBAC, audit log view, gap-analysis. Nothing else. Export
(`GET /api/v1/export`, still 🚧 in `docs/API_Contract.md`) stays deferred,
not in scope here.

Read `Project_Context.md` §6 (auth/RBAC) and the gap-analysis line in §3
before starting — this plan follows both closely and calls out where it
deviates.

---

## Phase 0 — Fixes carried over from the Phase 1 review

Do these first, they're small and otherwise linger indefinitely.

1. **Double form submission bug**, `model1-registry/app/templates/camera_form.html`.
   The `<form>` has `hx-post` / `hx-patch` / `hx-ext="json-enc"` /
   `hx-headers` attributes AND an inline `<script>` that adds its own
   `submit` listener doing a manual `fetch()`. The script's
   `e.preventDefault()` does not stop HTMX's own already-attached
   listener from also firing. The `json-enc` extension script is never
   loaded anywhere in the repo, so HTMX's own request goes out as
   form-urlencoded against a JSON-only endpoint and 422s — the manual
   fetch is what actually saves the camera, every submit currently
   fires two requests. **Fix:** remove `hx-post`, `hx-patch`, `hx-ext`,
   `hx-headers` from the `<form>` tag. The vanilla JS already fully
   owns submission.

2. **`docs/DATASET.md` / `schema.sql` comment now contradict the real
   seed data.** Both still say `district_id` is 16/30 with the rest
   intentionally `NULL` ("not guessed"), `location` is 0/30 `NULL`,
   `department_id` is 0/30 ("not inferable from the catalogue"), and
   explicitly instruct against backfilling by guessing. `seed.sql` now
   assigns all three to every one of the 30 cameras, including the
   ones previously named as too ambiguous to place (Janpath, ONGC
   Office, Mohanpura, BK Mervada, kheram, dhanori, TANKAL). Pick one:
   - **(a)** Update `docs/DATASET.md` §"caveats" and the `cameras`
     table comment block in `schema.sql` to say plainly that
     department/coordinates were enriched for demo completeness and
     are not sourced from the grid catalogue — the honest reframing,
     given you explicitly wanted full demo functionality; or
   - **(b)** Revert the genuinely-unknowable ones back to `NULL`.

   Whichever you pick, the docs and the data have to agree by the end
   of this phase — don't let a reviewer (or the hackathon jury) read
   one and see the other.

3. **`main.py`'s `REPO_ROOT` sys.path hack** computes
   `Path(__file__).resolve().parent.parent.parent`, correct for local
   dev (3 parents from `model1-registry/app/main.py` lands on the repo
   root) but resolves to filesystem root `/` inside the Docker
   container (3 parents from `/app/app/main.py` lands on `/`, not
   `/app`). Currently harmless only because uvicorn's own
   cwd-relative import behavior already makes `/app` importable
   regardless of this hack. Fix: compute `REPO_ROOT` from an
   environment-aware base instead of a fixed parent count, or just
   drop the hack in favor of an `ENV PYTHONPATH=/app` line in
   `infra/Dockerfile` and keep the relative-parent version only for
   the local (non-Docker) path.

4. **Alpine anti-pattern**, `cameras_table_partial.html`'s delete
   button does `onclick="cameraListPage().deactivateCamera('...')"`,
   which calls the Alpine factory function fresh, creating a throwaway
   object disconnected from the real bound instance. It works today
   only because `deactivateCamera` never touches `this.*` reactive
   state. Fix: move the row actions inside the same `x-data` scope and
   use `@click="deactivateCamera('{{ row.cam.id }}')"` properly, or
   make `deactivateCamera` a standalone plain function outside the
   Alpine component if it never needs component state.

5. **Unused Pydantic schemas** — `shared/schemas/department.py` and
   `district.py` are defined but never used; `departments.py` and
   `districts.py` routers hand-build dicts instead
   (`response_model=list[dict]`). Either wire the routers to actually
   return these schemas (cleaner, gets you response validation for
   free) or delete the unused files. Don't leave both versions lying
   around.

6. **Index ordering nit** — `models.py`'s `idx_status_history_camera`
   index doesn't preserve `schema.sql`'s `changed_at DESC`. Minor, fix
   if you're already touching `models.py` this phase for the new audit
   query in Phase 4 below.

---

## Phase 1 — Auth backend

Per `Project_Context.md` §6 and `docs/API_Contract.md` §0: JWT bearer
auth, `POST /api/v1/auth/login`, three roles already defined in
`schema.sql`'s `users.role` CHECK constraint — `dept_admin`, `operator`,
`viewer`. **Do not invent a fourth role** (no "super admin") — the
schema doesn't have one and adding one now means an out-of-band
migration nobody asked for.

New files:
```
model1-registry/app/
  auth/
    security.py       password hashing (passlib[bcrypt]), JWT encode/decode (python-jose)
    dependencies.py   get_current_user(), require_role(*roles) FastAPI dependencies
  routers/
    auth.py           POST /api/v1/auth/login, POST /api/v1/auth/logout (cookie clear)
```

- `POST /api/v1/auth/login`: accepts `username` + `password` (JSON
  body), looks up `users` by username, verifies with
  `passlib.context.CryptContext(schemes=["bcrypt"])`, issues a JWT
  (`sub` = user id, `role`, `department_id`, short expiry, e.g. 8h).
  On success, set the JWT as an **httpOnly cookie**, not a response
  body token for JS to store in `localStorage`. This is a real
  deployed app talking to a plain Jinja2 + HTMX frontend, not a
  sandboxed artifact — httpOnly cookies are the right call here since
  they're not readable by JS and closes off the obvious XSS-token-theft
  path, which matters more for a government surveillance tool than
  almost anything else in this repo.
- `get_current_user()` dependency: reads the cookie, decodes/verifies
  the JWT, loads the `User` row, 401s on anything invalid/expired/
  missing. Every camera-mutation endpoint depends on this from here on.
- `require_role(*roles)`: a dependency factory, `Depends(require_role("dept_admin"))`
  etc., 403s if the current user's role isn't in the allowed set.
- **Department scoping for `dept_admin`**: per §6, "manages that
  department's cameras" — a `dept_admin` can create/edit/deactivate
  cameras only where `camera.department_id == current_user.department_id`.
  Enforce this inside the camera router itself (check ownership after
  loading the row, 403 if it doesn't match), not just at the
  `require_role` level, since `require_role("dept_admin")` alone would
  let a Rajkot dept_admin edit an Ahmedabad camera.
- Update `docs/API_Contract.md`'s auth line from 🚧 to ✅ once this is
  live, same convention as the `DELETE` endpoint last phase.

Enforcement matrix for the existing camera endpoints (update
`cameras.py`'s route decorators accordingly):

| Endpoint | `viewer` | `operator` | `dept_admin` (own dept) | `dept_admin` (other dept) |
|---|---|---|---|---|
| `GET /cameras`, `GET /cameras/{id}` | ✅ | ✅ | ✅ | ✅ (read is unscoped) |
| `POST /cameras`, `PATCH`, `DELETE`, `/bulk` | ❌ 403 | ❌ 403 | ✅ | ❌ 403 |
| `GET /cameras/{id}/history` | ✅ | ✅ | ✅ | ✅ |

`operator` is read-only for Model 1 specifically — §6 describes operator
as "views feeds, acknowledges alerts," both Model 2 concerns. Don't grant
operator camera-write access just because it feels more permissive than
viewer; nothing in the spec asks for that.

---

## Phase 2 — Auth frontend

- `templates/login.html`: plain form, username + password, posts to
  `/api/v1/auth/login`. On success, redirect to `/` (the map). On
  failure, re-render with an inline error, same pattern as the camera
  form's validation errors.
- `pages.py`: add `GET /login` (renders the form) and a
  `require_current_user` page-level dependency that redirects to
  `/login` when there's no valid session cookie — apply it to every
  page route except `/login` itself and the Model 2 placeholders
  (those don't touch real data yet, no need to gate them).
- `base.html` nav bar: show the logged-in username + a Logout link
  (`POST /api/v1/auth/logout`, clears the cookie, redirects to
  `/login`) when authenticated.
- **UI hiding is convenience, not security** — reiterating §6's own
  wording since it's the exact mistake this phase exists to avoid:
  hide the "Add Camera" / "CSV Import" / row edit-delete buttons for
  `viewer`/`operator` roles so the UI doesn't dangle controls that'll
  403, but the actual enforcement already lives in Phase 1's API-layer
  checks. If someone crafts the request by hand, it still 403s
  regardless of what the UI shows.

---

## Phase 3 — Wire up `SET LOCAL app.current_user_id`

`shared/db/triggers.sql`'s `log_camera_changes()` already reads
`current_setting('app.current_user_id', true)` and falls back to `NULL`
cleanly — that fallback was the whole point of building it that way
before login existed. Now that a real logged-in user exists, actually
set it:

- In `cameras.py`'s `create_camera`, `update_camera`, `delete_camera`
  (and the bulk import loop), before `db.commit()`, run:
  ```python
  db.execute(text("SET LOCAL app.current_user_id = :uid"), {"uid": str(current_user.id)})
  ```
  on the same session/transaction, using the `current_user` now
  available via the Phase 1 dependency. `SET LOCAL` only holds for the
  current transaction, so this has to run in the same `db.execute` /
  `db.commit()` cycle as the actual UPDATE, not in a separate
  connection.
- Acceptance: create or edit a camera while logged in as a specific
  user, then check `status_history.changed_by` is that user's UUID,
  not `NULL`.

---

## Phase 4 — Audit log view

**Keep this genuinely small.** `Project_Context.md` §8 explicitly lists
audit trail under "explicitly stubbed, not built, don't let these
expand: DB writes only, a plain table view is enough, no dedicated
audit UI." The trigger-based writes already exist from Phase 1, the
per-camera history endpoint (`GET /api/v1/cameras/{id}/history`)
already exists too — this phase just adds the **global** view.

- New endpoint `GET /api/v1/audit` — `status_history` joined to
  `cameras.name` and `users.username`, most recent first, capped at a
  reasonable limit (e.g. 200 rows or a simple `?limit=` param), no
  pagination machinery beyond that.
- New page `/audit` — one plain HTML table (name, changed field, old
  value, new value, changed by, changed at). No filters, no charts, no
  per-field breakdown UI. If you find yourself building a dashboard
  here, that's scope creep against your own spec — stop and ship the
  table.
- Gate this page behind `require_current_user` (Phase 2) but don't
  role-restrict it further unless you want to — §6 doesn't say viewers
  can't see the audit trail, just that they can't cause entries in it.
- Add a nav link, same style as Cameras/Departments/Districts.

---

## Phase 5 — District boundary data (blocker for gap-analysis)

Same shape of problem as the coordinate gap last phase: gap-analysis
needs real spatial operations (`Project_Context.md` §2 — "buffers,
polygon containment"), and `districts.boundary` is `NULL` for all 33
rows right now, no shapefile sourced (§9's open question). This has to
get resolved before Phase 6 can produce anything real.

- Source Gujarat district boundary polygons. DataMeet's community-
  maintained `india-district-boundaries` GitHub repo is the usual
  free/open source for this at the constituency/district level for
  Indian states — verify current accuracy against Gujarat's actual 33
  districts before trusting it wholesale (some community boundary sets
  lag official district splits, e.g. newer districts like Chhota
  Udepur carved out of older ones).
- Load via `ogr2ogr` (GDAL) straight into the `districts.boundary`
  column: `ogr2ogr -f PostgreSQL PG:"..." districts.geojson -nln districts -append`
  or a small Python script using `shapely` + raw `UPDATE ... SET
  boundary = ST_GeomFromGeoJSON(...)` keyed by matching district name
  to the existing 33 rows. Match by name carefully — same caution as
  the coordinate work, don't silently drop a district whose name in
  the boundary file doesn't exactly match your seeded name (e.g.
  "Ahmadabad" vs "Ahmedabad" spelling variants are a known gotcha with
  these datasets).
- Update `districts_list.html`'s "Boundary data not yet available"
  warning banner once this lands — remove it, and drop the `boundary:
  None` hardcode in `districts.py`'s router, return the real GeoJSON.
- Acceptance: `SELECT name, ST_AsGeoJSON(boundary) FROM districts LIMIT 1;`
  returns a real polygon, not `NULL`.

---

## Phase 6 — Gap-analysis backend

`GET /api/v1/gap-analysis`, per `docs/API_Contract.md` §1 (currently
🚧). This is the one genuinely new spatial-query piece of this phase.

- **State the coverage-radius assumption explicitly, don't hide it.**
  "Coverage" needs a buffer distance around each camera to mean
  anything spatially — pick a number (e.g. 1km for an urban fixed
  camera's effective monitoring radius, this is a judgment call, not a
  fact you're looking up) and say so in the endpoint's docstring and
  in the HLD. This is exactly the kind of unstated-assumption that
  §0's "no fancy tricks, be honest about what's real" philosophy cares
  about — a jury member asking "why 1km?" deserves a documented answer,
  not "the AI picked it."
- Query, per district, per active+non-null-location camera:
  ```sql
  SELECT
    d.id, d.name,
    ST_Area(d.boundary::geometry) AS district_area_m2,
    ST_Area(ST_Difference(
      d.boundary::geometry,
      ST_Union(ST_Buffer(c.location::geometry, :radius_m))
    )) AS uncovered_area_m2,
    COUNT(c.id) AS camera_count
  FROM districts d
  LEFT JOIN cameras c ON c.district_id = d.id AND c.is_active AND c.location IS NOT NULL
  GROUP BY d.id
  ```
  (sketch, not final SQL — validate the `ST_Union`/`ST_Buffer` inside
  an aggregate actually behaves as expected in SQLAlchemy Core/raw SQL
  before committing to this shape; a district with zero cameras needs
  `uncovered_area_m2 == district_area_m2`, handle the `ST_Union` of an
  empty set case explicitly rather than letting it error).
- Response: per-district `{name, camera_count, coverage_pct, uncovered_geojson}` —
  the uncovered polygon itself as GeoJSON, so it can be drawn on the
  map as an overlay, not just a number in a table.
- Sync response is fine at this scale (30 cameras, 33 districts) —
  `docs/API_Contract.md`'s open question about background-job-vs-sync
  only matters at real statewide volume (§7's scale-plan concern, not
  a Phase 2 concern). Note this in the endpoint's docstring so a future
  reader doesn't wonder why it's not a job queue.
- Update `docs/API_Contract.md`: mark this ✅ once built, and resolve
  its "sync or background job" open question with a one-line note
  ("sync, revisit at scale — see §7").

---

## Phase 7 — Gap-analysis frontend

- New page `/gap-analysis`: a ranked table, worst-covered district
  first (lowest `coverage_pct`), columns: district, camera count,
  coverage %, area. Plain table, consistent with the audit page's
  restraint — this isn't the place to build a dashboard either.
- Map overlay: a toggle-able layer on the main map page (`/`) that
  draws each district's uncovered-area polygon (from Phase 6's
  response) as a shaded overlay, so a low-coverage district is visible
  spatially, not just as a number in a table. Reuse the existing
  Leaflet map instance in `map.js` — add a `loadGapAnalysis()` +
  `renderGapOverlay()` following the same fetch-and-redraw pattern
  already established there, don't introduce a second map instance.
- Nav link, same pattern as the others.

---

## Manual QA checklist before you report back

- [ ] Login as each of the three roles, confirm the enforcement matrix
      in Phase 1 holds for every camera endpoint, not just the happy path.
- [ ] Log in as a `dept_admin` for one department, confirm editing a
      camera belonging to a *different* department 403s.
- [ ] Create/edit/deactivate a camera while logged in, confirm
      `status_history.changed_by` is populated with the real user id.
- [ ] `/audit` shows real rows across multiple cameras, most recent
      first, capped, no pagination controls needed.
- [ ] `districts.boundary` is populated for all 33 rows, spot-check a
      couple of district names against the actual polygon shape (e.g.
      Kutch should look enormous compared to Botad).
- [ ] `/gap-analysis` returns a ranked list and the map overlay draws
      without erroring on a district that currently has zero cameras.
- [ ] `docs/API_Contract.md` updated: auth ✅, gap-analysis ✅, its
      sync-vs-job question resolved.
- [ ] All six Phase 0 carry-over fixes actually applied, not just
      acknowledged.

**Explicitly out of scope for this pass:** `GET /api/v1/export`,
pagination/error-shape standardization (still 🚧 elsewhere in the
contract doc, unrelated to this phase's three items), custom marker
icons, WebSocket push (Model 2), anything under Model 2 at all.
