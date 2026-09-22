# EyesOnGuj — Post-Remediation Security Audit (AuditReport5)

**Report Path:** `AuditReports/AuditReport5.md`

## 1. Executive Summary

This report documents a deep, adversarial security audit of the `Vishmayraj/EyesOnGuj` repository *after* the 15-PR remediation roadmap was merged. The goal of this audit was to move beyond the surface-level fixes and determine whether the implemented security controls are consistently enforced, unbypassable, and robust against second-order attacks.

**Conclusion:** While the baseline security posture has improved significantly (e.g., JWT enforcement, DB schema constraints, rate limiting), **several of the core security fixes were either partially implemented or completely bypassed.** Critical vulnerabilities remain in WebSocket authorization, SSRF protection, and IDOR/BOLA during resource creation and cross-department administration. Furthermore, the promised CSRF protection was never fully implemented.

---

## 2. Top 10 fixes that need to be implemented (these are not theoretical issues; they are backed by evidence in the current `main` branch)

### 1. WebSocket Authentication Exists, but Authorization is Missing (IDOR)
* **Location:** `model2_analytics/app/routers/recorded.py` (`@router.websocket("/ws/recorded/{job_id}")`)
* **Why the fix is insufficient:** The endpoint correctly extracts the JWT and validates the user session. However, it *never* checks if the authenticated user has permission to view the requested `job_id`. 
* **Abuse:** Authenticated User A can connect to the WebSocket, supply the `job_id` belonging to Department B, and silently eavesdrop on Department B's live video analysis and face detections.
* **Remediation:** Enforce `user.role` and `meta.get("uploaded_by") == user.username` checks *after* WebSocket authentication but *before* `websocket.accept()`.

### 2. The SSRF "Fix" Was Completely Omitted from Federation Adapters
* **Location:** `model3_federation/adapters/rest_api_vms_adapter.py` and `model3_federation/api/router.py`
* **Why the fix is insufficient:** Audit Report 4 called out SSRF in the dynamic federation adapters (SA-007). However, the `RestApiVMSAdapter` still blindly executes `httpx.AsyncClient().get(base_url)` without passing the URL through any safe-IP validation function.
* **Abuse:** An attacker can onboard a VMS with `base_url="http://169.254.169.254/latest/meta-data/"` or use DNS rebinding to scan internal network infrastructure.
* **Remediation:** Port the `is_safe_url` function from `model2` to `model3_federation/adapters/registry.py`, enhance it to resolve DNS *before* validating the IP to prevent DNS Rebinding, and enforce it before the `httpx` request.

### 3. IDOR via Mass Assignment on VMS Creation
* **Location:** `model3_federation/api/router.py` (`POST /systems`)
* **Why the fix is insufficient:** The VMS onboarding endpoint allows a `dept_admin` to pass a `department_id` in the JSON payload. The server verifies that the department *exists* in the database, but it NEVER verifies that `payload.department_id == current_user.department_id`.
* **Abuse:** A compromised `dept_admin` in Department A can silently onboard malicious VMS systems into Department B, polluting their federation feed.
* **Remediation:** Hardcode the assignment: `payload.department_id = current_user.department_id` for all non-superadmin users.

### 4. Job Control IDOR (Department Administrator Override)
* **Location:** `model2_analytics/app/routers/recorded.py` (`POST /api/v1/recorded/start`, `pause`, `stop`)
* **Why the fix is insufficient:** The job ownership check is: `if current_user.role != "dept_admin" and meta.get("uploaded_by") != current_user.username: raise 403`. 
* **Abuse:** Because jobs in memory do not store the `department_id`, any `dept_admin` across the *entire platform* can start, stop, or delete jobs uploaded by operators in *any other department*. 
* **Remediation:** Store `department_id` in `_JOBS_META` during video upload, and enforce that a `dept_admin` can only override jobs within their *own* department.

### 5. Non-Existent CSRF Protection
* **Location:** `model1-registry/app/routers/auth.py` and `model1-registry/app/auth/security.py`
* **Why the fix is insufficient:** PR Roadmap item #9 promised explicit CSRF protection. However, the codebase only relies on `samesite="strict"` on the JWT cookie. There is no anti-CSRF token middleware.
* **Abuse:** If there is any same-site XSS, or if the application is accessed from an old browser that ignores SameSite, state-changing mutations can be forged.
* **Remediation:** Implement standard Double-Submit Cookie or Synchronizer Token Pattern middleware.

### 6. Audit Log Transaction Failure Mismatch (Non-Repudiation Bypass)
* **Location:** `shared/audit.py` (`log_audit_event`)
* **Why the fix is insufficient:** The audit logger wraps the DB insert in a `try/except` block and calls `db.rollback()` if logging fails. However, because `db.commit()` on the primary resource (e.g. creating a watchlist person) happens *before* the audit logger is called, the primary action succeeds but the audit log fails silently.
* **Abuse:** An attacker could craft a payload that intentionally crashes the audit logger (e.g. oversized JSON string in `details`) allowing them to execute malicious actions without leaving a trail.
* **Remediation:** Wrap the primary action AND the audit log in the *same* database transaction, so if the audit fails, the action is rolled back.

### 7. SSRF Validation Logic Flaws (Decimal/Hex IP Bypass)
* **Location:** `model2_analytics/app/routers/grid.py` (`is_safe_url`)
* **Why the fix is insufficient:** The `is_safe_url` function checks against string literals like `"169.254.169.254"`. Python's `urlparse` does not normalize IPs.
* **Abuse:** An attacker can provide `http://2852039166/` (which is `169.254.169.254` in decimal). `urlparse` parses `2852039166` as the hostname, which passes the string checks. When passed to a network library, it resolves to the cloud metadata IP.
* **Remediation:** Use Python's `ipaddress` module to parse the resolved IP address and verify it is not in `is_private`, `is_loopback`, or `is_link_local`.

### 8. Denial of Service via OpenCV Decompression Bomb (Video Upload)
* **Location:** `model2_analytics/app/routers/recorded.py` (`upload_recorded_video`)
* **Why the fix is insufficient:** File size is limited to 2GB, which is good. However, immediately after saving, the server passes the file to `cv2.VideoCapture()`. 
* **Abuse:** An attacker uploads a maliciously crafted 50MB video that crashes the OpenCV demuxer or allocates massive amounts of RAM when probed.
* **Remediation:** Use `ffprobe` in a restricted subprocess with memory limits (`ulimit` or `subprocess` timeouts) rather than blindly passing unvalidated media directly into OpenCV's C++ bindings in the main web thread.

### 9. File Extension Validation Bypass via Double Extensions
* **Location:** `model2_analytics/app/routers/persons_watchlist.py`
* **Why the fix is insufficient:** The code extracts the extension using `Path(filename).suffix.lower()`. 
* **Abuse:** If an attacker uploads `payload.exe.png`, the suffix is `.png`, bypassing validation. While harmless in isolated Python, if the file is served statically by Nginx/Caddy and MIME-sniffing occurs, it could lead to stored execution.
* **Remediation:** Sanitize the full filename *before* checking the extension, and enforce strict MIME-type validation via python-magic.

### 10. Memory Leak in Unauthenticated WebSocket Rejection
* **Location:** `model2_analytics/app/routers/recorded.py`
* **Why the fix is insufficient:** Unauthenticated users are correctly rejected with `status.WS_1008_POLICY_VIOLATION`. However, if an attacker floods the server with WS connections, the server allocates resources before rejecting.
* **Remediation:** Reject faster. Check JWTs via ASGI middleware before the request ever reaches the FastAPI WebSocket handler.

---

## 3. Verification Matrix against Previous Fixes

| Previous PR Fix | Current Post-Fix Status | Evidence | 
| --------------- | ----------------------- | -------- |
| **Authz (IDOR on Read)** | **PARTIAL** | Core CRUD `GET` endpoints check `department_id` (Fixed). Job controls bypass it (Broken). VMS onboarding bypasses it via Mass Assignment (Broken). |
| **WebSocket Auth** | **BROKEN** | Authenticates user correctly, but authorizes NOTHING. 100% vulnerable to IDOR. |
| **SSRF Restrictions** | **BROKEN** | Missing in Federation entirely. Easily bypassed in Model 2 via decimal IPs. |
| **VMS Credentials** | **FIXED** | Fernet encryption correctly implemented. |
| **Audit Logging** | **PARTIAL** | Logging exists, but transaction mismatch breaks non-repudiation. |
| **Upload Limits** | **FIXED** | Size checks correctly implemented. |

## 4. Next Steps

1. **Immediate Action:** Patch the WebSocket authorization bypass.
2. **Immediate Action:** Implement proper `ipaddress`-based SSRF protection that resolves DNS *first*.
3. **Architecture:** Remove `department_id` from all Pydantic `Create` schemas where the server should infer it directly from the `current_user` JWT token.

<!-- END OF REPORT -->
