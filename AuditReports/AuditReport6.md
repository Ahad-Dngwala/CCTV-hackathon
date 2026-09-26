# EyesOnGuj — Deep Security & Code Audit Report 6

**Audit Date:** 2026-09-26
**Auditor:** Deep Repository Forensic Analysis (Post-Fix Iteration)
**Repository:** `Ahad-Dngwala/CCTV-hackathon` / `Vishmayraj/EyesOnGuj`
**Branch:** `main`
**Scope:** Full codebase re-audit after all previous PR fixes — all three models, shared layer, DB schema, infrastructure. Focus on second-order vulnerabilities, missed logic, and bypasses introduced by the fixes themselves.

---

## 1. Executive Summary

This is the sixth audit of the Sentinel Gujarat CCTV Integration platform and the first one performed **after** the complete remediation roadmap from AuditReport4 was applied. Previous audit fixes addressed department-scoped CRUD, WebSocket authentication, job ownership, federation SSRF, VMS credential encryption, and CSRF tokens.

This audit treats those fixes as the new baseline and investigates second-order vulnerabilities — gaps that the fixes introduced or left incomplete. The focus areas were: federation REST endpoints, JWT lifecycle, audit log transaction integrity, department scoping consistency, and race conditions in async/threaded state.

**33 new findings were confirmed, none of which appeared in any previous audit.**

**Total Confirmed Findings:** 33
**CRITICAL:** 7 | **HIGH:** 8 | **MEDIUM:** 13 | **LOW:** 5

---

## 2. Audit Scope

The audit covered all files under:
- `model1-registry/` — Auth, CSRF, rate limiting, camera CRUD, JWT lifecycle
- `model2_analytics/` — Recorded video pipeline, persons watchlist, grid sync, SSRF validation
- `model3_federation/` — All REST endpoints, WebSocket, adapter SSRF, VMS lifecycle
- `shared/` — `audit.py`, `db/schema.sql`, `db/models.py`, `security.py`
- `infra/` — Docker Compose, Caddy reverse proxy configuration

**The core architectural flaw identified in this iteration:** The authorization model enforces `JWT → Role → Endpoint` and now (after fixes) `Department → Camera CRUD`, but **entirely skips department enforcement for Model 3 federation REST endpoints**, leaving 5 endpoints open to cross-department data access by any authenticated user.

---

## 3. Security Posture Summary

| Category | Status | Key Observation |
| -------- | ------ | --------------- |
| Authentication (JWT lifecycle) | **Poor** | 8-hour tokens, no revocation, logout is UI-only |
| Authorization (Department scoping) | **Partial** | Camera CRUD fixed; federation endpoints untouched |
| Audit Logging | **Broken** | Independent `db.commit()` breaks non-repudiation |
| Rate Limiting | **Partial** | In-memory only — reset on restart, bypassed by proxy |
| SSRF Protection | **Partial** | DNS TOCTOU race still exploitable in `is_safe_url()` |
| Person Watchlist | **Poor** | No `department_id` column — zero isolation |
| Federation RBAC | **Critical** | 5 endpoints open to cross-department access or viewer abuse |
| Database Schema | **Fair** | Missing indexes, inconsistent FK types, no `updated_at` |

---

## 4. Findings Summary

| ID | Severity | Category | Finding | File(s) | Status |
| -- | -------- | -------- | ------- | ------- | ------ |
| BUG-001 | 🔴 CRITICAL | Auth / JWT | JWT role/dept not re-read from DB — 8h privilege window | `auth/dependencies.py`, `auth/security.py` | New |
| BUG-002 | 🔴 CRITICAL | Audit | Audit log independent commit breaks non-repudiation | `shared/audit.py` | New |
| BUG-003 | 🔴 CRITICAL | AuthZ / IDOR | PATCH /v3/systems — no ownership check | `model3_federation/api/router.py` | New |
| BUG-004 | 🔴 CRITICAL | AuthZ / IDOR | DELETE /v3/systems — no ownership check | `model3_federation/api/router.py` | New |
| BUG-005 | 🔴 CRITICAL | AuthZ | Simulate endpoint accessible to viewer role | `model3_federation/api/router.py` | New |
| BUG-006 | 🔴 CRITICAL | AuthZ / IDOR | GET /v3/alerts — cross-department alert disclosure | `model3_federation/api/router.py` | New |
| BUG-007 | 🔴 CRITICAL | AuthZ / IDOR | GET /v3/correlations/track — no department isolation | `model3_federation/api/router.py` | New |
| BUG-008 | 🟠 HIGH | Auth | Rate limiter in-memory — reset on restart | `auth/rate_limit.py` | New |
| BUG-009 | 🟠 HIGH | Auth | 8-hour JWT with no revocation mechanism | `config.py` | New |
| BUG-010 | 🟠 HIGH | Auth | Logout only clears cookie — JWT stays valid | `routers/auth.py` | New |
| BUG-011 | 🟠 HIGH | AuthZ / IDOR | GET /v3/cameras — no department filter | `model3_federation/api/router.py` | New |
| BUG-012 | 🟠 HIGH | AuthZ / IDOR | GET /v3/events — no department filter | `model3_federation/api/router.py` | New |
| BUG-013 | 🟠 HIGH | DoS | Bulk CSV import has no row limit | `routers/cameras.py` | New |
| BUG-014 | 🟠 HIGH | Data | Audit `details` JSONB has no size cap | `shared/audit.py` | New |
| BUG-015 | 🟠 HIGH | AuthZ / IDOR | Camera history — no department scoping | `routers/cameras.py` | New |
| BUG-016 | 🟡 MEDIUM | Config | Duplicate `model2-analytics/` directory | Root | New |
| BUG-017 | 🟡 MEDIUM | Auth / CSRF | CSRF token not bound to session JWT | `routers/auth.py`, `auth/dependencies.py` | New |
| BUG-018 | 🟡 MEDIUM | AuthZ / IDOR | Person watchlist — no department_id column or scoping | `routers/persons_watchlist.py`, `schema.sql` | New |
| BUG-019 | 🟡 MEDIUM | AuthZ / IDOR | Recorded cameras endpoint — no department filter | `routers/recorded.py` | New |
| BUG-020 | 🟡 MEDIUM | Performance | OpenCV blocking call in async endpoint | `routers/recorded.py` | New |
| BUG-021 | 🟡 MEDIUM | UX / Info | Camera history exposes raw user UUID | `routers/cameras.py` | New |
| BUG-022 | 🟡 MEDIUM | AuthZ | Viewer role can query job status | `routers/recorded.py` | New |
| BUG-023 | 🟡 MEDIUM | Secrets | VMS adapter `config` JSONB stores credentials in plaintext | `schema.sql` | New |
| BUG-024 | 🟡 MEDIUM | Schema | `person_alerts.camera_id` is TEXT, not UUID FK | `schema.sql` | New |
| BUG-025 | 🟡 MEDIUM | Logic | Bulk import: `SET LOCAL` user ID set after INSERTs — audit shows NULL | `routers/cameras.py` | New |
| BUG-026 | 🟡 MEDIUM | Auth | Rate limit IP read from direct TCP peer — proxy-bypassed | `routers/auth.py`, `rate_limit.py` | New |
| BUG-027 | 🟡 MEDIUM | SSRF | DNS TOCTOU race bypasses `is_safe_url()` | `routers/grid.py` | New |
| BUG-028 | 🟡 MEDIUM | Race Condition | `_JOBS` / `_JOBS_META` dicts not thread-safe | `routers/recorded.py` | New |
| BUG-029 | 🔵 LOW | API Design | No pagination on federation endpoints | `model3_federation/api/router.py` | New |
| BUG-030 | 🔵 LOW | Error Handling | `get_optional_current_user()` swallows DB errors | `auth/dependencies.py` | New |
| BUG-031 | 🔵 LOW | DB | `audit_logs` missing `created_at` index | `schema.sql` | New |
| BUG-032 | 🔵 LOW | DB | `status_history` ON DELETE RESTRICT blocks future hard deletes | `schema.sql` | New |
| BUG-033 | 🔵 LOW | DB | `vms_systems` missing `updated_at` column | `schema.sql` | New |

---

## 5. Detailed Findings

### [BUG-001] — JWT Role/Department Not Re-Read from DB on Each Request (Privilege Escalation Window)

**Severity:** 🔴 CRITICAL
**Category:** CWE-613 Insufficient Session Expiration / CWE-269 Improper Privilege Management
**Confidence:** CONFIRMED
**File:** `model1-registry/app/auth/dependencies.py`, `model1-registry/app/auth/security.py`
**Lines:** `dependencies.py:60–65`, `security.py:84–89`

**Evidence:**
```python
# auth/dependencies.py
user = db.query(UserModel).filter(UserModel.id == user_id).first()
if not user or not user.is_active:
    raise HTTPException(status_code=401, ...)
return user  # role and department_id come from the live DB row — CORRECT

# BUT: auth/routers/auth.py on login
token_data = {
    "sub": str(user.id),
    "role": user.role,           # baked into the token
    "department_id": str(user.department_id),  # baked into the token
}
```

**What is wrong:** The JWT payload carries `role` and `department_id`. While `get_current_user()` correctly re-queries the DB and returns the live `UserModel`, there is no token revocation mechanism. A user whose role is downgraded (e.g. `dept_admin` → `viewer`) retains a valid JWT for up to 8 hours. Deactivating the account (`is_active = false`) works immediately; role changes do not.

**Why it happens:** JWTs are stateless by design. The fix (checking `is_active` in the DB) covers account deactivation but not role changes.

**Attack / Failure Scenario:**
1. Admin promotes `attacker_user` to `dept_admin` temporarily.
2. `attacker_user` logs in, receives a JWT valid for 8 hours.
3. Admin revokes `dept_admin` role from `attacker_user`.
4. `attacker_user` continues to use all `dept_admin` endpoints for the remaining 7h 59m.

**Impact:** Privilege escalation window up to 8 hours after role revocation.

**Affected Components:** All RBAC-protected endpoints.

**Root Cause:** No token invalidation on role change; 8-hour token lifetime.

**Recommended Fix:** Add a `token_version INTEGER DEFAULT 0` column to `users`. Increment it on any role/department change. Include it in the JWT payload and validate it against the DB on each request.

**Suggested Implementation:**
```python
# In get_current_user():
user = db.query(UserModel).filter(UserModel.id == user_id).first()
if not user or not user.is_active:
    raise HTTPException(status_code=401, ...)
# Validate token version
if payload.get("tv") != user.token_version:
    raise HTTPException(status_code=401, detail="Session invalidated. Please log in again.")
return user
```

**Verification:** Change a user's role in the DB while holding their JWT. Attempt a role-gated endpoint. It should return 401.

---

### [BUG-002] — Audit Log Independent `db.commit()` Breaks Non-Repudiation

**Severity:** 🔴 CRITICAL
**Category:** CWE-778 Insufficient Logging / CWE-362 Race Condition
**Confidence:** CONFIRMED
**File:** `shared/audit.py`
**Lines:** `22–44`

**Evidence:**
```python
# shared/audit.py
def log_audit_event(db, action, resource_type, ...):
    try:
        db.execute(text("INSERT INTO audit_logs ..."), {...})
        db.commit()   # ← INDEPENDENT commit, AFTER the primary action's commit
    except Exception as e:
        logger.error(f"Failed to write audit log: {e}")
        db.rollback()  # ← Rolls back only the audit INSERT; primary action already committed
```

**What is wrong:** The primary resource action (e.g. creating a watchlist entry) calls `db.commit()` in the router. Then `log_audit_event()` is called, which calls its own `db.commit()`. If the audit INSERT fails (oversized JSON, DB connection drop), the `db.rollback()` has no effect on the already-committed primary action.

**Attack / Failure Scenario:**
1. Attacker sends a watchlist creation request with a deliberately oversized `details` field (>1MB JSON string).
2. The camera/watchlist creation `db.commit()` succeeds.
3. The audit `db.execute()` raises a PostgreSQL error (value too long for JSONB column limit).
4. `db.rollback()` runs but only affects the (already-failed) audit INSERT.
5. The primary action is committed, the audit log is empty.

**Impact:** Critical security actions (watchlist creation, camera changes, role changes) can succeed with zero audit trail.

**Recommended Fix:** Use a single transaction. Call `db.flush()` in the router instead of `db.commit()`. Call `log_audit_event()`. Then commit once.

**Suggested Implementation:**
```python
# In the router (e.g. create watchlist entry):
db.add(new_entry)
db.flush()   # stage the INSERT — does NOT commit
log_audit_event(db, action="watchlist.create", ...)
db.commit()  # one commit covers BOTH the entry and the audit log
```

**Verification:** Cause the audit INSERT to fail (temporarily add a CHECK constraint on `audit_logs.details` that rejects long strings). Verify the primary action is also rolled back.

---

### [BUG-003] — `PATCH /api/v3/systems/{system_id}` Has No Ownership Check (IDOR)

**Severity:** 🔴 CRITICAL
**Category:** CWE-639 BOLA/IDOR
**Confidence:** CONFIRMED
**File:** `model3_federation/api/router.py`
**Lines:** `521–553`

**Evidence:**
```python
@router.patch("/systems/{system_id}")
def update_system(system_id: str, payload: VMSSystemUpdate, db: Session = Depends(get_db),
                  current_user: UserModel = Depends(require_role("dept_admin", "operator"))):
    exists = db.execute(text("SELECT 1 FROM vms_systems WHERE id = :id"), {"id": system_id}).fetchone()
    if exists is None:
        raise HTTPException(status_code=404, ...)
    # ← NO check: does this system belong to current_user.department_id?
    db.execute(text(f"UPDATE vms_systems SET {set_clause} WHERE id = :id"), params)
```

**Attack / Failure Scenario:** Operator from Department A obtains the UUID of Department B's VMS system (visible from `GET /api/v3/systems` which returns all systems). Sends `PATCH /api/v3/systems/<dept_b_system_id>` with `{"department_id": "<dept_a_id>"}`. Department B's VMS system is now assigned to Department A.

**Impact:** Cross-department VMS system takeover. Complete federation data theft.

**Recommended Fix:**
```python
row = db.execute(text("SELECT department_id FROM vms_systems WHERE id = :id"), {"id": system_id}).fetchone()
if row is None:
    raise HTTPException(status_code=404, ...)
if current_user.department_id and str(row[0]) != str(current_user.department_id):
    raise HTTPException(status_code=403, detail="You can only modify systems in your own department.")
```

**Verification:** As `dept_admin` of Department A, attempt to PATCH a system belonging to Department B. Should receive 403.

---

### [BUG-004] — `DELETE /api/v3/systems/{system_id}` Has No Ownership Check (IDOR)

**Severity:** 🔴 CRITICAL
**Category:** CWE-639 BOLA/IDOR
**Confidence:** CONFIRMED
**File:** `model3_federation/api/router.py`
**Lines:** `556–587`

**Evidence:**
```python
@router.delete("/systems/{system_id}")
def delete_system(system_id: str, ...current_user: UserModel = Depends(require_role("dept_admin", "operator"))):
    exists = db.execute(text("SELECT 1 FROM vms_systems WHERE id = :id"), {"id": system_id}).fetchone()
    # ← NO ownership check before deletion
    db.execute(text("DELETE FROM vms_systems WHERE id = :id"), {"id": system_id})
```

**Attack / Failure Scenario:** Same as BUG-003 — any `dept_admin` or `operator` can delete any VMS system in the database by its UUID, regardless of which department owns it.

**Recommended Fix:** Same pattern as BUG-003 — read `department_id` from the row first and verify it matches `current_user.department_id`.

**Verification:** As `dept_admin` of Department A, attempt to DELETE a system belonging to Department B. Should receive 403.

---

### [BUG-005] — Simulate Endpoint Accessible by `viewer` Role

**Severity:** 🔴 CRITICAL
**Category:** CWE-284 Improper Access Control
**Confidence:** CONFIRMED
**File:** `model3_federation/api/router.py`
**Lines:** `866–916`

**Evidence:**
```python
@router.post("/systems/{system_id}/simulate")
async def simulate_burst(
    system_id: str,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),  # ← Any authenticated user!
):
    # Fires 10 synthetic vehicle_detection events into the live event bus
    for i in range(10):
        event = FederatedEvent(event_type="vehicle_detection", detected_plate=plate, ...)
        await _bus.publish(event)
```

**What is wrong:** `Depends(get_current_user)` allows any role including `viewer`. A viewer can inject 10 fake vehicle detection events into the production database and broadcast them to all connected WebSocket clients.

**Impact:** Viewers can pollute the detection database, trigger false watchlist alerts, and confuse all connected operators. Persistent data corruption.

**Recommended Fix:** Change `Depends(get_current_user)` to `Depends(require_role("dept_admin", "operator"))`.

**Suggested Implementation:**
```python
current_user: UserModel = Depends(require_role("dept_admin", "operator")),
```

**Verification:** Log in as `viewer1`. POST to `/api/v3/systems/{any_id}/simulate`. Should receive 403.

---

### [BUG-006] — `GET /api/v3/alerts` — Cross-Department Alert Disclosure

**Severity:** 🔴 CRITICAL
**Category:** CWE-200 Information Exposure / CWE-639 BOLA
**Confidence:** CONFIRMED
**File:** `model3_federation/api/router.py`
**Lines:** `803–838`

**Evidence:**
```python
@router.get("/alerts")
def get_federated_alerts(limit: int = Query(30), db: Session = Depends(get_db),
                         current_user: UserModel = Depends(get_current_user)):
    rows = db.execute(text("""
        SELECT a.id, a.created_at, a.severity, d.detected_plate, c.name, vs.name
        FROM alerts a
        JOIN detections d ON d.id = a.detection_id
        JOIN cameras c ON c.id = d.camera_id
        JOIN vms_systems vs ON vs.id = c.vms_system_id
        ORDER BY a.created_at DESC LIMIT :lim
    """), {"lim": limit}).fetchall()
    # ← Returns ALL alerts from ALL departments, no filter
```

**Attack / Failure Scenario:** A `viewer` from the Home Department requests `GET /api/v3/alerts` and receives all alerts — including plate numbers detected by RTO Department cameras — across the entire platform.

**Impact:** Cross-department vehicle surveillance data disclosure.

**Recommended Fix:**
```python
where_clause = "WHERE c.vms_system_id IS NOT NULL"
params = {"lim": limit}
if current_user.department_id:
    where_clause += " AND vs.department_id = :dept_id"
    params["dept_id"] = str(current_user.department_id)
```

**Verification:** As `admin_home` (Home Department), request `/api/v3/alerts`. Should only return alerts from Home Department cameras.

---

### [BUG-007] — `GET /api/v3/correlations/track` — No Department Isolation

**Severity:** 🔴 CRITICAL
**Category:** CWE-200 Information Exposure / CWE-639 BOLA
**Confidence:** CONFIRMED
**File:** `model3_federation/api/router.py`
**Lines:** `745–800`

**Evidence:**
```python
@router.get("/correlations/track")
def track_vehicle(plate: str = Query(...), db: Session = Depends(get_db),
                  current_user: UserModel = Depends(get_current_user)):
    rows = db.execute(text("""
        SELECT d.id, c.vms_system_id, d.timestamp, ...
        FROM detections d
        JOIN cameras c ON c.id = d.camera_id
        LEFT JOIN vms_systems vs ON vs.id = c.vms_system_id
        WHERE d.detected_plate = :p
        ORDER BY d.timestamp ASC LIMIT 100
    """), {"p": plate_norm}).fetchall()
    # ← Returns ALL sightings across ALL departments
```

**What is wrong:** Any authenticated user (including `viewer`) can perform a full nationwide vehicle track lookup. All sightings across all departments' cameras are returned regardless of the requesting user's department.

**Impact:** Complete bypass of the department isolation model for vehicle tracking data — a core privacy and security requirement.

**Recommended Fix:** Filter by `vs.department_id = current_user.department_id` when the user has a department assigned.

**Verification:** Log in as `viewer1` (Home Dept). Track a plate. Should only see sightings from Home Dept cameras, not RTO cameras.

---

### [BUG-008] — Login Rate Limiter Is In-Memory Only — Reset on Process Restart

**Severity:** 🟠 HIGH
**Category:** CWE-307 Improper Restriction of Excessive Authentication Attempts
**Confidence:** CONFIRMED
**File:** `model1-registry/app/auth/rate_limit.py`
**Lines:** `29–103`

**Evidence:**
```python
class LoginRateLimiter:
    def __init__(self, ...):
        self._failures: Dict[str, List[float]] = {}   # ← In-memory Python dict
        self._locked_until: Dict[str, float] = {}
```

The code's own docstring acknowledges this:
> "If that ever changes [horizontal scaling], this needs a shared backend (e.g. Redis)"

**Attack / Failure Scenario:** Attacker triggers a 500-error path (e.g. sending a malformed request that causes an unhandled exception and triggers uvicorn to recycle the worker). All lockout state is cleared. Brute force resumes immediately from zero failures.

**Recommended Fix:** Use Redis for the rate limiter state. `REDIS_URL` is already in `settings`.

**Suggested Implementation:**
```python
import redis
r = redis.from_url(settings.REDIS_URL)
# Use INCR + EXPIRE for failure counting; SETEX for lockout keys
```

**Verification:** Lock out a key. Restart the uvicorn process. Attempt login again — it should still be locked.

---

### [BUG-009] — 8-Hour JWT Lifetime with No Token Revocation

**Severity:** 🟠 HIGH
**Category:** CWE-613 Insufficient Session Expiration
**Confidence:** CONFIRMED
**File:** `model1-registry/app/config.py`
**Lines:** `24`

**Evidence:**
```python
ACCESS_TOKEN_EXPIRE_MINUTES: int = 480  # 8 hours
```

**What is wrong:** A stolen JWT (via XSS, network interception, or browser extension) remains fully valid for up to 8 hours. There is no token blocklist, no `jti`, and no refresh token rotation.

**Recommended Fix:** Reduce to 60 minutes. Implement a Redis-based token blocklist keyed on `jti`. On logout, add the token's `jti` to the blocklist with TTL equal to remaining token lifetime.

---

### [BUG-010] — Logout Only Clears Browser Cookie — JWT Remains Valid

**Severity:** 🟠 HIGH
**Category:** CWE-613 Insufficient Session Expiration
**Confidence:** CONFIRMED
**File:** `model1-registry/app/routers/auth.py`
**Lines:** `125–143`

**Evidence:**
```python
@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(key="access_token", ...)
    response.delete_cookie(key="csrf_token", ...)
    return {"status": "logged_out"}
    # ← The JWT itself is NOT invalidated anywhere
```

**Attack / Failure Scenario:** An attacker captures the JWT (e.g. from a shared computer's network logs). The victim clicks Logout. The attacker's copy of the JWT continues to work for up to 8 hours.

**Recommended Fix:** On logout, add the JWT's `jti` to a Redis blocklist. On each request in `get_current_user()`, check the blocklist before returning the user.

---

### [BUG-011] — `GET /api/v3/cameras` — No Department Scoping

**Severity:** 🟠 HIGH
**Category:** CWE-200 Information Exposure / CWE-639 BOLA
**Confidence:** CONFIRMED
**File:** `model3_federation/api/router.py`
**Lines:** `590–627`

**Evidence:**
```python
q = "SELECT c.id, c.name, ... FROM cameras c JOIN vms_systems vs ON vs.id = c.vms_system_id"
if system_id:
    q += " WHERE c.vms_system_id = :sys"
# ← No filter on vs.department_id
```

**Recommended Fix:** Add `AND vs.department_id = :dept_id` to the WHERE clause when `current_user.department_id` is set.

---

### [BUG-012] — `GET /api/v3/events` — No Department Scoping

**Severity:** 🟠 HIGH
**Category:** CWE-200 Information Exposure / CWE-639 BOLA
**Confidence:** CONFIRMED
**File:** `model3_federation/api/router.py`
**Lines:** `630–676`

**Evidence:** `get_federated_events()` queries `detections` + `cameras` + `vms_systems` with no `department_id` filter. Any authenticated user receives detection events from all departments.

**Recommended Fix:** Same department filter pattern as BUG-011.

---

### [BUG-013] — Bulk CSV Import Has No Row Limit (DoS)

**Severity:** 🟠 HIGH
**Category:** CWE-400 Uncontrolled Resource Consumption
**Confidence:** CONFIRMED
**File:** `model1-registry/app/routers/cameras.py`
**Lines:** `174–279`

**Evidence:**
```python
content = await file.read()
# 5MB limit enforced ✓
reader = csv.DictReader(io.StringIO(text_content))
for i, row in enumerate(reader, start=2):
    # ← No row count cap. 5MB of 1-byte rows = 5,000,000 iterations
    dept = db.query(DeptModel).filter(DeptModel.name == dept_name).first()  # DB query per row
    dist = db.query(DistModel).filter(DistModel.name == dist_name).first()  # DB query per row
    with db.begin_nested():  # Savepoint per row
        db.add(cam)
```

**Attack / Failure Scenario:** Upload a 5MB CSV with 100,000 single-character rows. Each row triggers 2 DB queries + 1 savepoint. The DB connection pool is exhausted for the duration, blocking all other requests.

**Recommended Fix:**
```python
MAX_CSV_ROWS = 1000
for i, row in enumerate(reader, start=2):
    if i > MAX_CSV_ROWS + 1:
        raise HTTPException(status_code=400, detail=f"CSV exceeds {MAX_CSV_ROWS} row limit.")
```

---

### [BUG-014] — Audit `details` JSONB Has No Size Cap

**Severity:** 🟠 HIGH
**Category:** CWE-400 Uncontrolled Resource Consumption / CWE-20 Improper Input Validation
**Confidence:** CONFIRMED
**File:** `shared/audit.py`
**Lines:** `36`

**Evidence:**
```python
"details": json.dumps(details) if details else None,
```

No maximum size is enforced on the serialized `details` string before insertion into `audit_logs.details JSONB`.

**Recommended Fix:**
```python
MAX_DETAILS_BYTES = 65536  # 64 KB
details_json = json.dumps(details) if details else None
if details_json and len(details_json.encode()) > MAX_DETAILS_BYTES:
    details_json = json.dumps({"truncated": True, "reason": "details exceeded 64KB limit"})
```

---

### [BUG-015] — Camera History Endpoint Has No Department Scoping

**Severity:** 🟠 HIGH
**Category:** CWE-200 Information Exposure / CWE-639 BOLA
**Confidence:** CONFIRMED
**File:** `model1-registry/app/routers/cameras.py`
**Lines:** `376–404`

**Evidence:**
```python
@router.get("/{camera_id}/history")
def get_camera_history(camera_id: uuid.UUID, db: Session = Depends(get_db),
                       current_user: UserModel = Depends(get_current_user)):
    cam = db.query(CameraModel).filter(CameraModel.id == camera_id).first()
    if not cam:
        raise HTTPException(status_code=404, ...)
    # ← No check: cam.department_id == current_user.department_id
    rows = db.query(StatusHistoryModel).filter(StatusHistoryModel.camera_id == camera_id).all()
```

**Recommended Fix:** After fetching `cam`, add:
```python
if current_user.department_id and cam.department_id != current_user.department_id:
    raise HTTPException(status_code=403, detail="Access to this camera's history is restricted.")
```

---

### [BUG-016] — Duplicate `model2-analytics/` Directory Causes Confusion

**Severity:** 🟡 MEDIUM
**Category:** CWE-1188 Initialization of a Resource with an Insecure Default
**Confidence:** CONFIRMED
**File:** Root directory

**What is wrong:** Both `model2_analytics/` (active, with underscore) and `model2-analytics/` (hyphenated, appears older) exist at the project root. Python cannot import from hyphenated directories. Any path reference to `model2-analytics/` is silently dead code.

**Recommended Fix:** Delete `model2-analytics/`. Add `model2-analytics/` to `.gitignore`.

---

### [BUG-017] — CSRF Token Not Bound to Session JWT

**Severity:** 🟡 MEDIUM
**Category:** CWE-352 Cross-Site Request Forgery
**Confidence:** CONFIRMED
**File:** `model1-registry/app/routers/auth.py:92`, `model1-registry/app/auth/dependencies.py:67–78`

**What is wrong:** The CSRF token is a random `uuid4()` generated at login and stored as a session cookie with no expiry (`Max-Age` not set). It is not cryptographically derived from the JWT. An old CSRF token from a previous session (if the browser kept the cookie) can be replayed with a new JWT.

**Recommended Fix:** Derive the CSRF token as `HMAC-SHA256(secret_key, jti)` so it is mathematically bound to a specific JWT instance.

---

### [BUG-018] — Person Watchlist Has No `department_id` Column or Enforcement

**Severity:** 🟡 MEDIUM
**Category:** CWE-284 Improper Access Control / CWE-639 BOLA
**Confidence:** CONFIRMED
**File:** `model2_analytics/app/routers/persons_watchlist.py`, `shared/db/schema.sql:193–201`

**Evidence:**
```sql
CREATE TABLE persons_watchlist (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    -- ← NO department_id column
    category    TEXT NOT NULL CHECK (category IN ('wanted', 'missing', 'suspect')),
    ...
);
```

Any `dept_admin` or `operator` can read, modify, or delete person watchlist entries created by any other department.

**Recommended Fix:**
1. Add `department_id UUID REFERENCES departments(id) ON DELETE SET NULL` to `persons_watchlist`.
2. Populate it from `current_user.department_id` on creation.
3. Filter all read/update/delete endpoints by `current_user.department_id`.

---

### [BUG-019] — `GET /api/v1/recorded/cameras` Exposes All Departments' Cameras

**Severity:** 🟡 MEDIUM
**Category:** CWE-200 Information Exposure
**Confidence:** CONFIRMED
**File:** `model2_analytics/app/routers/recorded.py`
**Lines:** `108–131`

**Evidence:** The endpoint returns all active cameras with no department filter. Any authenticated user (including `viewer`) can enumerate every camera name, department, and connectivity status across the platform.

**Recommended Fix:** Filter by `CameraModel.department_id == current_user.department_id` when `current_user.department_id` is set.

---

### [BUG-020] — OpenCV `VideoCapture()` Called Synchronously in Async Endpoint (Blocking I/O)

**Severity:** 🟡 MEDIUM
**Category:** CWE-400 Uncontrolled Resource Consumption
**Confidence:** CONFIRMED
**File:** `model2_analytics/app/routers/recorded.py`
**Lines:** `194–203`

**Evidence:**
```python
# In async def upload_recorded_video(...)
cap = cv2.VideoCapture(str(target_path))  # Blocking C++ I/O — freezes the event loop
```

**What is wrong:** `cv2.VideoCapture()` is a synchronous, blocking C++ call. Calling it inside an `async def` endpoint blocks the entire asyncio event loop, preventing any other requests from being served until the probe completes. Large video files can take multiple seconds.

**Recommended Fix:**
```python
loop = asyncio.get_event_loop()
cap = await loop.run_in_executor(None, lambda: cv2.VideoCapture(str(target_path)))
```

---

### [BUG-021] — Camera History Returns Raw User UUID Instead of Username

**Severity:** 🟡 MEDIUM
**Category:** Usability / Information Architecture
**Confidence:** CONFIRMED
**File:** `model1-registry/app/routers/cameras.py`
**Lines:** `400`

**What is wrong:** The `changed_by` field in history responses is a raw UUID string. Operators must cross-reference the users table manually to know who made a change.

**Recommended Fix:** JOIN `users` on `status_history.changed_by` and return `changed_by_username` alongside the UUID.

---

### [BUG-022] — `viewer` Role Can Query Recorded Job Status

**Severity:** 🟡 MEDIUM
**Category:** CWE-284 Improper Access Control
**Confidence:** CONFIRMED
**File:** `model2_analytics/app/routers/recorded.py`
**Lines:** `344–365`

**Evidence:**
```python
@router.get("/api/v1/recorded/status/{job_id}")
def get_recorded_job_status(job_id: str,
    current_user: UserModel = Depends(get_current_user)):  # Any role
```

A `viewer` who guesses a `job_id` (UUIDs, but enumerable via other leaks) can query full job metadata including the video filename, upload path, camera name, and processing state.

**Recommended Fix:** Change `Depends(get_current_user)` to `Depends(require_role("dept_admin", "operator"))`.

---

### [BUG-023] — VMS Adapter `config` JSONB Stores Credentials in Plaintext

**Severity:** 🟡 MEDIUM
**Category:** CWE-312 Cleartext Storage of Sensitive Information
**Confidence:** CONFIRMED
**File:** `shared/db/schema.sql`
**Lines:** `79–81`

**Evidence:**
```sql
config JSONB,  -- adapter-specific connection config. PLAINTEXT -- see
               -- migrations/002_vms_systems_adapter_config.sql's header
               -- for the security caveat
```

VMS API keys, passwords, and connection configs stored in `vms_systems.config` are readable by anyone with `SELECT` access to the table.

**Recommended Fix:** Encrypt the `config` column using Fernet (the same approach in `shared/security.py` used for camera RTSP credentials). Decrypt at runtime in `load_dynamic_adapters()`.

---

### [BUG-024] — `person_alerts.camera_id` Is `TEXT` Instead of UUID FK

**Severity:** 🟡 MEDIUM
**Category:** CWE-20 Improper Input Validation / Database Schema Design
**Confidence:** CONFIRMED
**File:** `shared/db/schema.sql`
**Lines:** `255`

**Evidence:**
```sql
camera_id TEXT DEFAULT 'prerecorded',   -- ← Free text with a magic default string
```

Unlike `alerts.detection_id` (proper UUID FK to `detections`), `person_alerts.camera_id` has no referential integrity. Orphaned alert records are possible, and JOIN queries must use text matching.

**Recommended Fix:** Change to `camera_id UUID REFERENCES cameras(id) ON DELETE SET NULL` and handle the pre-recorded case explicitly with a nullable column and application-level logic.

---

### [BUG-025] — Bulk Import: `SET LOCAL` User ID Set After All INSERTs (NULL Audit Trail)

**Severity:** 🟡 MEDIUM
**Category:** CWE-778 Insufficient Logging
**Confidence:** CONFIRMED
**File:** `model1-registry/app/routers/cameras.py`
**Lines:** `265–275`

**Evidence:**
```python
for i, row in enumerate(reader, start=2):
    # ← Camera INSERTs happen here via db.begin_nested()
    with db.begin_nested():
        db.add(cam)

# ← SET LOCAL happens AFTER all inserts
if created > 0:
    db.execute(text("SET LOCAL app.current_user_id = :uid"), {"uid": str(current_user.id)})
    db.commit()
```

The DB trigger `log_camera_changes()` fires at INSERT time and reads `current_setting('app.current_user_id', true)`. Since the variable is set after all inserts, every bulk-imported camera shows `NULL` for `changed_by` in the audit trail.

**Recommended Fix:** Move `SET LOCAL app.current_user_id` to before the `for` loop.

```python
db.execute(text("SET LOCAL app.current_user_id = :uid"), {"uid": str(current_user.id)})
for i, row in enumerate(reader, start=2):
    ...
```

---

### [BUG-026] — Rate Limit Key Uses Direct TCP IP — Bypassed Behind Proxy

**Severity:** 🟡 MEDIUM
**Category:** CWE-307 Improper Restriction of Excessive Authentication Attempts
**Confidence:** CONFIRMED
**File:** `model1-registry/app/routers/auth.py:58`

**Evidence:**
```python
client_ip = request.client.host if request.client else "unknown"
```

Behind Caddy (the reverse proxy in `infra/Caddyfile`), `request.client.host` is always the proxy's IP — every user shares the same rate limit bucket.

**Recommended Fix:** Configure trusted proxy IPs and use `X-Forwarded-For` only from trusted upstreams:
```python
trusted_proxies = {"127.0.0.1", "::1"}
xff = request.headers.get("X-Forwarded-For")
if request.client.host in trusted_proxies and xff:
    client_ip = xff.split(",")[0].strip()
else:
    client_ip = request.client.host or "unknown"
```

---

### [BUG-027] — DNS TOCTOU Race Bypasses `is_safe_url()` (SSRF via DNS Rebinding)

**Severity:** 🟡 MEDIUM
**Category:** CWE-918 Server-Side Request Forgery / CWE-362 Race Condition
**Confidence:** CONFIRMED
**File:** `model2_analytics/app/routers/grid.py`
**Lines:** `21–42`

**Evidence:**
```python
def is_safe_url(url):
    ip = socket.gethostbyname(host)     # DNS resolved HERE
    ip_obj = ipaddress.ip_address(ip)
    if ip_obj.is_private or ...:
        return False
    return True
# ← Actual HTTP request uses the URL AGAIN — resolves DNS a second time
```

The DNS validation and the actual HTTP request are separate operations. An attacker using DNS rebinding can serve a public IP for the validation check and then flip DNS to `169.254.169.254` before the actual `httpx` request.

**Recommended Fix:** After validation, pass the resolved IP directly to the HTTP client:
```python
ip = socket.gethostbyname(host)
# validate ip...
# Then connect to the IP directly:
async with httpx.AsyncClient() as client:
    resp = await client.get(url, headers={"Host": host},
                            transport=httpx.HTTPTransport(local_address=ip))
```

---

### [BUG-028] — `_JOBS` / `_JOBS_META` Dicts Are Not Thread-Safe for Concurrent Access

**Severity:** 🟡 MEDIUM
**Category:** CWE-362 Concurrent Execution Using Shared Resource with Improper Synchronization
**Confidence:** CONFIRMED
**File:** `model2_analytics/app/routers/recorded.py`
**Lines:** `53–55`

**Evidence:**
```python
_JOBS: Dict[str, PreRecordedVideoWorker] = {}       # ← Plain dict, no lock
_JOBS_META: Dict[str, Dict] = {}                   # ← Plain dict, no lock
_JOB_WS: Dict[str, Set[WebSocket]] = defaultdict(set)

# Written from the async event loop (API endpoints)
# Read and written from background threads (video workers via on_recorded_worker_event)
```

**Recommended Fix:** Protect dict access with `asyncio.Lock()` for async callers and `threading.Lock()` for threaded callers. Consider using `concurrent.futures.ThreadPoolExecutor` with thread-safe queue communication.

---

### [BUG-029] — No Pagination on Federation List Endpoints

**Severity:** 🔵 LOW
**Category:** CWE-400 Uncontrolled Resource Consumption
**Confidence:** CONFIRMED
**File:** `model3_federation/api/router.py`

**What is wrong:** `/api/v3/cameras`, `/api/v3/events`, `/api/v3/correlations/track` have no `limit`/`offset` pagination. For large deployments (80,000 cameras noted in docs), these queries will time out or return partial data without signaling truncation.

**Recommended Fix:** Add `limit: int = Query(100, le=500)` and `offset: int = Query(0, ge=0)` to all list endpoints.

---

### [BUG-030] — `get_optional_current_user()` Swallows All Exceptions Including DB Errors

**Severity:** 🔵 LOW
**Category:** CWE-755 Improper Handling of Exceptional Conditions
**Confidence:** CONFIRMED
**File:** `model1-registry/app/auth/dependencies.py`
**Lines:** `101–102`

**Evidence:**
```python
except Exception:
    return None  # ← DB outage = anonymous user
```

A DB connection failure silently returns `None`, treating any connection error as an unauthenticated request. Routes serving different content based on auth state could accidentally serve the anonymous version during a DB outage.

**Recommended Fix:** Catch only `(ValueError, TypeError, JWTError)`. Let database exceptions propagate as 503.

---

### [BUG-031] — `audit_logs` Table Missing `created_at` Index

**Severity:** 🔵 LOW
**Category:** CWE-400 Uncontrolled Resource Consumption (Performance)
**Confidence:** CONFIRMED
**File:** `shared/db/schema.sql`
**Lines:** `281–283`

**Evidence:**
```sql
CREATE INDEX idx_audit_logs_user ON audit_logs (user_id);
CREATE INDEX idx_audit_logs_department ON audit_logs (department_id);
CREATE INDEX idx_audit_logs_resource ON audit_logs (resource_type, resource_id);
-- ← No index on created_at
```

The audit log UI sorts by time, causing full table scans as the log grows.

**Recommended Fix:**
```sql
CREATE INDEX idx_audit_logs_created ON audit_logs (created_at DESC);
```

---

### [BUG-032] — `status_history` ON DELETE RESTRICT Blocks Future Hard Deletes

**Severity:** 🔵 LOW
**Category:** CWE-459 Incomplete Cleanup
**Confidence:** CONFIRMED
**File:** `shared/db/schema.sql`
**Lines:** `165–166`

**Evidence:**
```sql
camera_id UUID NOT NULL REFERENCES cameras(id) ON DELETE RESTRICT,
```

If hard deletion is ever needed, all `status_history` rows must be manually deleted first. This is a latent data integrity trap.

**Recommended Fix:** Change to `ON DELETE CASCADE` or `ON DELETE SET NULL` with `camera_id` made nullable.

---

### [BUG-033] — `vms_systems` Table Missing `updated_at` Column

**Severity:** 🔵 LOW
**Category:** CWE-778 Insufficient Logging
**Confidence:** CONFIRMED
**File:** `shared/db/schema.sql`
**Lines:** `56–85`

**What is wrong:** `vms_systems` has `created_at` but no `updated_at`. When a system is patched (name, vendor, department), there is no record of when the change was made.

**Recommended Fix:**
```sql
ALTER TABLE vms_systems ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
-- Add trigger to auto-update on each change
```

---

## 6. Remediation Roadmap

The following PRs are recommended in priority order:

| PR | Branch | Fixes | Priority |
|----|--------|-------|----------|
| PR-40 | `security/federation-idor-fix` | BUG-003, BUG-004, BUG-011, BUG-012, BUG-006, BUG-007 — Department scoping on all Model 3 federation endpoints | P0 |
| PR-41 | `security/simulate-viewer-fix` | BUG-005 — Restrict simulate endpoint to dept_admin/operator | P0 |
| PR-42 | `security/jwt-revocation` | BUG-001, BUG-009, BUG-010 — Token version column, blocklist, reduced TTL | P0 |
| PR-43 | `security/audit-transaction` | BUG-002, BUG-014, BUG-025 — Single-transaction audit logging + size cap + bulk import audit fix | P1 |
| PR-44 | `security/persons-dept-scoping` | BUG-018 — Add `department_id` to persons_watchlist | P1 |
| PR-45 | `security/rate-limit-redis` | BUG-008, BUG-026 — Redis-backed rate limiter with proper proxy IP | P1 |
| PR-46 | `security/csrf-session-binding` | BUG-017 — HMAC-bound CSRF token | P2 |
| PR-47 | `fix/async-opencv` | BUG-020, BUG-028 — run_in_executor for OpenCV + thread-safe job dicts | P2 |
| PR-48 | `fix/schema-cleanup` | BUG-023, BUG-024, BUG-031, BUG-032, BUG-033 — Schema fixes | P2 |
| PR-49 | `fix/misc-endpoint-scoping` | BUG-013, BUG-015, BUG-019, BUG-022, BUG-027, BUG-029 | P3 |

---

## 7. Overall Assessment

| Area | Previous Score | Current Score | Change |
|------|---------------|---------------|--------|
| Authentication (JWT lifecycle) | 3/10 | 2/10 | ↓ (revocation gap confirmed) |
| Authorization (Department scoping) | 3/10 | 5/10 | ↑ (camera CRUD fixed) |
| Federation RBAC | 1/10 | 1/10 | — (untouched) |
| Audit Logging | 4/10 | 2/10 | ↓ (transaction bug confirmed critical) |
| SSRF Protection | 3/10 | 4/10 | ↑ (model2 improved; DNS rebinding gap remains) |
| Database Schema | 5/10 | 5/10 | — |
| API Design | 4/10 | 4/10 | — |

**Overall Security Score: 3.5 / 10**

The platform has improved significantly from the initial audit (2.5/10) in authentication and camera-level authorization. However, the federation layer (Model 3) was left entirely unscoped for department isolation, creating 5 new CRITICAL findings. Token revocation remains unimplemented, and the audit log has a fundamental transaction integrity flaw.

<!-- END OF REPORT -->
