# Model 3 — VMS Federation & Middleware

Model 3 answers the third question in this problem space, after "what
cameras exist" (Model 1) and "how does an operator watch and analyze
them live" (Model 2): *how do you get Police's Milestone deployment,
RTO's HikCentral checkpoints, AMC's Dahua city cameras, and whatever
ONVIF box or cloud webcam API shows up next, all talking to one
correlation and alerting layer — without touching a single line of
any department's own VMS?* Twenty-six departments means, realistically,
not twenty-six copies of the same vendor stack. A middleware/federation
layer is the only architecture that doesn't ask a department to rip
out infrastructure it already paid for and already trusts.

That's the brief's actual mandate for this model — an adapter/plugin
architecture across vendors, a metadata exchange bus for camera and
event data, cross-system event correlation, and a unified dashboard,
all without replacing anything departments already run — and it's
also, not coincidentally, the shape of this package: a
`VMSAdapter` interface with five interchangeable implementations, a
Redis-backed pub/sub event bus, a correlation engine that watches
every event for cross-VMS pattern matches, and one dashboard that
doesn't care which vendor a detection came from.

This document covers Model 3 on its own terms. Two adjacent concerns
get their own documents because they're shared platform surface, not
Model-3-specific:

- **[docs/PLATFORM.md](../PLATFORM.md)** — the shared FastAPI app shell
  Model 3's router mounts into, and the boot/shutdown sequence that
  starts and stops federation services alongside everything else.
- **[docs/SECURITY.md](../SECURITY.md)** — auth, RBAC, and the
  platform's cybersecurity posture, including the one open item
  Model 3 introduces (§10 below).

`model3_federation/README.md` (in the package itself) covers the same
ground at engineer-handoff granularity; this document is the polished
pass — read that one when you're editing the code, this one when
you're evaluating the system.

---

## 1. Architecture at a glance

```
Departmental VMS Estate                    Cloud / Public Sources
 (Milestone · HikCentral ·                  (Windy.com public
  Dahua DSS — vendor SDKs,                   webcams, any REST+API-key
  simulated for this demo)                   service, ONVIF NVR/camera)
        │                                            │
        ▼                                            ▼
┌───────────────────┐                    ┌───────────────────────┐
│  Hardcoded VMS     │                    │  Config-driven VMS     │
│  Adapters          │                    │  Adapters (registry.py)│
│  Police · RTO ·    │                    │  ONVIF (SOAP/WSDL) ·   │
│  Municipal         │                    │  REST+API-key · Windy  │
└─────────┬──────────┘                    └───────────┬───────────┘
          │  FederatedEvent (canonical schema)         │
          └───────────────────────┬─────────────────────┘
                                   ▼
                     FederationEventBus (bus/event_bus.py)
                Redis Pub/Sub — sentinel:federation:events
                (graceful in-process asyncio.Queue fallback)
                                   │
                                   ▼
                      CorrelationEngine (correlation/engine.py)
        dedup → resolve camera/track → detections → watchlist
              check → cross-system correlation → WS broadcast
                                   │
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
     shared/db/schema.sql   /ws/federation        REST API (/api/v3)
    cameras · detections     WebSocket push      systems · cameras ·
  · vehicle_tracks · alerts  (event/alert/         events · correlations
   (Model 1/2's own tables)   correlation)          · alerts
                                   │
                                   ▼
                      /federation dashboard (federation.html)
              topology cards · live feed · correlations · map ·
                        VMS Systems onboarding panel
```

The load-bearing decision in this diagram is that **the two adapter
families feed the same bus and the same correlation engine** — there
is no "simulated path" and a separate "real path" downstream of the
adapter boundary. A `FederatedEvent` from the Police adapter's
`asyncio.sleep` loop and one from a real ONVIF device flow through
identically. That's what makes "onboard a new vendor" a bounded,
well-defined unit of work instead of a growing pile of special cases.

---

## 2. How this relates to Model 1 and Model 2

Model 3 does not have its own database schema. It used to — a private
`federated_systems` / `federated_cameras` / `federated_events` /
`federated_alerts` / `correlation_results` set of tables — but that
meant a camera reported by a federated VMS and a camera in Model 1's
own registry were two different rows in two different tables for the
same real-world object. A department isn't guaranteed to run exactly
one VMS, and a VMS isn't guaranteed to be government-owned, but a
camera is still just a camera either way, so that schema was dropped
in favor of `shared/db/schema.sql`'s tables — the same ones Model 1's
registry and Model 2's analytics pipeline already write to:

- Every camera Model 3 learns about — from an adapter or from manual
  onboarding — is a normal row in Model 1's own `cameras` table,
  tagged with a `vms_system_id`. `NULL` means "from the main grid or
  manually onboarded [into Model 1]," not "federated"; a non-null
  value traces the camera back to whichever VMS reported it. See
  [docs/model1/README.md §2](../model1/README.md#2-data-model) for
  the rest of that table's shape.
- Detections, vehicle tracking, and watchlist alerting reuse Model
  1/2's own `detections`, `vehicle_tracks`, `vehicles_watchlist`, and
  `alerts` tables. There is no `correlation_results` table — a
  correlation is always derivable from `detections` + `vehicle_tracks`
  + `vms_systems`, computed on demand rather than cached somewhere it
  could silently drift from the raw sightings.
- Model 3's router mounts straight into Model 1's own FastAPI app
  (`model1-registry/app/main.py` does a plain, static
  `app.include_router(federation_router)`, the same pattern Model 2's
  routers use — see [docs/PLATFORM.md §1](../PLATFORM.md#1-why-this-code-lives-in-model1-registry))
  at `/api/v3`. There is no separate Model 3 process. The federation
  dashboard and its VMS Systems management panel are pages served by
  `model1-registry/app/templates/`, same as every other page in the
  product.

The practical payoff: `GET /api/v3/correlations/track?plate=...` (§8)
returns a plate's full multi-system route across *every* camera that
ever saw it — main grid, Model 2's own ANPR pipeline, and every
federated VMS — because they all write to the same `detections` table.
Cross-system correlation and Model 2's own cross-camera correlation
aren't two mechanisms; they're the same query.

---

## 3. Data model in plain terms

- **`vms_systems`** — one row per distinct VMS integration: its name,
  vendor, protocol, `ownership` (`government` or `private` — a mall or
  society's own camera system Sentinel has read access to counts too),
  which `department_id` it belongs to, a `status`
  (`connected` / `disconnected` / `unknown`), and, for config-driven
  integrations, `adapter_type` + `config` (§4).
- **`cameras.vms_system_id`** — a foreign key from Model 1's own
  camera table back to `vms_systems`. This is the entire link between
  "a camera" and "which federated VMS it came from." `ON DELETE SET
  NULL`, which is why `DELETE /api/v3/systems/{id}` refuses with `409`
  while cameras still reference it (§8) — otherwise a delete would
  quietly turn federated cameras into what looks like main-grid ones.
- **`cameras.source_grid_id`** — that VMS's own id for the camera
  (an adapter's `external_id`). Unique only *within* a `vms_system_id`
  (`idx_cameras_source_per_system`, a composite `UNIQUE` index), since
  two unrelated VMSs can both label a camera `cam-01` without
  colliding.
- **Department resolution** — an adapter's cameras report a
  plain-English department hint (e.g. `"Police"`), matched against
  `departments.name` / `category` with `ILIKE`
  (`registration.py`'s `_resolve_department_id`). Zero matches leaves
  `department_id` `NULL`; more than one match picks the first by
  `id` deterministically rather than whichever row Postgres's planner
  happens to return first. Either outcome is logged with the adapter
  name and the exact hint string, and a hint that fails to resolve
  surfaces on `GET /api/v3/systems` as `unmatched_department_hint`
  rather than sitting as a silent, unexplained `NULL`. Manually
  onboarded systems skip this path entirely — an admin picks the
  department directly, no ILIKE guessing involved.

---

## 4. Onboarding a VMS: two paths, deliberately kept separate

**Path 1 — adapter self-registration.** For a VMS with an actual
`VMSAdapter` subclass written for it. `registration.py`'s
`register_adapter()`, called from `start_federation_services()` at
app startup, connects the adapter, asks it for its camera inventory,
and upserts a `vms_systems` row plus one `cameras` row per camera —
idempotently, by primary key and by the `(vms_system_id,
source_grid_id)` composite unique index, so a restart re-registers the
same rows instead of duplicating them. This is how Police, RTO, and
Municipal (§5) come online; writing a new adapter this way requires
Python code and a deploy.

**Path 2 — config-driven onboarding**
(`POST /api/v3/systems`, gated to `dept_admin`/`operator`). For
everything else, and it itself branches on whether the caller supplies
an `adapter_type`:

| Caller supplies | Result |
|---|---|
| No `adapter_type` | Record-only. Row created `status='disconnected'`, `camera_count=0`, stays that way permanently. Honest about what's actually talking to Sentinel versus what's merely on file — for a VMS that has no adapter and never will (a vendor who emails CSVs on request), that's correct, not stale. |
| `adapter_type` + `config` | **Live.** `registry.py`'s `build_adapter()` constructs a real adapter of that type, `connect()`s against the actual endpoint, and — if that succeeds — pulls its real camera list into the same request's DB transaction and starts its event-stream task immediately. No redeploy. |

What makes the live path possible without a redeploy per vendor is
`adapters/registry.py`: every adapter type self-registers a stable
`adapter_type` string, a list of `ConfigField`s (what the onboarding
form should ask for), and a factory, via one class decorator
(`@register_adapter_type(...)`) at import time. `GET
/api/v3/adapter-types` exposes that registry directly, so the
"VMS Systems" panel's onboarding form (screenshot-equivalent: pick a
type from a dropdown, fill in exactly that type's fields, hit **Test
Connection**) never hardcodes a single vendor's field names — it's
reading the same registry the backend validates against. Onboarding a
new *protocol* still needs one new `VMSAdapter` subclass, written
once — that's a property of protocols being genuinely different
things (a Milestone SDK call, an ONVIF SOAP call, and a REST+API-key
call don't share code any more than a USB driver and a Bluetooth
driver would), not a gap in the framework. Onboarding a new *vendor
that already speaks a supported protocol* (any ONVIF-compliant camera,
or any REST+API-key service) needs zero code.

`POST /api/v3/systems/test-connection` runs the exact same
connect-and-enumerate path against a throwaway, unpersisted adapter
instance — it's what makes a wrong API key or an unreachable host fail
loudly on the onboarding screen instead of silently producing another
`disconnected` row for someone to puzzle over later. And because a
process restart shouldn't quietly drop everything an operator
onboarded through the UI, `registration.py`'s `load_dynamic_adapters()`
re-reads every `vms_systems` row with a non-`NULL` `adapter_type` at
startup, reconnects each one, and restarts its event stream —
a row whose credentials now fail (revoked key, moved camera, changed
password) is logged and left `disconnected` rather than crashing
startup for everyone else; fixing it is the same edit-and-re-test flow
as onboarding it the first time.

---

## 5. The adapters

### 5.1 Simulated adapters — Police, RTO, Municipal

Three `VMSAdapter` implementations, one per department, each modeling
a distinct real vendor's actual event-payload shape and translating it
into the canonical `FederatedEvent` schema. This is the interoperability
problem in miniature — three vendors describing the identical concept
(a license-plate detection) with completely incompatible field names:

| | Milestone (Police) | HikCentral (RTO) | Dahua DSS (Municipal) |
|---|---|---|---|
| Plate field | `licensePlate` | `plateText` | `plate` |
| Confidence field | `score` | `detectionConfidence` | `conf` (abbreviated) |
| Timestamp field | `utcTime` (ISO-8601) | `captureTime` (ISO-8601) | `time` (**UNIX integer**, not ISO) |
| Camera-id field | `deviceId` | `cameraIndex` | `channel` |
| Vehicle-class field | `vehicleClass` | `vehicleCategory` | `class` |
| Push model | XML/SDK event push | REST event subscription | WebSocket push |
| Event cadence | 3–10 s | 5–15 s (toll-plaza rate) | 2–8 s (busiest inner-city traffic) |

Each adapter carries a small, realistic fleet (4–5 cameras with real
Gujarat coordinates — Shahibaug, NH-48 Toll Plaza, Lal Darwaja, and so
on), emits events on a randomized interval matching its vendor's
real-world traffic pattern, and periodically emits the same
watchlisted plate (`GJ01CD5678`, also seeded in
`shared/db/seed.sql`) so a correlation and a watchlist alert are both
reliably demonstrable rather than left to chance. All three are
explicitly, intentionally simulated — there is no real vendor
SDK/RTSP/ONVIF integration behind them in this codebase, and the
adapter interface (`connect()` / `get_cameras()` /
`start_event_stream()`) is exactly what a real Milestone-SDK or
HikCentral-REST adapter would implement in their place. Swapping one
in is a new `VMSAdapter` subclass against this same interface, not an
architecture change.

### 5.2 ONVIF — the real interoperability standard

`adapters/onvif_vms_adapter.py` speaks actual ONVIF: SOAP over the
ONVIF Media and Device WSDL services, via `onvif-zeep-async`, which
bundles the WSDL files so there's no separate download/config step.
This is deliberately the second config-driven adapter type (alongside
REST+API-key, §5.3) rather than a third hardcoded vendor class,
because ONVIF is the protocol most Hikvision, Dahua, Axis, Bosch, and
NVR/VMS boxes already speak regardless of whether they also expose a
proprietary SDK — the actual industry answer to "heterogeneous
vendors," not a Sentinel-specific abstraction over it. One onboarded
system can represent an NVR with several channels: each ONVIF media
profile the device reports becomes its own `FederatedCamera`, so an
8-channel NVR onboards as 8 cameras from one `host`/`username`/
`password` config.

**Field-verified against real hardware**, not just written against
the documented WSDL shape: this adapter has been connected to an
actual ONVIF-capable device — a phone running an IP-camera app that
exposes an ONVIF Media/Device service — and confirmed end to end:
`connect()` → `GetDeviceInformation()` → `GetProfiles()` →
`GetStreamUri()` all resolve against a live endpoint, the exact call
sequence this file makes. That test caught a real bug worth knowing
about, because it's the kind of thing that only shows up against a
live device and not a mock: `onvif-zeep-async`'s `create_media_service()`
and `create_devicemgmt_service()` are themselves `async` factories,
not synchronous calls that happen to return an awaitable-friendly
object. Skipping the `await` on either one left the corresponding
service handle bound to the coroutine object itself, so the first real
operation on it failed with `'coroutine' object has no attribute
'GetProfiles'` — against live hardware, deterministically, while an
earlier, more permissive mock in the unit-test suite stayed green
because it modeled those factories as synchronous. Both the adapter
and the test fixture were fixed together once that surfaced
(`tests/test_onvif_adapter.py`'s own docstring documents the same
fix); the unit tests now assert the async-factory shape explicitly, so
that class of bug can't quietly regress even without hardware on hand
for every run.

ONVIF's genuine Events service (pull-point subscriptions, for real
push-style motion/analytics events) is a meaningfully larger slice of
the spec than this pass covers — subscription lifecycle, renewal,
per-vendor topic sets. Until that's built, this adapter's event stream
emits an honest periodic `camera_heartbeat` per camera on a 5-minute
poll (`_POLL_INTERVAL_SECONDS`), rather than fabricating detection
events the way the three simulated adapters do — it tells the
correlation engine and dashboard "this camera is still here and
enumerable," which is the truth, without pretending to be an
analytics source it isn't.

### 5.3 REST + API-key — the generic connector, proven by Windy

`adapters/rest_api_vms_adapter.py` is one class that onboards *any*
VMS or webcam service exposing a REST endpoint returning a JSON array
(or an array nested under a key) of camera-like objects, authenticated
by a single API key sent as a header. Field mapping is entirely
config-driven — dotted paths (`location.latitude`, `webcams.location.city`)
resolved at runtime by `_dig()`, not hardcoded per-vendor parsing
logic. `Windy.com`'s public webcams API is registered as a *preset*
(`adapter_type="windy"`) of this exact same class, with its dotted
field paths pre-filled so the onboarding form only asks for lat/lng/
radius/key instead of raw path names — proof that "generic" and
"Windy" are the same code path, not two parallel implementations that
could drift apart.

**Field-verified end to end with a real Windy API key**, through the
actual onboarding flow — `POST /api/v3/systems/test-connection` →
`connect()` → `get_cameras()` against `api.windy.com` itself, not a
mock. `tests/test_rest_api_adapter.py`'s own `httpx.MockTransport`
suite covers the adapter's field-mapping and error-handling logic in
isolation (no network, no key required to run it); the live key run is
what confirmed the real endpoint's response actually matches the
shape those tests assume.

Same honest scoping as the ONVIF adapter: a REST API needing OAuth,
multi-page pagination, or a response shape that isn't "array of
flat-ish objects" needs either new config fields here or, past a
point, its own adapter — this covers the common case (Windy, and most
cloud/hosted VMS and webcam-directory REST APIs), not literally every
API that exists.

---

## 6. Event bus — `bus/event_bus.py`

`FederationEventBus` publishes every `FederatedEvent` as JSON to a
single Redis Pub/Sub channel (`sentinel:federation:events`) and lets
the correlation engine subscribe to it — the "metadata exchange bus"
the brief calls for, decoupling every adapter from knowing who (or how
many consumers) is listening. Two details worth knowing:

- **Connection reuse.** The publisher keeps one open Redis connection
  rather than opening/pinging/closing a fresh one per event — this
  gets called once per camera detection, which during a burst can be
  several times a second.
- **Graceful degradation.** If Redis is unreachable, `publish()` falls
  back to an in-process `asyncio.Queue` (bounded at 2000, oldest
  event dropped first under sustained pressure) and logs a warning on
  every fallback publish, so adapters and the correlation engine keep
  working in a bare local-dev environment with no `docker-compose`
  Redis running, without silently losing events or crashing.

---

## 7. Correlation engine — `correlation/engine.py`

The intelligence layer: one asyncio background task, subscribed to the
bus, running this pipeline for every `FederatedEvent`:

1. **Deduplicate** — same normalized plate + same
   `camera_external_id` within 60 seconds is skipped. The dedup cache
   is pruned back to entries newer than five dedup windows once it
   passes 10,000 keys, so it stays bounded without needing a separate
   cleanup task.
2. **Resolve the camera** — look up the `cameras` row for
   `(vms_system_id, source_grid_id)`. An event for a camera never
   registered is logged and dropped rather than violating
   `detections.camera_id`'s foreign key with a made-up id.
3. **Resolve-or-create the vehicle track** — a deterministic `uuid5`
   of the normalized plate, the *same derivation*
   `model2_analytics/pipeline/tracking/associator_interface.py`'s
   `TrackAssociatorStub` uses. That's the mechanism, not a
   coincidence: it's what makes a plate resolve to the same
   `vehicle_tracks` row whether Model 2's own analytics pipeline or a
   Model 3 federated adapter sees it first.
4. **Watchlist check**, before the `detections` write, so
   `is_watchlisted` is known at insert time rather than patched in
   after.
5. **Persist to `detections`** — full audit trail, `raw_payload`
   preserved as `jsonb`, `camera_id` + `vehicle_track_id` set.
6. **Alert on a watchlist hit** — writes `alerts`, broadcasts a
   `WSMessage(type="alert")`.
7. **Cross-system correlation** — queries `detections` for the same
   `vehicle_track_id` seen through a *different* `vms_system_id`
   within the last 30 minutes. If found, broadcasts a
   `WSMessage(type="correlation")` with the full camera sequence
   (name, system, timestamp, lat/lng) the plate traveled through. Not
   stored anywhere — always recomputed from the raw sightings, so it
   can never drift from them.
8. **Broadcast the event itself** to every connected WebSocket client.

All DB work runs in a thread executor (synchronous SQLAlchemy in a
thread pool) so the event loop never blocks waiting on Postgres, and a
per-event exception is caught, logged, and rolled back without taking
down the engine's own subscription loop — one bad event doesn't stall
the whole federation pipeline.

---

## 8. REST + WebSocket API — `/api/v3`

All read endpoints require `Depends(get_current_user)`; writes are
gated to `dept_admin`/`operator` via `require_role(...)`, the same
dependency-layer pattern the rest of the platform uses
(see [docs/SECURITY.md §3](../SECURITY.md#3-role-based-access-control)).

| Endpoint | Method | Auth | Notes |
|---|---|---|---|
| `/api/v3/systems` | GET | any user | Every VMS system (main grid + federated), with live `events_per_min` from an in-memory rate counter and `unmatched_department_hint` when department resolution failed |
| `/api/v3/adapter-types` | GET | any user | Drives the onboarding form's type dropdown from `registry.py` directly — no hardcoded frontend field list |
| `/api/v3/systems/test-connection` | POST | `dept_admin`/`operator` | Builds a throwaway adapter, actually connects, persists nothing |
| `/api/v3/systems` | POST | `dept_admin`/`operator` | Record-only or live, branching on `adapter_type` — see §4 |
| `/api/v3/systems/{id}` | PATCH | `dept_admin`/`operator` | Partial update — `exclude_unset` semantics, so an omitted field is untouched and an explicit `null` clears it |
| `/api/v3/systems/{id}` | DELETE | `dept_admin`/`operator` | `409` while cameras still reference it |
| `/api/v3/cameras` | GET | any user | Federated cameras, optional `system_id` filter |
| `/api/v3/events` | GET | any user | Recent federated detections, filterable by `system_id` and `plate` |
| `/api/v3/events/stats` | GET | any user | Events/minute per system, live |
| `/api/v3/correlations` | GET | any user | Vehicle tracks with detections spanning more than one VMS, computed on the fly |
| `/api/v3/correlations/track` | GET | any user | Full multi-system route for one plate — main grid + Model 2 + every federated VMS together |
| `/api/v3/alerts` | GET | any user | Federation-originated watchlist alerts |
| `/api/v3/alerts/{id}/acknowledge` | POST | `dept_admin`/`operator` | Same acknowledgment pattern as Model 2's own alerts |
| `/api/v3/systems/{id}/simulate` | POST | any user | Fires a 10-event burst from one adapter — a deliberate demo control, not a production concern |
| `/ws/federation` | WebSocket | cookie/header auth, checked manually | Pushes `event`/`alert`/`correlation`/`heartbeat` messages to every connected dashboard |

The WebSocket route is the one place auth couldn't go through
`Depends(get_current_user)` on the route signature itself:
`get_current_user` takes a `request: Request` parameter, and FastAPI's
dependency solver won't substitute a `WebSocket` for a
`Request`-typed dependency — it raises a bare `TypeError` from inside
the ASGI app on every connection, auth notwithstanding, rather than a
clean `401`. `Request` and `WebSocket` both derive from Starlette's
`HTTPConnection`, and the only things `get_current_user` actually
touches (`.cookies`, `.headers`) exist on both, so the route calls it
directly instead — same check, same outcome, just invoked explicitly
rather than through the solver for this one connection type.

---

## 9. The dashboard — `/federation`

One page (`federation.html`, rendered by
`model1-registry/app/routers/pages.py`'s `federation_page` route),
four live regions, all driven by the same WebSocket connection plus
periodic REST polling:

- **Topology bar** — one card per VMS system (color-coded by
  department), live camera count, events-today, and events/minute,
  each with a **Simulate burst** control for demoing correlation and
  alerting on demand.
- **Live Event Feed** — every `FederatedEvent` as it arrives, color-
  coded by source system.
- **Cross-System Correlations** — every `CorrelationResult` the engine
  emits, watchlist hits visually distinguished from ordinary
  multi-system sightings.
- **GIS map** — federated cameras plotted alongside Model 1's own
  registry, one shared map layer rather than a separate federation-only
  view.
- **VMS Systems panel** — the onboarding UI for §4's two paths: pick
  an adapter type (populated from `GET /api/v3/adapter-types`), fill
  in exactly that type's fields, **Test Connection**, save. A row with
  a live `adapter_type` behind it is marked as such and isn't
  reconfigurable from this panel — deleting and re-onboarding is the
  path for changing a live connector's config, not an in-place edit.

---

## 10. Security note

Config-driven onboarding (§4) means `vms_systems.config` can hold real
credentials — a Windy API key, an ONVIF device's username/password.
Today that column is plain `JSONB`: readable in the clear by anything
with database access, same as this codebase's existing RTSP-credential
handling elsewhere (`shared/adapters/factory.py`), not a one-off gap
specific to federation. It's flagged at the schema level
(`migrations/002_vms_systems_adapter_config.sql`'s header) and now in
[docs/SECURITY.md §6](../SECURITY.md#6-whats-documented-but-not-built)
alongside this platform's other named-not-implemented items — real
next step is application-layer encryption (Fernet, key from an env var
or secrets manager) or moving the secret itself into a proper secrets
manager and storing only a reference here, before this holds a real
department's credentials rather than a demo API key.

Everything else about federation-specific access follows the
platform's standard session: no separate credential or service-account
model for adapters, `Depends(get_current_user)` /
`Depends(require_role(...))` at the dependency layer for every REST
route, and the WebSocket auth path described in §8.

---

## 11. Testing

`model3_federation/tests/` — 90 tests across nine files — needs the
same real Postgres + PostGIS `sentinel_test` database as
`model1-registry/tests/`, for the same reason Model 1's own test suite
does: this layer leans on real foreign keys, composite unique
indexes, and PostGIS geography columns with no SQLite equivalent.

```bash
cd model3_federation
pip install -r requirements-dev.txt
pytest
```

| File | Covers |
|---|---|
| `test_adapter_registry.py` | Registration, config validation, factory construction for every adapter type |
| `test_auth.py` | Every REST + WebSocket endpoint's auth/role gating |
| `test_composite_uniqueness.py` | The `(vms_system_id, source_grid_id)` unique index — collision behavior with and without `ON CONFLICT` |
| `test_correlation_engine.py` | Cross-system correlation, watchlist alerting, unregistered-camera skip |
| `test_dynamic_onboarding_api.py` | The full config-driven onboarding flow — test-connection, create, listing markers, failure handling |
| `test_onvif_adapter.py` | ONVIF field-mapping and error handling against a fixture matching the real package's async-factory call shape |
| `test_registration.py` | Adapter self-registration, upsert idempotency, sticky department resolution |
| `test_rest_api_adapter.py` | Generic REST adapter's dotted-path mapping, plus the Windy preset proving it's the same class |
| `test_systems_api.py` | Manual (record-only) VMS onboarding CRUD and its RBAC rules |

`tests/conftest.py` re-exports `model1-registry/tests/conftest.py`'s
fixtures by loading that file directly (rather than duplicating a
~300-line fixture file) — same running app, same database, since
Model 3's router is mounted into Model 1's own app, not a separate
one. One thing specific to this component:
`start_federation_services()` normally registers cameras through a raw
database session at app startup, outside the request-scoped session
tests override for transaction isolation. `DISABLE_FEDERATION_STARTUP`
(set unconditionally by `conftest.py`, same mechanism as Model 1's own
`DISABLE_CATALOGUE_POLL`) skips that during tests — nothing goes
untested as a result, since `test_registration.py` and
`test_correlation_engine.py` exercise `register_adapter()` and the
correlation engine directly against the test session instead.
