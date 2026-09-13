# Model 3 — working notes (not the doc pass yet)

Internal scratch file, same purpose as `docs/model2/NOTES.md` — a
head start for whenever Model 3 gets its own real documentation, not
something to publish as-is. Model 3 is moving faster than Model 2 was
at the equivalent stage, so treat anything endpoint-shaped below as
provisional — confirm against current code before writing it into a
polished doc or quoting a shape externally.

## What lives inside `model1-registry/` but is actually Model 3

- **`app/main.py` imports `model3_federation.api.router` directly** —
  `router as federation_router`, plus `start_federation_services` /
  `stop_federation_services`, called from `lifespan()`. Unlike Model 2,
  this is a normal static import, not the runtime auto-loader — see
  [docs/PLATFORM.md §1](../PLATFORM.md#1-why-this-code-lives-in-model1-registry)
  for why the two models use different mounting strategies and what
  that trade-off actually is.
- **`start_federation_services(db_session_factory=..., redis_url=...)`**
  — registers each federation adapter's cameras into the shared DB and
  starts its event stream as an independent background task per
  adapter. Doesn't block app startup.
- **`app/routers/pages.py`'s `/federation` route** — renders
  `federation.html`, the unified federation dashboard. One page, one
  route, clearly commented in `pages.py` as `# ── Model 3 Federation
  Dashboard ──`.
- **`settings.REDIS_URL`** (`app/config.py`) — the federation event
  bus. Model 1 doesn't read this setting anywhere; it's centralized in
  Model 1's config object for the same one-process/one-config reason
  covered in [docs/PLATFORM.md §6](../PLATFORM.md#6-configuration-appconfigpy).
- **`vms_system_id` on `cameras`** — the actual coupling point between
  Model 1's registry and Model 3's federation layer. A `vms_systems`
  row (vendor, protocol, connection status, heartbeat) can own many
  `cameras` rows through this FK. Model 1's own API never populates or
  filters on it; it exists in the shared table because federation
  needs to attach a camera to a specific external VMS connection
  without Model 1 needing to know that connection exists.

## Not yet true, don't assume

- Model 1's registry API (`app/routers/cameras.py`) has no
  federation-aware filtering (e.g. "show me only cameras behind VMS
  X") — if that's wanted later, it's a new filter param on `GET
  /cameras` reading the existing `vms_system_id` column, not a schema
  change.
- No federation-specific auth path yet distinct from the platform's
  standard JWT session (docs/SECURITY.md) — if adapters end up needing
  their own credential/service-account model, that's new ground, not
  an extension of an existing pattern.

## Loose ends worth resolving in the real doc pass

- This layer is under active development; endpoint shapes, the event
  bus contract, and the adapter interface should all be re-verified
  against current code rather than assumed stable when the real doc
  pass happens.
- Decide, at that point, whether `docs/SECURITY.md` §7's "add a
  section here" instruction has actually been followed for whatever
  federation-specific auth/credential handling exists by then.
