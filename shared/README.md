# shared/

Code both `model1-registry` and `model2-analytics` depend on. This
exists because they're one FastAPI codebase, not two services (see root
`README.md` and `Project_Context.md` §2) — Model 2 reads and writes
against tables Model 1 owns (`cameras`, `departments`), so the schema
can't live in two places.

**Rule of thumb:** if a change touches the DB schema, a type both models
pass across the API boundary, or the VMS adapter interface, it goes
here — and gets reflected in `docs/API_Contract.md` in the same PR.
Model-specific logic (routers, templates, pipeline code) stays in that
model's own directory.

## `db/`

SQLAlchemy models + Alembic migrations. Single source of truth for the
schema in `Project_Context.md` §3 (`cameras`, `departments`,
`districts`, `status_history`) and §4 (`vehicles_watchlist`,
`detections`, `alerts`, `vehicle_tracks`). Not yet populated — add
models here as tables get built, don't duplicate a model's definition
inside `model1-registry/` or `model2-analytics/`.

## `schemas/`

Pydantic request/response models — the enforceable version of what
`docs/API_Contract.md` describes in prose. If you add or change a field
here, update the contract doc's example JSON to match.

## `adapters/`

The VMS adapter interface from `Project_Context.md` §4 — one adapter
class per vendor, all implementing `connect()`, `get_stream()`,
`get_metadata()`. This is what keeps the "modular adapter-based
framework, avoid vendor lock-in" mandate real rather than aspirational.
ONVIF-based cameras should use a shared ONVIF adapter rather than each
getting a bespoke one.

## Not yet built

Nothing is implemented yet — this is the frame. First real content here
will likely be the `cameras`/`departments`/`districts` SQLAlchemy models
as Model 1 starts on camera CRUD.
