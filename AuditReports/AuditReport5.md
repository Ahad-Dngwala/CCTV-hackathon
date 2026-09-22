# SECURITY AND CODE AUDIT -- Revision 2 (Updated Repository)

**Audit Date:** 2026-09-05
**Auditor:** Senior Engineering Audit (Automated Forensic)
**Repository:** `Ahad-Dngwala/CCTV-hackathon`
**Scope:** Full repository traversal of every source file, SQL schema, Docker configuration, dependency, test, and AI pipeline component.

---

# 1. Executive Summary

This audit represents a complete re-examination of the Sentinel Gujarat CCTV Integration platform after recent development iterations. The repository has evolved substantially: a real AI pipeline (YOLO vehicle detection, IoU/centroid tracking, DetectionWriter persistence) is now partially implemented and functional. However, the core P0 security defects from the first audit remain unfixed on the live codebase. All watchlist and grid sync endpoints are still completely unauthenticated. The hard-coded SECRET_KEY and database credentials are still present in `config.py`. Hard-coded RTSP credentials containing a cleartext email and password are embedded in multiple source files. The system remains fundamentally unsafe for any deployment beyond a closed development environment.

**Total Confirmed Findings:** 28
**CRITICAL:** 5 | **HIGH:** 8 | **MEDIUM:** 9 | **LOW:** 4 | **INFO:** 2

---

# 2. Repository Architecture Understanding

The system consists of:
- **Model 1 (Registry/GIS):** FastAPI application at `model1-registry/app/` -- Camera CRUD, RBAC, PostGIS gap analysis, Jinja2 HTML pages, JWT authentication via httpOnly cookies.
- **Model 2 (Analytics/Viewer):** Mounted under the same FastAPI app at `model2-analytics/app/` -- Live camera grid, watchlist CRUD, WebSocket-driven detection dashboard, catalogue sync.
- **AI Pipeline:** `model2-analytics/pipeline/` -- YOLO-based vehicle detection (`vehicle_detector.py`), IoU/centroid tracking (`frame_tracker.py`), database persistence (`writer.py`), multi-stream runner (`runner.py`), pre-recorded video worker (`video_worker.py`).
- **Database:** PostgreSQL 16 + PostGIS 3.4 + pgvector. Schema at `shared/db/schema.sql`, ORM at `shared/db/models.py`.
- **Infrastructure:** Docker Compose at `infra/docker-compose.yml`, plus MediaMTX for RTSP/WHEP/HLS relay.

---

# 3. Security Score

**Overall Security Score: 2.5 / 10**
**Overall Production Readiness: 2 / 10**

---

# 4. Security Findings

## [SEC-01] Hard-Coded JWT Secret Key and Database Credentials

**Severity:** CRITICAL
**Category:** OWASP A02 Security Misconfiguration / CWE-798 Hard-coded Credentials
**Confidence:** CONFIRMED

**File:** `model1-registry/app/config.py`
**Function/Class/Endpoint:** `Settings`
**Lines:** `11-16`

**Evidence:**
```python
class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://sentinel:sentinel_dev@127.0.0.1:5432/sentinel"
    ...
    DEBUG: bool = True
    SECRET_KEY: str = "sentinel-secret-key-hackathon-2026-secure"
```

**What is wrong:** The JWT signing key and database URL with credentials are hard-coded as default values. `DEBUG` defaults to `True`.

**Why it happens:** Pydantic `BaseSettings` falls back to the default when no environment variable is present.

**Attack / Failure Scenario:** Any person reading this public GitHub repository can forge a JWT for `admin_home` (or any user) with: `jwt.encode({"sub": "<admin UUID>", "role": "dept_admin"}, "sentinel-secret-key-hackathon-2026-secure", algorithm="HS256")`. This grants full administrative access.

**Impact:** Total authentication bypass. Complete system compromise.

**Affected Components:** All authenticated endpoints, database.

**Root Cause:** Configuration defaults include production-sensitive values.

**Recommended Fix:** Remove all defaults for `DATABASE_URL` and `SECRET_KEY`. Set `DEBUG: bool = False`.

**Suggested Implementation:**
```python
class Settings(BaseSettings):
    DATABASE_URL: str     # Required -- crash if missing
    SECRET_KEY: str       # Required -- crash if missing
    DEBUG: bool = False
```

**Regression Test:** Test that `Settings(_env_file=None)` raises `ValidationError` when `SECRET_KEY` is unset.

**Verification:** Inspect `config.py` line 16 and confirm no default value exists.

**Status Since Last Audit:** A local fix was applied in a previous session but the live repository file (`config.py` lines 11-16) still contains the hard-coded defaults.

**References:** OWASP A02, CWE-798.

---

## [SEC-02] Hard-Coded RTSP Credentials in Source Code

**Severity:** CRITICAL
**Category:** OWASP A02 Security Misconfiguration / CWE-798 Hard-coded Credentials
**Confidence:** CONFIRMED

**File:** `model2-analytics/app/routers/grid.py`
**Function/Class/Endpoint:** `_build_stream_urls()`
**Lines:** `48`

**Evidence:**
```python
rtsp = f"rtsp://kushwahavarun86%40gmail.com:77YY-GGER-EW2M@103.250.160.189:8554/stream/{cam_tag}"
```

**Also found in:**
- `model2-analytics/pipeline/runner.py` lines `36, 42` (same credentials)
- `model2-analytics/pipeline/config.py` (CAM04_RTSP, CAM22_RTSP)

**What is wrong:** A real email address (`kushwahavarun86@gmail.com`) and password (`77YY-GGER-EW2M`) for the RTSP gateway are embedded directly in committed source code.

**Why it happens:** Stream URLs with embedded credentials were copied directly into the code instead of being loaded from environment variables or the database.

**Attack / Failure Scenario:** Anyone with access to the GitHub repository can connect to the RTSP gateway using these credentials and access all 30 live camera feeds. The email address can also be used for targeted phishing.

**Impact:** Unauthorized access to all CCTV streams. Credential compromise. Potential regulatory violation (surveillance data exposure).

**Root Cause:** No credential management strategy for stream authentication.

**Recommended Fix:** Move RTSP username and password to environment variables. Construct URLs at runtime using `settings.GRID_RTSP_USER` and `settings.GRID_RTSP_PASS` (which already exist in `config.py` lines 27-28 but are not used).

**Suggested Implementation:**
```python
def _build_stream_urls(cam: CameraModel) -> tuple[str, str, str]:
    from app.config import settings
    source_id = cam.source_grid_id or str(cam.id)[:8]
    cam_tag = _format_cam_tag(source_id)
    user = settings.GRID_RTSP_USER
    passwd = settings.GRID_RTSP_PASS
    host = settings.GRID_RTSP_HOST
    auth = f"{user}:{passwd}@" if user else ""
    rtsp = f"rtsp://{auth}{host}:{settings.GRID_RTSP_PORT}/stream/{cam_tag}"
    whep = f"http://{host}:{settings.GRID_WHEP_PORT}/stream/{cam_tag}/whep"
    hls = f"https://{settings.GRID_CDN_HOST}/{cam_tag}/index.m3u8"
    return rtsp, whep, hls
```

**Regression Test:** `grep -rn "77YY-GGER" .` must return zero results.

**Verification:** Confirm no credentials appear in any committed file.

**References:** OWASP A02, CWE-798, CWE-312.

---

## [SEC-03] All Watchlist Endpoints Completely Unauthenticated

**Severity:** CRITICAL
**Category:** OWASP A01 Broken Access Control / OWASP API5 Broken Function Level Authorization
**Confidence:** CONFIRMED

**File:** `model2-analytics/app/routers/watchlist.py`
**Function/Class/Endpoint:** ALL five endpoints
**Lines:** `47-196`

**Evidence:**
```python
@router.get("", response_model=List[VehicleWatchlistResponse])
def list_watchlist_vehicles(
    # ... filters ...
    db: Session = Depends(get_db),   # <-- NO get_current_user / require_role
):

@router.post("", response_model=VehicleWatchlistResponse, status_code=status.HTTP_201_CREATED)
def create_watchlist_vehicle(
    payload: VehicleWatchlistCreate,
    db: Session = Depends(get_db),   # <-- NO authentication
):

@router.patch("/{id}", response_model=VehicleWatchlistResponse)
def update_watchlist_vehicle(
    id: uuid.UUID,
    payload: VehicleWatchlistUpdate,
    db: Session = Depends(get_db),   # <-- NO authentication
):

@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_watchlist_vehicle(
    id: uuid.UUID,
    db: Session = Depends(get_db),   # <-- NO authentication
):
```

**What is wrong:** None of the five watchlist endpoints include any authentication dependency. Any unauthenticated HTTP client can list, create, modify, and delete surveillance watchlist entries.

**Why it happens:** The `Depends(get_current_user)` or `Depends(require_role(...))` was never added to the Model 2 router.

**Attack / Failure Scenario:** `curl -X POST http://target:8000/api/v1/watchlist/vehicles -d '{"plate_number":"GJ01AB1234","category":"stolen","description":"test attack entry"}' -H "Content-Type: application/json"` -- creates a watchlist entry without any login.

**Impact:** An attacker can inject fake watchlist entries, causing false alerts and wasted law enforcement resources. They can also delete legitimate watchlist entries to suppress alerts for actual stolen/wanted vehicles.

**Affected Components:** Watchlist API, alert generation, law enforcement operations.

**Root Cause:** Authentication dependency was never wired into Model 2 routers.

**Recommended Fix:** Add `current_user: UserModel = Depends(require_role("dept_admin", "operator"))` to every watchlist endpoint.

**Regression Test:** Test that an unauthenticated `POST /api/v1/watchlist/vehicles` returns HTTP 401.

**References:** OWASP A01, OWASP API5.

---

## [SEC-04] Grid Sync and Ingest Catalogue Endpoints Unauthenticated

**Severity:** HIGH
**Category:** OWASP A01 Broken Access Control
**Confidence:** CONFIRMED

**File:** `model2-analytics/app/routers/grid.py`
**Function/Class/Endpoint:** `get_grid_streams()`, `sync_ingest_catalogue()`, `get_ingest_catalogue()`
**Lines:** `58-114` (streams), `120-150` (ingest), `156-187` (sync)

**Evidence:** None of these functions include any `Depends(get_current_user)`.

**What is wrong:** Stream URLs (including RTSP credentials), camera metadata, and the sync endpoint that can modify database state are all fully accessible without authentication.

**Impact:** Unauthenticated exposure of the entire camera network topology and stream credentials. The sync endpoint enables SSRF (see SEC-05).

**Recommended Fix:** Add authentication to all three endpoints.

---

## [SEC-05] SSRF via Unauthenticated Grid Sync Endpoint

**Severity:** HIGH
**Category:** OWASP A10 SSRF / CWE-918
**Confidence:** CONFIRMED

**File:** `model2-analytics/app/routers/grid.py`
**Function/Class/Endpoint:** `sync_ingest_catalogue()`
**Lines:** `156-187`

**Evidence:**
```python
@router.post("/api/v1/grid/sync", response_model=CatalogueSyncResponse)
def sync_ingest_catalogue(payload: CatalogueSyncRequest, db: Session = Depends(get_db)):
    # ...
    cam.rtsp_url = item.rtsp_url or cam.rtsp_url
```

And in `pipeline/ingest.py` line 67:
```python
cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
```

**What is wrong:** An unauthenticated attacker can POST to `/api/v1/grid/sync` and set `rtsp_url` to any value (e.g., `rtsp://169.254.169.254/latest/meta-data`). The background pipeline worker subsequently opens a TCP connection to this URL via FFmpeg.

**Impact:** Server-Side Request Forgery into internal network.

**Recommended Fix:** Authenticate the endpoint. Validate that `rtsp_url` matches allowed host/scheme patterns before storing.

---

## [SEC-06] Camera List and Detail Endpoints Unauthenticated

**Severity:** HIGH
**Category:** OWASP A01 Broken Access Control
**Confidence:** CONFIRMED

**File:** `model1-registry/app/routers/cameras.py`
**Function/Class/Endpoint:** `list_cameras()`, `get_camera()`, `get_camera_history()`
**Lines:** `103-128`, `272-285`, `355-379`

**Evidence:**
```python
@router.get("", response_model=list[CameraSchema])
def list_cameras(
    # ...
    db: Session = Depends(get_db),
):  # NO Depends(get_current_user)
```

**What is wrong:** Three read endpoints exposing camera locations, stream URLs, department assignments, and audit history require no authentication.

**Impact:** Full surveillance infrastructure exposure to anonymous attackers.

**Recommended Fix:** Add `Depends(get_current_user)` to all three.

---

## [SEC-07] Mass Assignment via setattr on Camera Update

**Severity:** HIGH
**Category:** OWASP A01 Broken Access Control / CWE-915 Mass Assignment
**Confidence:** CONFIRMED

**File:** `model1-registry/app/routers/cameras.py`
**Function/Class/Endpoint:** `update_camera()`
**Lines:** `305-310`

**Evidence:**
```python
update_data = body.model_dump(exclude_unset=True)
lat = update_data.pop("latitude", None)
lon = update_data.pop("longitude", None)

for field, value in update_data.items():
    setattr(cam, field, value)
```

**What is wrong:** The `CameraUpdate` schema at `shared/schemas/camera.py` line 50 includes `department_id: Optional[uuid.UUID] = None`. The endpoint checks that the current user owns the camera (line 299) but does NOT validate the *new* `department_id` value. A dept_admin can transfer a camera to another department.

**Impact:** Horizontal privilege escalation. Cross-department data manipulation.

**Recommended Fix:** After `update_data` is extracted, validate:
```python
if "department_id" in update_data and current_user.department_id:
    if update_data["department_id"] != current_user.department_id:
        raise HTTPException(403, "Cannot transfer camera to another department.")
```

---

## [SEC-08] Watchlist Mass Assignment via setattr

**Severity:** HIGH
**Category:** OWASP A01 Broken Access Control / CWE-915
**Confidence:** CONFIRMED

**File:** `model2-analytics/app/routers/watchlist.py`
**Function/Class/Endpoint:** `update_watchlist_vehicle()`
**Lines:** `168-169`

**Evidence:**
```python
for field, value in update_data.items():
    setattr(item, field, value)
```

**What is wrong:** `VehicleWatchlistUpdate` permits updating `plate_number`, `category`, `department_id`, `status`. Combined with the complete lack of authentication (SEC-03), any attacker can change watchlist entry statuses from "active" to "resolved", effectively hiding wanted vehicles.

**Impact:** Surveillance evasion by resolving active watchlist entries.

---

## [SEC-09] CSV Bulk Import Transaction Rollback Bug

**Severity:** HIGH
**Category:** Logic / Data Integrity / CWE-460
**Confidence:** CONFIRMED

**File:** `model1-registry/app/routers/cameras.py`
**Function/Class/Endpoint:** `bulk_import()`
**Lines:** `255-261`

**Evidence:**
```python
        db.add(cam)
        db.flush()
        created += 1
    except Exception as exc:
        db.rollback()           # <-- Rolls back ALL prior rows
        errors.append(f"Row {i}: {exc}")
        errored += 1
```

**What is wrong:** `db.rollback()` resets the entire transaction, discarding all previously flushed rows. But the `created` counter is not reset, so the API response lies about how many rows were actually created.

**Expected behavior:** Rows 1-49 valid, Row 50 invalid, Rows 51-100 valid => 99 rows created.
**Actual behavior:** Rows 1-49 are rolled back. Rows 51-100 are added to a fresh session. The response says `created: 99` but only rows 51-100 (50 rows) actually exist.

**Recommended Fix:** Use savepoints (`db.begin_nested()`) per row.

```python
try:
    with db.begin_nested():
        db.add(cam)
        db.flush()
    created += 1
except Exception as exc:
    errors.append(f"Row {i}: {exc}")
    errored += 1
```

---

## [SEC-10] Watchlist Duplicate Race Condition (TOCTOU)

**Severity:** MEDIUM
**Category:** Logic / CWE-367 TOCTOU
**Confidence:** CONFIRMED

**File:** `model2-analytics/app/routers/watchlist.py`
**Function/Class/Endpoint:** `create_watchlist_vehicle()`
**Lines:** `86-98`

**Evidence:**
```python
existing = db.query(VehicleWatchlistModel).filter(
    VehicleWatchlistModel.plate_number == payload.plate_number,
    VehicleWatchlistModel.status == "active",
).first()
if existing:
    raise HTTPException(...)
# ... gap between check and insert ...
db.add(new_entry)
db.commit()
```

**What is wrong:** The `vehicles_watchlist` table in `schema.sql` line 132 has an index `idx_vehicles_watchlist_plate` but it is NOT a `UNIQUE` index. It is just `CREATE INDEX` (not `CREATE UNIQUE INDEX`). Two concurrent requests can both pass the SELECT check and both insert.

**Recommended Fix:** Add to `schema.sql`:
```sql
CREATE UNIQUE INDEX idx_vehicles_watchlist_plate_unique
    ON vehicles_watchlist (plate_number) WHERE status = 'active';
```

---

## [SEC-11] No Rate Limiting on Login Endpoint

**Severity:** MEDIUM
**Category:** OWASP A07 Authentication Failures / CWE-307
**Confidence:** CONFIRMED

**File:** `model1-registry/app/routers/auth.py`
**Function/Class/Endpoint:** `login()`
**Lines:** `38-82`

**What is wrong:** No rate limiting on failed login attempts. An attacker can brute-force passwords against the `/api/v1/auth/login` endpoint without any throttling.

**Recommended Fix:** Add `slowapi` or a custom middleware to limit login attempts per IP.

---

## [SEC-12] Cookie Missing `Secure` Flag

**Severity:** MEDIUM
**Category:** OWASP A02 Security Misconfiguration / CWE-614
**Confidence:** CONFIRMED

**File:** `model1-registry/app/routers/auth.py`
**Function/Class/Endpoint:** `login()`
**Lines:** `66-72`

**Evidence:**
```python
response.set_cookie(
    key="access_token",
    value=access_token,
    httponly=True,
    samesite="lax",
    path="/",
)
```

**What is wrong:** The `secure=True` flag is not set. The JWT cookie will be transmitted over unencrypted HTTP connections.

---

## [SEC-13] Department and District List Endpoints Unauthenticated

**Severity:** MEDIUM
**Category:** OWASP A01 Broken Access Control
**Confidence:** CONFIRMED

**File:** `model1-registry/app/routers/departments.py` line `18-45`, `model1-registry/app/routers/districts.py` line `15-43`

**What is wrong:** Both endpoints expose organizational structure without requiring authentication.

---

## [SEC-14] Stored XSS in Map Popup HTML

**Severity:** MEDIUM
**Category:** OWASP A03 Injection / CWE-79
**Confidence:** CONFIRMED

**File:** `model1-registry/app/static/js/map.js`
**Function/Class/Endpoint:** `renderMarkers()`
**Lines:** `261-263`

**Evidence:**
```javascript
let popupHtml = `
    <div class="popup-content">
        <div class="popup-title">${emoji} ${cam.name}</div>
```

**What is wrong:** `cam.name` is interpolated directly into HTML without sanitization. A `dept_admin` who creates a camera with name `<img src=x onerror=alert(document.cookie)>` can steal session cookies from other administrators viewing the map.

**Recommended Fix:** Use `element.textContent` or a sanitization function.

---

## [SEC-15] No CORS Configuration

**Severity:** MEDIUM
**Category:** OWASP A02 Security Misconfiguration
**Confidence:** NEEDS RUNTIME VALIDATION

**What is wrong:** No explicit CORS middleware was found. If the FastAPI app is accessed from a different origin (e.g., a separate frontend deployment), requests will fail. If a wildcard CORS is added carelessly, it creates a security issue.

---

## [SEC-16] CSV Import Has No File Size Limit

**Severity:** MEDIUM
**Category:** OWASP API4 Unrestricted Resource Consumption / CWE-400
**Confidence:** CONFIRMED

**File:** `model1-registry/app/routers/cameras.py`
**Function/Class/Endpoint:** `bulk_import()`
**Lines:** `184`

**Evidence:**
```python
content = await file.read()  # Reads entire file into memory
```

**What is wrong:** No size limit. A 10GB CSV will be read entirely into memory, crashing the worker process.

---

## [SEC-17] Unpaginated Camera List Query

**Severity:** MEDIUM
**Category:** Performance / CWE-400
**Confidence:** CONFIRMED

**File:** `model1-registry/app/routers/cameras.py`
**Function/Class/Endpoint:** `list_cameras()`
**Lines:** `127`

**Evidence:**
```python
cameras = q.order_by(CameraModel.name).all()
```

**What is wrong:** No `LIMIT` or pagination. With 80,000 cameras, this returns all rows in a single response, consuming excessive memory and bandwidth.

---

# 5. Authentication Findings

| Endpoint | Auth Required? | Auth Present? | Correct? | Risk |
| -------- | ------------- | ------------- | -------- | ---- |
| `POST /api/v1/auth/login` | No | N/A | N/A | LOW |
| `POST /api/v1/auth/logout` | No | N/A | N/A | LOW |
| `GET /api/v1/cameras` | Yes | **No** | **No** | HIGH |
| `POST /api/v1/cameras` | Yes | Yes | Yes | LOW |
| `POST /api/v1/cameras/bulk` | Yes | Yes | Yes | LOW |
| `GET /api/v1/cameras/{id}` | Yes | **No** | **No** | HIGH |
| `PATCH /api/v1/cameras/{id}` | Yes | Yes | **IDOR** | HIGH |
| `DELETE /api/v1/cameras/{id}` | Yes | Yes | Yes | LOW |
| `GET /api/v1/cameras/{id}/history` | Yes | **No** | **No** | HIGH |
| `GET /api/v1/departments` | Yes | **No** | **No** | MEDIUM |
| `GET /api/v1/districts` | Yes | **No** | **No** | MEDIUM |
| `GET /api/v1/gap-analysis` | Yes | Yes | Yes | LOW |
| `GET /api/v1/audit` | Yes | Yes | Yes | LOW |
| `GET /api/v1/watchlist/vehicles` | Yes | **No** | **No** | HIGH |
| `POST /api/v1/watchlist/vehicles` | Yes | **No** | **No** | CRITICAL |
| `GET /api/v1/watchlist/vehicles/{id}` | Yes | **No** | **No** | HIGH |
| `PATCH /api/v1/watchlist/vehicles/{id}` | Yes | **No** | **No** | HIGH |
| `DELETE /api/v1/watchlist/vehicles/{id}` | Yes | **No** | **No** | CRITICAL |
| `GET /api/v1/grid/streams` | Yes | **No** | **No** | HIGH |
| `POST /api/v1/grid/sync` | Yes | **No** | **No** | CRITICAL |
| `GET /api/ingest` | Yes | **No** | **No** | HIGH |

---

# 6. Authorization / RBAC Findings

**Roles defined:** `dept_admin`, `operator`, `viewer` (schema.sql line 37).

- `dept_admin`: Can create/update/delete cameras within their department. However, IDOR via mass assignment (SEC-07) allows cross-department manipulation.
- `operator`, `viewer`: Currently cannot access any write endpoints on Model 1, but can access ALL Model 2 endpoints because Model 2 has zero authentication.
- There is no `system_admin` role -- all `dept_admin` users have equal privileges except for department scoping.

---

# 7. API Security Findings

See Section 5 for endpoint-level detail. Summary:
- 12 out of 21 API endpoints lack authentication.
- No rate limiting on any endpoint.
- No pagination on `GET /api/v1/cameras` or `GET /api/v1/grid/streams`.
- RTSP credentials are returned in API responses from grid endpoints.

---

# 8. Database Findings

- **SQL Injection:** PostGIS `ST_GeogFromText` uses f-string interpolation (`cameras.py` line 89: `f"SRID=4326;POINT({lon} {lat})"`), but inputs are Pydantic `float` types. **NOT A BUG** -- float coercion prevents injection.
- **Missing Unique Constraint:** `vehicles_watchlist.plate_number` has a non-unique index. Race condition confirmed (SEC-10).
- **Trigger Architecture:** Well-implemented audit triggers for `status_history` (`triggers.sql` lines 44-107). Correctly uses `current_setting('app.current_user_id', true)` with graceful NULL fallback.
- **Cascading Deletes:** Watchlist DELETE manually cascades alerts (`watchlist.py` line 192) instead of using DB-level `ON DELETE CASCADE` -- schema has `ON DELETE RESTRICT` on `alerts.watchlist_id` (schema.sql line 177). This is intentionally different from the schema constraint, but creates a logic inconsistency.

---

# 9. SSRF / Network Findings

See SEC-05. The attack path is: unauthenticated POST to `/api/v1/grid/sync` -> arbitrary `rtsp_url` stored in DB -> `StreamIngestClient` calls `cv2.VideoCapture(self.rtsp_url)` -> FFmpeg connects to attacker-controlled address.

No URL validation exists anywhere in the codebase.

---

# 10. Streaming / RTSP Findings

- Stream URLs are generated with hard-coded credentials (SEC-02).
- The `_build_stream_urls()` function ignores database-stored URLs and generates hardcoded URLs (grid.py lines 43-52). Database fields `cam.rtsp_url`, `cam.whep_url`, `cam.hls_url` are written by sync but never read for grid display.
- `StreamIngestClient` (`ingest.py`) correctly implements exponential backoff reconnection (lines 74-76), cap at 30 seconds, and TCP-forced RTSP. Frame buffering uses a lock-protected "latest frame only" strategy (lines 89-92) to prevent buffering lag. This is well-engineered.
- Resource cleanup: `cap.release()` is called in `finally` block (line 96). No fd leaks identified.

---

# 11. AI Pipeline Findings

| Component | Status | File |
| --------- | ------ | ---- |
| Frame Ingestion | IMPLEMENTED | `pipeline/ingest.py` |
| Vehicle Detection (YOLO) | IMPLEMENTED | `pipeline/detection/vehicle_detector.py` |
| YOLO Model Weights | PRESENT | `pipeline/detection/indian_traffic_yolov8.pt` (6.25 MB) |
| IoU/Centroid Tracking | IMPLEMENTED | `pipeline/tracking/frame_tracker.py` |
| ByteTrack Tracking | IMPLEMENTED | `pipeline/tracking/byte_tracker.py` |
| Detection Persistence | IMPLEMENTED | `pipeline/detection/writer.py` |
| Multi-Stream Runner | IMPLEMENTED | `pipeline/runner.py` |
| Pre-Recorded Video Worker | IMPLEMENTED | `pipeline/video_worker.py` |
| OCR / ANPR | PLACEHOLDER | `pipeline/ocr/__init__.py` (53 bytes, empty) |
| Watchlist Matching | MISSING | No matcher logic exists |
| Alert Generation | MISSING | No code connects detections to alerts table |
| Frame Sampling | IMPLEMENTED | `runner.py` line 49: `INFER_EVERY_N_FRAMES = 3` |
| GPU Batching | MISSING | Single-frame inference only |
| Re-identification | PLACEHOLDER | `pipeline/reid/` directory exists but is empty |
| Fusion | PLACEHOLDER | `pipeline/fusion/` directory exists but is empty |

The AI pipeline has advanced significantly since the first audit. Vehicle detection and tracking are functional. OCR and watchlist matching remain unimplemented.

---

# 12. Performance and Scalability Findings

No benchmark evidence exists in the repository.

**Architecture bottleneck:** Each camera requires a dedicated thread with a blocking `cv2.VideoCapture` call (`runner.py`). The `CAMERAS` list (`runner.py` lines 31-44) is hardcoded to 2 cameras. Thread-per-camera will not scale beyond ~50-100 cameras per host.

**Scalability estimates:**

| Scale | Viewing | AI Inference | Database | Network |
| ----- | ------- | ------------ | -------- | ------- |
| 10 cameras | OK | OK (CPU) | OK | ~50 Mbps |
| 100 cameras | WebRTC limits | Needs GPU | OK | ~500 Mbps |
| 1,000 cameras | Needs CDN | Needs cluster | OK with indexes | ~5 Gbps |
| 10,000 cameras | Needs architecture redesign | Needs distributed inference | Needs partitioning | Dedicated network |
| 80,000 cameras | Impossible with current architecture | Impossible | Needs sharding | Impossible |

---

# 13. Frontend Findings

- **XSS:** Confirmed in map.js popup rendering (SEC-14).
- **Token Storage:** JWT stored in httpOnly cookie -- correct and secure.
- **CSRF:** `SameSite=lax` provides partial CSRF protection for state-changing POST requests.
- **Client-Side Auth:** Page routes (`pages.py`) check `get_optional_current_user` and redirect to `/login` if None. This is UI-level only; backend API endpoints must independently enforce auth (and many do not).

---

# 14. Docker / DevOps Findings

**Status: DEVELOPMENT ONLY -- NOT SAFE FOR PRODUCTION**

- **Root Container:** Dockerfile uses `python:3.12-slim` with no `USER` directive. Container runs as root.
- **Database Port Exposed:** Port 5432 mapped to host (docker-compose.yml line 16).
- **Static DB Password:** `POSTGRES_PASSWORD: sentinel_dev` (docker-compose.yml line 13).
- **No Resource Limits:** No `mem_limit`, `cpus`, or `ulimits`.
- **No Restart Policy on DB:** `app` has `restart: unless-stopped` but `db` does not.
- **Source Code Mounted:** Live source volumes (`../model1-registry/app:/app/app`) are dev-only mounts.
- **MediaMTX Latest Tag:** `bluenviron/mediamtx:latest` (line 59) is unpinned.
- **Health Checks:** DB has `pg_isready` healthcheck. App has none.

---

# 15. Dependency / Supply Chain Findings

**File:** `model1-registry/requirements.txt`

| Package | Pinned? | Risk |
| ------- | ------- | ---- |
| `fastapi` | No | MEDIUM |
| `uvicorn[standard]` | No | MEDIUM |
| `sqlalchemy>=2.0` | Partially | LOW |
| `geoalchemy2` | No | MEDIUM |
| `psycopg2-binary` | No | MEDIUM |
| `pydantic-settings` | No | MEDIUM |
| `jinja2` | No | MEDIUM |
| `python-multipart` | No | MEDIUM |
| `shapely` | No | LOW |
| `passlib[bcrypt]` | No | MEDIUM |
| `python-jose[cryptography]` | No | HIGH (`python-jose` is abandoned; prefer `PyJWT` or `joserfc`) |
| `opencv-python-headless` | No | MEDIUM |
| `requests` | No | LOW |
| `ultralytics` | No | MEDIUM |

`python-jose` is effectively unmaintained. The recommended replacement is `PyJWT` or `joserfc`.

No lock file exists (`requirements.txt` only, no `poetry.lock` or `pip-compile` output).

---

# 16. Logic Bugs

1. **CSV Rollback Bug** (SEC-09): Confirmed data loss on mid-batch errors.
2. **Watchlist Race Condition** (SEC-10): Confirmed duplicate entries possible.
3. **Grid URL Ignores Database:** `_build_stream_urls()` generates hardcoded URLs instead of using `cam.rtsp_url`/`cam.whep_url`/`cam.hls_url` from the database.
4. **Watchlist DELETE vs Schema Mismatch:** Code manually deletes alerts (watchlist.py line 192) but schema has `ON DELETE RESTRICT` (schema.sql line 177). If the manual delete is skipped (e.g., race condition), the subsequent `db.delete(item)` will fail with an FK violation.

---

# 17. Dead / Unused / Redundant Code

| File | Line | Symbol | Why Unused | Safe to Delete? |
| ---- | ---- | ------ | ---------- | --------------- |
| `pages.py` | 421-430 | `alerts_placeholder()` | Returns a static "not built yet" template | Yes |
| `pipeline/ocr/__init__.py` | 1 | module | Empty placeholder, 53 bytes | No (needed for future OCR) |
| `pipeline/reid/` | -- | directory | Empty placeholder | No (needed for future re-id) |
| `pipeline/fusion/` | -- | directory | Empty placeholder | No (needed for future fusion) |
| `config.py` | 27-28 | `GRID_RTSP_USER`, `GRID_RTSP_PASS` | Defined but never used (credentials are hardcoded elsewhere) | No (should be used) |
| `pipeline/orchestrator.py` | 1-132 | `VehicleAnalyticsPipeline` | Older pipeline design superseded by `runner.py` | Likely safe to merge/delete |

---

# 18. Documentation / Implementation Mismatches

- README describes comprehensive ANPR/OCR capabilities. **OCR is not implemented** (empty `pipeline/ocr/`).
- README describes watchlist matching and alert generation. **Neither is implemented** in the AI pipeline.
- `docs/API_Contract.md` describes Model 2 endpoints as authenticated. **They are not.**

---

# 19. Testing Gaps

| Component | Existing Tests | Missing Tests | Risk |
| --------- | -------------- | ------------- | ---- |
| Camera CRUD | `test_cameras.py` (8.6 KB) | Mass assignment IDOR test | HIGH |
| Auth | `test_auth.py` (2.4 KB) | Brute force, rate limit tests | MEDIUM |
| Gap Analysis | `test_gap_analysis.py` (3.6 KB) | None | LOW |
| Districts | `test_districts.py` (2.8 KB) | None | LOW |
| Pages | `test_pages.py` (4.9 KB) | None | LOW |
| Watchlist API | **None** | Full CRUD + auth + race condition | CRITICAL |
| Grid API | **None** | Full CRUD + auth + SSRF | CRITICAL |
| Ingestion Pipeline | **None** | Reconnect, fd leaks, thread safety | HIGH |
| AI Detection | **None** | Model accuracy, performance | MEDIUM |
| CSV Import | Partial in `test_cameras.py` | Savepoint rollback, memory exhaustion | HIGH |
| Frontend XSS | **None** | Sanitization tests | MEDIUM |

---

# 20. Observability Gaps

- Basic Python `logging` in pipeline components.
- No structured logging (JSON format).
- No Prometheus metrics endpoint.
- No OpenTelemetry tracing.
- No application-level health check endpoint (`/healthz`).
- No GPU utilization monitoring.
- No queue depth or backpressure metrics.
- Database audit trail exists via triggers but has no alerting integration.

---

# 21. Privacy / Surveillance Risks

- License plate data in `vehicles_watchlist` and `detections` tables has no retention policy enforcement (no cleanup job exists).
- Camera coordinates expose exact surveillance positions.
- RTSP credentials in source code expose live video feeds.
- No data access logging beyond the camera-level audit trail.
- `detections.cropped_image_path` stores vehicle crop images with no access control on the filesystem.

---

# 22. Threat Model

| Actor | Attack Surface | Key Attacks | Impact |
| ----- | -------------- | ----------- | ------ |
| Anonymous Internet | All unauthenticated endpoints | Watchlist manipulation, camera enumeration, SSRF, credential harvesting from source code | CRITICAL |
| Authenticated Low-Privilege (viewer/operator) | All Model 2 endpoints (no auth check) | Full watchlist CRUD, grid sync | HIGH |
| Department Admin | PATCH cameras, CSV import | Cross-department camera transfer via mass assignment | HIGH |
| Malicious Insider | Source code access | RTSP credential extraction, JWT forgery | CRITICAL |

---

# 23. P0 Fixes -- MUST FIX BEFORE DEPLOYMENT

1. **SEC-01:** Remove hard-coded `SECRET_KEY` and `DATABASE_URL` defaults from `config.py`.
2. **SEC-02:** Remove hard-coded RTSP credentials from `grid.py`, `runner.py`, `config.py`. Use environment variables.
3. **SEC-03:** Add authentication to all 5 watchlist endpoints.
4. **SEC-04:** Add authentication to grid streams, sync, and ingest endpoints.
5. **SEC-05:** Add URL validation to prevent SSRF via grid sync.
6. **SEC-06:** Add authentication to camera list, detail, and history endpoints.

---

# 24. P1 Fixes -- MUST FIX BEFORE PRODUCTION

7. **SEC-07:** Block `department_id` mass assignment in camera PATCH.
8. **SEC-09:** Fix CSV bulk import transaction rollback using savepoints.
9. **SEC-10:** Add partial unique index on `vehicles_watchlist(plate_number) WHERE status = 'active'`.
10. **SEC-11:** Add rate limiting to login endpoint.
11. **SEC-12:** Add `secure=True` to JWT cookie.
12. **SEC-14:** Fix XSS in map.js popup rendering.
13. Add pagination to `list_cameras` and `get_grid_streams`.
14. Pin all dependencies with exact versions.

---

# 25. P2 Fixes -- SHOULD FIX

15. **SEC-16:** Add file size limit to CSV upload.
16. Replace `python-jose` with `PyJWT`.
17. Add non-root user to Dockerfile.
18. Add health check endpoint for the app container.
19. Add resource limits to docker-compose.
20. Implement OCR pipeline.
21. Implement watchlist matching and alert generation.
22. Use database-stored URLs instead of hardcoded URLs in `_build_stream_urls()`.

---

# 26. Recommended Architecture

For production at scale:
- Separate Model 1 (Registry API) and Model 2 (Analytics) into independent services.
- Use a message queue (Redis Streams / Kafka) between ingestion and detection.
- Deploy MediaMTX per-region, not as a single instance.
- Use NGINX/Traefik as a reverse proxy with TLS termination.

---

# 27. Recommended Security Architecture

- Enforce authentication on EVERY endpoint via a global middleware or router-level dependency.
- Implement refresh token rotation.
- Add CORS configuration with explicit allowed origins.
- Deploy behind a WAF for rate limiting and IP blocking.
- Rotate RTSP credentials regularly via environment variables.

---

# 28. Recommended AI Scaling Architecture

- Replace thread-per-camera with process-per-GPU-batch.
- Implement frame sampling with motion detection pre-filter.
- Use NVIDIA DeepStream or TensorRT for GPU-accelerated inference.
- Batch 8-16 frames per inference call.
- Deploy inference workers horizontally with Kubernetes.

---

# 29. Recommended Test Plan

1. **Authentication matrix test:** For every endpoint, test with no token, expired token, valid token, wrong role.
2. **Mass assignment test:** PATCH camera with `department_id` belonging to a different department.
3. **CSV savepoint test:** Upload CSV with valid-invalid-valid rows, verify all valid rows persist.
4. **Race condition test:** Concurrent watchlist creation with same plate number.
5. **SSRF test:** Sync endpoint with `rtsp_url` pointing to internal addresses.
6. **XSS test:** Create camera with HTML payload in name, verify it does not execute.

---

# 30. Final Production Readiness Assessment

## False Positive / Verified Safe

- **Password hashing:** bcrypt with random salt generation (`security.py` lines 14-18). Correctly implemented. NOT A BUG.
- **JWT verification:** `decode_access_token()` uses `jwt.decode()` with algorithm enforcement (`[settings.ALGORITHM]`). No bypass identified. NOT A BUG.
- **SQL Injection in PostGIS:** `ST_GeogFromText(f"SRID=4326;POINT({lon} {lat})")` -- `lon` and `lat` are Pydantic `float` types. Float coercion prevents string-based injection. NOT A BUG (but parameterized binding is preferred).
- **DB Trigger audit:** `log_camera_changes()` function correctly handles NULL `acting_user` with `current_setting(... true)` and exception fallback. NOT A BUG.
- **RTSP reconnection:** Exponential backoff implemented correctly with cap. Frame drop detection triggers reconnect. NOT A BUG.

---

## Final Scorecard

| Area                 | Score / 10 | Status |
| -------------------- | ---------: | ------ |
| Authentication       |          2 | FAIL -- 12/21 endpoints unauthenticated |
| Authorization        |          3 | FAIL -- Mass assignment, no object-level auth on Model 2 |
| API Security         |          2 | FAIL -- No rate limiting, no pagination, credential exposure |
| Database Security    |          6 | POOR -- Missing unique constraints, rollback bug |
| Streaming Security   |          1 | FAIL -- Hardcoded credentials in source |
| Input Validation     |          6 | OK -- Pydantic schemas with plate validation |
| Docker Security      |          3 | FAIL -- Root container, exposed ports, no limits |
| Dependency Security  |          3 | FAIL -- No pinning, abandoned library |
| Code Quality         |          6 | OK -- Clean structure, good separation |
| Testing              |          4 | POOR -- No Model 2 tests, no security tests |
| Observability        |          2 | FAIL -- Basic logging only |
| AI Architecture      |          5 | PARTIAL -- Detection/tracking work, OCR/matching missing |
| Performance          |          3 | POOR -- Thread-per-camera, no GPU batching |
| Scalability          |          2 | FAIL -- Cannot scale beyond ~50 cameras |
| Privacy              |          2 | FAIL -- No retention enforcement, credential exposure |
| Production Readiness |          2 | FAIL -- Not safe for any deployment |

**Overall Security Score: 2.5 / 10**

**Overall Production Readiness: 2 / 10**

**Top 10 Issues To Fix Immediately:**

1. Remove hard-coded `SECRET_KEY` from `config.py`
2. Remove hard-coded RTSP credentials from `grid.py` and `runner.py`
3. Add authentication to all watchlist endpoints
4. Add authentication to grid sync endpoint (SSRF risk)
5. Add authentication to camera list/detail/history endpoints
6. Fix mass assignment in camera PATCH (department_id)
7. Fix CSV bulk import rollback bug with savepoints
8. Add partial unique index for watchlist plate numbers
9. Add rate limiting to login endpoint
10. Add `secure=True` to JWT cookie
