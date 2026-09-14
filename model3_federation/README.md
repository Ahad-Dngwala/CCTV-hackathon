# Model 3 — VMS Federation & Middleware

Federates whatever video-management system (VMS) each government
department already runs — Police, RTO, Municipal Corporation, and
whatever else gets onboarded later — into one place: a live event
feed, cross-system vehicle correlation, and watchlist alerting, on top
of Model 1's own camera registry rather than a separate one.

## How this relates to Model 1 and Model 2

Model 3 does not have its own database schema. Early on it did (a
private `federated_systems` / `federated_cameras` / `federated_events`
/ `federated_alerts` / `correlation_results` set of tables), but that
meant a camera reported by a federated VMS and a camera in Model 1's
own registry were two different rows in two different tables for the
same real-world concept — a department isn't guaranteed to run exactly
one VMS, and a VMS isn't guaranteed to be government-owned, but a
camera is still just a camera either way. That schema was dropped in
favor of the shared tables in `shared/db/schema.sql`:

- Every camera Model 3 learns about — from an adapter or from manual
  onboarding — is a normal row in Model 1's own `cameras` table,
  tagged with a `vms_system_id`. A `NULL` `vms_system_id` means "from
  the main grid or manually onboarded [into Model 1]", not
  "federated"; a non-null one traces the camera back to whichever VMS
  reported it.
- Detections, correlation, and alerting reuse Model 1/2's own
  `detections`, `vehicle_tracks`, `vehicles_watchlist`, and `alerts`
  tables (see `correlation/engine.py`'s module docstring for exactly
  how). There is no separate `correlation_results` table — a
  correlation is always derivable from `detections` +
  `vehicle_tracks` + `vms_systems`, computed on demand rather than
  cached somewhere it could drift from the raw sightings.
- Model 3's router mounts into Model 1's own FastAPI app
  (`model1-registry/app/main.py` does a plain
  `app.include_router(federation_router)`) at `/api/v3` — there is no
  separate Model 3 app or process. The federation dashboard
  (`/federation`) and its "VMS Systems" management panel are pages
  served by `model1-registry/app/templates/`, same as every other
  page in the product.

If you're reading older commit messages, docs, or comments that still
mention `federated_systems`/`federated_cameras`/etc. as if they're
current, they're describing the pre-migration design — the tables
above are what actually exists today.

## Data model in plain terms

- **`vms_systems`** (`shared/db/schema.sql`) — one row per distinct
  VMS integration: its name, vendor, protocol, `ownership`
  (`government` or `private`), which `department_id` it belongs to
  (nullable — see "Department resolution" below), and a `status`
  (`connected` / `disconnected` / `unknown`).
- **`cameras.vms_system_id`** — a foreign key from Model 1's own
  camera table back to `vms_systems`. This is the entire link between
  "a camera" and "which federated VMS it came from."
- **Department resolution** — an adapter's cameras report a
  plain-English department hint (e.g. `"Police"`), matched against
  `departments.name`/`category` with `ILIKE` (`registration.py`'s
  `_resolve_department_id`). A hint that matches nothing, or matches
  more than one department, is logged and surfaced as
  `unmatched_department_hint` on `GET /api/v3/systems` rather than
  silently leaving `department_id` `NULL` with no explanation.
  Manually-onboarded systems (see below) skip this entirely — an
  admin picks the department directly, no guessing involved, so they
  never populate `department_hint`.

## Onboarding a new VMS

There are two ways a `vms_systems` row gets created — deliberately
kept as two separate paths, not one replacing the other:

1. **Adapter self-registration** (`registration.py`'s
   `register_adapter()`, called from `start_federation_services()` at
   app startup) — for a VMS with an actual Python adapter written for
   it (subclassing `VMSAdapter` in `adapters/base.py`). The adapter
   connects, reports its cameras, and its `vms_systems` row is
   upserted automatically. This is how the three adapters below get
   onboarded; writing a new one requires code and a deploy.
2. **Manual onboarding** (`POST /api/v3/systems`, `PATCH
   /api/v3/systems/{id}`, `DELETE /api/v3/systems/{id}`, all gated to
   `dept_admin`/`operator`, same as `acknowledge_alert`) — for
   everything else: a VMS that doesn't have an adapter yet, or one
   that never will (a private vendor who just emails CSVs on request,
   say). A dept_admin/operator can register it through the "VMS
   Systems" panel on the `/federation` dashboard, or the API directly,
   without writing any code. It's created with `status='disconnected'`
   and `camera_count=0` — honest about what's actually talking to
   Sentinel versus what's merely on file, and it'll stay that way
   permanently for a read-only/manual integration, which is correct,
   not stale.

Either way, the result is the same kind of `vms_systems` row, and both
show up identically in `GET /api/v3/systems` and the dashboard.

## What's simulated vs. real, today

All three current adapters —
`adapters/police_vms_adapter.py`, `adapters/rto_vms_adapter.py`,
`adapters/municipal_vms_adapter.py` — are **simulated**: they generate
plausible-looking detection events on a randomised interval rather
than connecting to a real VMS. There is no real vendor SDK/RTSP/ONVIF
integration in this codebase yet. This is an intentional, separate
scope decision (see `model3-completion-plan.md`), not something this
plan changed — a real integration is a new `VMSAdapter` subclass
(or, for a read-only/manual VMS, the manual-onboarding path above)
implementing the real connection.

## Directory layout

```
model3_federation/
├── adapters/          VMSAdapter base class + the three simulated adapters
├── api/router.py      /api/v3/* REST endpoints + the /ws/federation websocket
├── bus/event_bus.py   Redis pub/sub with an in-process fallback queue
├── correlation/engine.py   Cross-system correlation + watchlist alerting
├── schemas/models.py  Pydantic models: adapter/event data + REST request bodies
├── registration.py    Adapter self-registration into shared cameras/vms_systems
└── tests/             pytest suite (see below)
```

## Testing

`model3_federation/tests/` needs the same real Postgres `sentinel`/
`sentinel_test` setup as `model1-registry/tests/` — see that
project's README for how to bootstrap it. From this directory:

```
pip install -r requirements-dev.txt
pytest
```

`tests/conftest.py` re-exports `model1-registry/tests/conftest.py`'s
fixtures (same running app, same database — model3's router is mounted
into Model 1's own app, as above), the same way
`model2_analytics/tests/conftest.py` does. One thing specific to this
component: the app's `lifespan()` normally starts the three adapters
and the correlation engine at startup, which registers cameras through
a raw database session rather than the request-scoped one tests
override for isolation — `DISABLE_FEDERATION_STARTUP` (set by
`conftest.py`, same mechanism as Model 1's own
`DISABLE_CATALOGUE_POLL`) skips that during tests. Nothing is
untested as a result: `test_registration.py` and
`test_correlation_engine.py` exercise `register_adapter()` and the
correlation engine directly against the test session instead.
