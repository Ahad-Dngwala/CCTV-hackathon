# Security, Auth & Auditability

This document is deliberately cross-model rather than filed under
Model 1. Authentication, RBAC, and the audit trail are platform
concerns — Model 1 built the first version of all three because it
shipped first, but Model 2's upload/watchlist endpoints and Model 3's
federation layer sit behind the same login session and are expected to
extend this document as they add their own security-relevant surfaces
(a federation adapter's own credential handling, for instance, or
Model 2's face-photo upload path) rather than each maintaining a
separate, harder-to-audit copy of "how auth works here."

`HackathonPortal.md`'s bonus-scoring criteria name this explicitly:
*"enhanced cybersecurity, privacy protection, auditability, or
role-based access controls."* What follows is what's actually built,
what's deliberately deferred, and where the line between those two
currently sits — stated plainly rather than blurred, because a
reviewer can tell the difference between a documented scope decision
and a gap someone hoped wouldn't come up.

---

## 1. Authentication

JWT, carried in an **httpOnly cookie** (`access_token`) rather than
`localStorage` — the deliberate choice against the more common
SPA pattern of storing the token client-side and attaching it manually
to each request. httpOnly means client-side JavaScript can't read the
token at all, which closes off an entire class of XSS-driven token
theft; the trade-off is the usual one for cookie auth (CSRF exposure),
mitigated here with `samesite="lax"`. A `Bearer` header is also
accepted (`app/auth/dependencies.py::get_token_from_request` checks the
cookie first, then falls back to the `Authorization` header) — useful
for anything hitting the API directly rather than through the browser
session, like a script exercising `/api/v1/cameras` for the
government-feed evaluation.

- **Hashing:** bcrypt, via `app/auth/security.py`. Never plaintext, never
  reversible.
- **Token contents:** user id, username, role, department id, standard
  `exp`/`iat` claims. Signed `HS256`.
- **Expiry:** 8 hours (`ACCESS_TOKEN_EXPIRE_MINUTES`), a session-length
  choice appropriate for an operator working a shift, not a long-lived
  API token.
- **Cookie `secure` flag** tracks `settings.DEBUG` rather than being a
  separate setting: `DEBUG=True` (local dev/test default) sends the
  cookie over plain HTTP, `DEBUG=False` (the docker-compose default)
  requires HTTPS. This piggybacks on the app's one existing prod/dev
  switch instead of introducing a second flag that could drift out of
  sync with it.
- **`SECRET_KEY` fail-fast:** the key that signs every session ships
  with a public, checked-in placeholder value so local dev and CI work
  without a `.env` file. If the app ever boots with `DEBUG=False` *and*
  that placeholder still in place, it refuses to start rather than
  silently signing real sessions with a key anyone who's read the repo
  already knows. `DEBUG=True` is treated as an explicit opt-in to the
  insecure default; anything else must set a real, secret `SECRET_KEY`.

## 2. Login rate limiting

`POST /api/v1/auth/login` is protected by an in-memory sliding-window
limiter (`app/auth/rate_limit.py`): 5 failed attempts within a 5-minute
window locks that key out for 15 minutes (all three numbers are
env-configurable). The key is `(client IP, username)`, not username
alone — deliberately, so one attacker can't remotely lock a specific
real user out of their own account by repeatedly failing their login
from an arbitrary IP; they'd have to be attacking from the same IP the
real user actually logs in from. A successful login clears the failure
count for that key entirely, so it's consecutive failures that trigger
a lockout, not a lifetime tally.

This is intentionally simple — in-process memory, no Redis, no shared
table — because that's the right amount of complexity for how the app
actually runs today: one `app` container, no horizontal scaling
anywhere in `infra/`. The moment that changes (multiple app instances
behind a load balancer), this needs a shared backend, since separate
processes would each keep independent counters and the lockout would
stop being effective across all of them. Flagged here explicitly so
it isn't rediscovered the hard way during a scale-up.

## 3. Role-based access control

Three roles, defined at the database level
(`CHECK role IN ('dept_admin', 'operator', 'viewer')`) and enforced at
the **router dependency layer**, not hidden in the UI:

| Role | Can do |
|---|---|
| `dept_admin` | Full camera CRUD + bulk import, scoped to their own department if one is set; global if not |
| `operator` | Read access, plus the global/audit views; day-to-day monitoring |
| `viewer` | Read-only; explicitly excluded from the audit trail (see below) |

`require_role(*roles)` in `app/auth/dependencies.py` is a small
dependency factory — `Depends(require_role("dept_admin"))` — used
everywhere a mutation or a sensitive read needs a specific role, rather
than every endpoint hand-rolling its own role check. Department
scoping is layered on top of role checking, not a replacement for it:
a `dept_admin` with a `department_id` set can only create, update, or
delete cameras in their own department (`403` otherwise), and bulk
import enforces the same rule per CSV row rather than at the file
level, so one file can't be used to slip a camera into a department
its uploader doesn't manage.

## 4. Audit trail

`status_history` is written by a **Postgres trigger**
(`shared/db/triggers.sql`), not by application code calling a "log
this" function — every tracked field change on `cameras` (status
changes, soft deletes, metadata edits) gets a row automatically, which
means there's no code path that can mutate a camera and forget to
log it. Soft-deleting a camera specifically stamps
`decommissioned_at` and writes the trigger-generated row in the same
operation.

Two read surfaces expose this data with two different scoping rules,
and the difference is documented rather than papered over:

- `GET /api/v1/audit` (global feed) — restricted to `dept_admin` and
  `operator`; department-scoped callers see only their own department's
  history.
- `GET /api/v1/cameras/{id}/history` (per-camera) — requires only
  authentication, no role or department gate. See
  [docs/model1/README.md §4.1](model1/README.md#41-cameras--approuterscamerasp)
  for the reasoning and the narrower real-world exposure this implies.

## 5. Transport security

TLS termination is handled by Caddy/Nginx in `infra/`, in front of the
app — the app itself speaks plain HTTP behind the reverse proxy, which
is what makes the cookie's `secure` flag (§1) meaningful rather than
decorative once a real domain is in front of it.

## 6. What's documented but not built

Named explicitly, per `Project_Context.md` §6, rather than implied to
already exist:

- **At-rest encryption** for the watchlist/detection tables specifically
  (`pgcrypto` or disk-level) — flagged as a pre-production requirement,
  not implemented for the hackathon build.
- **Network segmentation** — VMS-ingestion network conceptually
  separate from the public dashboard network. Described in the
  architecture diagrams; the actual demo runs on one VPS.
- **API gateway / rate limiting at the edge** (Kong, or Nginx-level) —
  the statewide-scale answer to abusive traffic generally, distinct
  from the login-specific limiter in §2. Not needed at 50-camera demo
  scale, and a natural extension point for whichever model ends up
  owning the public-facing edge as the platform grows.
- **Encryption at rest for `vms_systems.config`** — Model 3's
  config-driven VMS onboarding (`docs/model3/README.md` §4) stores
  adapter credentials (a Windy API key, ONVIF host/username/password)
  as plain `JSONB`, same as `migrations/002_vms_systems_adapter_config.sql`'s
  own header already flags. That matches how RTSP credentials are
  handled elsewhere in this codebase (`shared/adapters/factory.py`),
  not a one-off gap specific to federation — but it's a real one:
  before any of this holds a real department's credentials, `config`
  needs application-layer encryption (Fernet, key from an env var or
  secrets manager) or the secret itself needs to live in a proper
  secrets manager with only a reference stored here, not a DB-level
  "encrypted column" the app server can still read unencrypted anyway.

## 7. For Model 2 and Model 3

If you're adding a security-relevant surface — a new upload endpoint,
a federation adapter's credential handling, a new WebSocket channel —
the pattern to match is: enforce at the dependency layer
(`Depends(get_current_user)` / `Depends(require_role(...))`), never
only in the template or the frontend JS, and add a section here rather
than leaving the reasoning in a code comment only you can find later.
