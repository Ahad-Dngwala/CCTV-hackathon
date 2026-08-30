# API Contract

Contract between `model1-registry` and `model2-analytics`, and between
either of them and the frontend. This is the thing that lets both models
get built in parallel without stepping on each other — **if you change an
endpoint's shape, update this file in the same PR.** Stale contract docs
are worse than none (same rule as `Project_Context.md`'s header).

Status markers used below:
- ✅ decided — build against this
- 🚧 draft — shape is likely but not final, confirm before depending on it
- ❓ open — see `Project_Context.md` §9 or ask before building on it

---

## 0. Conventions

- All endpoints are under FastAPI, prefixed `/api/v1/`.
- Auth: JWT bearer token (`Authorization: Bearer <token>`), issued by
  `POST /api/v1/auth/login`. Three roles per `Project_Context.md` §6:
  `dept_admin`, `operator`, `viewer`. Enforced at the router dependency
  level, not just hidden in the UI. ✅
- Errors: standard shape —
  ```json
  { "error": { "code": "string", "message": "string", "details": {} } }
  ```
  🚧 — confirm before both sides start branching on `error.code`.
- Timestamps: ISO 8601 UTC everywhere. No local-time fields.
- Pagination: `?page=&page_size=` on list endpoints, response wraps in
  `{ "items": [...], "total": N, "page": N, "page_size": N }`. 🚧

**Do not confuse this with the external camera-feed API.** The
government camera grid exposes its own read-only catalogue at
`GET http://<host>/api/ingest` (returns each camera's id, location,
codec, live status, and its RTSP/WHEP/HLS URLs) — that's the *source*
Model 2's ingestion adapters poll, not part of our API surface. See
`model2-analytics/README.md` for ingestion notes.

---

## 1. Model 1 — Registry endpoints

Owner: `model1-registry`. Data model reference: `Project_Context.md` §3.

| Method & path | Purpose | Status |
|---|---|---|
| `GET /api/v1/cameras` | List/search/filter cameras (by department, district, status) | ✅ |
| `POST /api/v1/cameras` | Create camera (manual entry) | ✅ |
| `POST /api/v1/cameras/bulk` | CSV bulk import — see `Project_Context.md` §8, no wizard UX | ✅ |
| `GET /api/v1/cameras/{id}` | Camera detail incl. metadata + `vms_url` | ✅ |
| `PATCH /api/v1/cameras/{id}` | Update camera; writes a `status_history` row | ✅ |
| `DELETE /api/v1/cameras/{id}` | Soft delete camera (sets `is_active = false`, trigger timestamps `decommissioned_at`) | ✅ |
| `GET /api/v1/cameras/{id}/history` | Audit trail for one camera | ✅ |
| `GET /api/v1/departments` | List departments | ✅ |
| `GET /api/v1/districts` | List districts incl. PostGIS boundary (GeoJSON) | ✅ |
| `GET /api/v1/gap-analysis` | Coverage-hole report (PostGIS spatial query) per `Project_Context.md` §3 | ✅ |
| `GET /api/v1/export` | CSV/JSON export of filtered camera set | 🚧 |

### Camera object (`shared/schemas`)

```json
{
  "id": "uuid",
  "name": "string",
  "department_id": "uuid",
  "location": { "type": "Point", "coordinates": [lon, lat] },
  "district": "string",
  "camera_type": "string",
  "ownership": "string",
  "connectivity_status": "online | offline | maintenance",
  "storage_type": "string",
  "retention_days": "int",
  "vms_url": "string | null",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```
Matches `Project_Context.md` §3's data model sketch — refine here as
fields get added, don't let this drift from `shared/db/`.

---

## 2. Model 2 — Analytics endpoints

Owner: `model2-analytics`. Data model reference: `Project_Context.md` §4.

| Method & path | Purpose | Status |
|---|---|---|
| `GET /api/v1/detections` | List detections, filterable by camera/plate/time range | 🚧 |
| `GET /api/v1/vehicle-tracks/{plate_number}` | Full route reconstruction for a plate — **this is the Step 4 scored test** | ✅ |
| `GET /api/v1/watchlist` | List watchlist entries | ✅ |
| `POST /api/v1/watchlist` | Add watchlist entry | ✅ |
| `GET /api/v1/alerts` | List alerts, filter by acknowledged/severity | ✅ |
| `POST /api/v1/alerts/{id}/acknowledge` | Ack an alert — writes `acknowledged_by`/`acknowledged_at` | ✅ |
| `WS /api/v1/ws/alerts` | Real-time alert push to dashboard on watchlist match | ✅ |

### Detection object

```json
{
  "id": "uuid",
  "camera_id": "uuid",
  "timestamp": "datetime",
  "detected_plate": "string",
  "confidence": "float",
  "cropped_image_path": "string",
  "vehicle_track_id": "uuid | null"
}
```

### Alert object

```json
{
  "id": "uuid",
  "detection_id": "uuid",
  "watchlist_id": "uuid",
  "alert_type": "string",
  "severity": "string",
  "created_at": "datetime",
  "acknowledged_by": "uuid | null",
  "acknowledged_at": "datetime | null"
}
```

`vehicle_tracks` (plate_number, first_seen, last_seen) is a derived
query over `detections.vehicle_track_id`, not a separately-written table
— see `Project_Context.md` §4.

### WebSocket contract — `/api/v1/ws/alerts` 🚧

Server pushes on every new `alerts` row:
```json
{ "type": "alert.created", "payload": { ...Alert object... } }
```
Confirm reconnect/backoff expectations on the client side before both
sides build against this — same reconnect discipline as the camera
streams (see §3 below), this is our own service, not exempt from it.

---

## 3. Cross-cutting: camera stream ingestion (Model 2 concern)

Model 2's pipeline consumes the government camera grid directly per the
resource doc — not through Model 1's API. Key constraints Model 2's
ingestion code must follow (full detail in
`model2-analytics/README.md`):

- RTSP forced over TCP, never trust `UDP`.
- Read the camera list from the grid's own `/api/ingest`, not
  hard-coded URLs — camera ids can change.
- Drive all timing off PTS (`CAP_PROP_POS_MSEC` / buffer PTS), never
  wall-clock arrival time.
- Reconnect with exponential backoff (~2s → cap 30s), never a tight loop.
- Tolerate decode warnings on join and scene-cut discontinuities at
  loop points — not fatal, not a disconnect.

---

## 4. Open items

- Exact error-code enum — needs a decision once both models have real
  failure cases to enumerate. ❓
- Pagination defaults (page size). ❓
- Synchronous execution for `gap-analysis` (30 cameras / 33 districts runs in <20ms). Revisit background job queue at statewide scale (80,000+ cameras). ✅

Update this section as decisions land — don't leave it stale while the
actual API diverges from what's written here.
