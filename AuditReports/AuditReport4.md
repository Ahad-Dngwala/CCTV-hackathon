# EyesOnGuj — Comprehensive Security Audit Report

**Report Path:** `AuditReports/AuditReport4.md`

## 1. Executive Summary

This report documents the findings of a deep, code-level security audit and engineering review of the `Vishmayraj/EyesOnGuj` repository. While previous audits (`AuditReport1`, `AuditReport2`, `AuditReport3`) addressed several issues, this review establishes that fundamental architectural vulnerabilities remain—particularly regarding resource-level authorization (BOLA/IDOR), WebSocket security, secret management, and outbound network controls (SSRF). 

A 15-PR remediation roadmap has been devised to address these issues systematically, ensuring that authenticated users cannot access or control data outside their department, that VMS credentials are secure, and that uploaded media/analysis jobs are properly scoped and constrained.

## 2. Audit Scope

The audit covered the `main` branch of the repository, including:
- `model1-registry/` (Core registry, Auth, API routers)
- `model2_analytics/` (WebSockets, Video processing, Face detection)
- `model3_federation/` (VMS Federation adapters)
- `shared/` (Database schema, Models)
- `infra/` (Docker, docker-compose)
- API routers, configuration, file uploads, AI pipelines.

**The core architectural flaw:** The authorization model is `JWT -> Role -> Endpoint`. It currently lacks a consistent `Department Scope -> Resource Ownership` check, leaving many endpoints vulnerable to BOLA/IDOR.

## 3. Security Posture Summary

| Category | Status | Key Observation |
| -------- | ------ | --------------- |
| Authentication | Fair | JWT + Cookie implementations exist, but WebSockets lack unified authentication. |
| Authorization (RBAC/IDOR) | **Poor** | Missing department-level and resource-level isolation across endpoints. |
| Secret Management | **Poor** | VMS credentials stored in plaintext JSONB. |
| Media/Uploads | Fair | Only extension validation is used; lacks deep probing/resource limits. |
| Federation/SSRF | **Poor** | Adapters allow outbound connections without destination validation. |
| Infrastructure | Fair | Needs stricter container/image version pinning and network isolation. |

## 4. Findings Summary

| ID | Severity | Category | Finding | File(s) | Status |
| -- | -------- | -------- | ------- | ------- | ------ |
| SA-001 | 🔴 Critical | Authz / IDOR | Missing department-scoped authorization for reads | `model1-registry/app/routers/cameras.py`, etc. | Unresolved |
| SA-002 | 🔴 Critical | WebSockets | Face-detection WebSocket is unauthenticated | `model2_analytics/app/routers/face_detection.py` | Unresolved |
| SA-003 | 🔴 Critical | Authz / IDOR | Recorded analysis job control lacks ownership check | `model2_analytics/app/routers/recorded.py` | Unresolved |
| SA-004 | 🔴 Critical | Authz / IDOR | Model 3 federation lacks department isolation | `model3_federation/api/router.py` | Unresolved |
| SA-005 | 🔴 Critical | Secrets | VMS adapter credentials stored as plaintext | `shared/db/schema.sql` | Unresolved |
| SA-006 | 🔴 High | Authz | Authenticated stream endpoints lack department authz | `model1-registry/app/routers/streams.py` | Unresolved |
| SA-007 | 🟠 High | SSRF | Federation dynamic adapter allows outbound connections to arbitrary targets | `model3_federation/api/router.py` | Unresolved |
| SA-008 | 🟠 High | Uploads | Extension-only validation and expensive media probing | `model2_analytics/app/routers/recorded.py` | Unresolved |
| SA-009 | 🟠 High | CSRF | Cookie-authenticated state-changing endpoints lack explicit CSRF | `model1-registry/app/auth/security.py` | Unresolved |

## 5. Detailed Findings

### SA-001 — Missing department-scoped authorization for reads (IDOR)
**Severity:** 🔴 Critical
**CWE:** CWE-284 (Improper Access Control), CWE-639 (BOLA/IDOR)
**Affected Components:** Cameras, Watchlists, Events
**File(s):** `model1-registry/app/routers/cameras.py`

#### Description
While the `department_id` is present on the `UserModel` and `CameraModel`, endpoints such as `get_camera(camera_id)` only verify that the user is authenticated (via `Depends(get_current_user)`). There is no check to ensure `current_user.department_id == camera.department_id`. 

#### Evidence
```python
# In model1-registry/app/routers/cameras.py
@router.get("/{camera_id}", response_model=CameraResponse)
def get_camera(
    camera_id: UUID,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    camera = db.query(CameraModel).filter(CameraModel.id == camera_id).first()
    # Missing: if current_user.department_id and camera.department_id != current_user.department_id: raise 403
```

#### Recommended Fix
Create a shared authorization policy `ensure_department_access(resource, current_user)` and apply it across all endpoints.

---

### SA-002 — Face-detection WebSocket is unauthenticated
**Severity:** 🔴 Critical
**File(s):** `model2_analytics/app/routers/face_detection.py`

#### Description
The WebSocket endpoint for face detection accepts connections without validating a JWT or session token. An attacker can connect and potentially subscribe to sensitive face analysis streams.

#### Recommended Fix
Introduce an `authenticate_websocket` dependency to parse the JWT or cookie before `await websocket.accept()`.

---

### SA-003 — Recorded analysis jobs have an ownership loophole
**Severity:** 🔴 Critical
**File(s):** `model2_analytics/app/routers/recorded.py`

#### Description
Jobs are stored in memory (`_JOBS`, `_JOBS_META`), and their state-changing routes (`/start`, `/pause`, `/stop`) use the job UUID but fail to consistently authorize the requester against the `uploaded_by` or `department_id` metadata.

#### Recommended Fix
Persist jobs in a database table with an explicit `owner_user_id` and enforce ownership checks on all job control endpoints.

---

### SA-004 — Model 3 federation lacks department isolation
**Severity:** 🔴 Critical
**File(s):** `model3_federation/api/router.py`

#### Description
VMS operations require `dept_admin` or `operator` roles, but fail to check if the manipulated VMS belongs to the user's department.

#### Recommended Fix
Apply the `ensure_department_access` policy for VMS models.

---

### SA-005 — VMS credentials are stored in plaintext
**Severity:** 🔴 Critical
**File(s):** `shared/db/schema.sql` (vms_systems.config)

#### Description
Federation adapters store credentials inside a `config` JSONB column in plaintext. A database compromise immediately exposes downstream VMS systems.

#### Recommended Fix
Introduce encryption (e.g., Fernet symmetric encryption) using an environment-provided key before storing credentials.

---

### SA-007 — Federation dynamic adapter allows SSRF
**Severity:** 🟠 High
**File(s):** `model3_federation/api/router.py`

#### Description
The `/api/v3/systems/test-connection` and VMS onboarding flows allow a user to specify a `host` and `base_url`, which the server immediately attempts to connect to. This creates an SSRF vector if internal IP ranges are targeted.

#### Recommended Fix
Implement IP validation to block loopback, link-local, and private metadata IPs before initiating the connection.

---

## 6. Existing ChatGPT Findings — Verification Matrix

| Previous Finding | Current Status | Evidence | Notes |
| ---------------- | -------------- | -------- | ----- |
| PR-01 (IDOR) | **VERIFIED** | `cameras.py` lacks department checks on reads. | Still vulnerable. |
| PR-02 (WS Auth) | **VERIFIED** | `face_detection.py` lacks token validation. | Still vulnerable. |
| PR-03 (Job Ownership)| **VERIFIED** | `recorded.py` uses UUIDs, no owner check. | Still vulnerable. |
| PR-04 (VMS IDOR) | **VERIFIED** | `model3_federation` missing department filters. | Still vulnerable. |
| PR-05 (Plaintext VMS)| **VERIFIED** | Schema uses `config JSONB`. | Still vulnerable. |
| PR-07 (Data Leakage) | **VERIFIED** | Response schemas leak internal `rtsp_url`. | True, schemas expose internal URLs. |
| PR-09 (CSRF) | **VERIFIED** | Cookie auth used, no explicit CSRF tokens. | True for state-changing routes. |

## 7. Existing AuditReport1/2/3 Findings — Revalidation

| Finding | Old Status | Current Reality | Action |
| ------- | ---------- | --------------- | ------ |
| Rate limiting on login | Done | `slowapi` is implemented on login. | Confirmed fixed. |
| Path Traversal on images | Done | Route sanitizes paths. | Confirmed fixed. |
| Department authz | Claimed Done | Only partial (mutations). Reads are completely open to BOLA. | Reopened as SA-001. |

## 8. Attack Surface Map
- **HTTP API:** Vulnerable to IDOR and SSRF.
- **WebSockets:** Unauthenticated access allows eavesdropping on analysis pipelines.
- **Database:** Stores plaintext credentials; susceptible to data exfiltration.
- **File Uploads:** Susceptible to resource exhaustion through maliciously crafted media.

## 9. Cross-Component / Chained Attack Scenarios
**Chain 1: Complete VMS Compromise**
1. Attacker exploits missing IDOR (SA-004) to access another department's VMS configuration.
2. Because VMS credentials are in plaintext (SA-005) or exposed via the API (SA-007 data leak), the attacker retrieves credentials for a target VMS.

## 10. Security Architecture Improvements
Implement a uniform Authorization middleware or dependency:
```text
JWT Auth -> Role Check -> Department Match -> Resource Ownership -> Action Policy
```
Eliminate ad-hoc `if` statements scattered across endpoints.

## 11. PR Roadmap (15-PR Plan)

1. `fix(authz): enforce department-scoped camera access`
2. `fix(authz): enforce department isolation for watchlists`
3. `fix(authz): add ownership and department scope to analysis jobs`
4. `fix(authz): enforce department scope across federation resources`
5. `fix(authz): scope person watchlists and biometric assets by department`
6. `fix(ws): centralize WebSocket authentication and resource authorization`
7. `security(federation): encrypt VMS adapter credentials at rest`
8. `security(federation): restrict outbound VMS connection targets (SSRF)`
9. `security(auth): add CSRF protection for cookie-authenticated mutations`
10. `feat(audit): record security-sensitive platform actions`
11. `security(uploads): validate media content and enforce processing limits`
12. `refactor(jobs): persist analysis job metadata and enforce lifecycle`
13. `hardening(infra): pin images and isolate internal services`
14. `fix(schema): apply DB constraints for data integrity`
15. `test(security): add authorization and isolation regression suite`

## 12. Security Regression Test Plan
- Write `pytest` fixtures for `viewer`, `operator`, `dept_admin` (Department A and Department B).
- **Test IDOR:** `dept_admin_A` attempting to `GET` a camera belonging to `dept_B` -> Expect 403.
- **Test WS:** Unauthenticated WS connection -> Expect rejection (code 1008).
- **Test SSRF:** Onboard VMS with `host="169.254.169.254"` -> Expect 400 Bad Request.

## 13. Documentation Corrections Required
- Update `README.md` to point to `AuditReports/AuditReport4.md` for the latest security baseline.
- Correct any documentation falsely claiming complete multi-tenant isolation, pending the implementation of the 15-PR roadmap.
