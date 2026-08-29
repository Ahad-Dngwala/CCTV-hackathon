# Model 1 — Registry & GIS Foundation

Full spec: `Project_Context.md` §3. This README is the quick-reference
frame for whoever's building this — keep it in sync as you go.

## What this owns

The camera registry and the map. Not video, not analytics — this is
"where are the cameras, whose are they, are they online, and what does
coverage look like across Gujarat." Model 2 builds analytics on top of
what this produces; this model doesn't depend on Model 2 for anything.

## Scope

- **Map**: Leaflet + OSM, clustered markers (Leaflet.markercluster),
  **custom-designed status/department icons** — not default pins, this
  is one of the actual differentiators per `Project_Context.md` §0.
- **Filters**: department layer toggle, **district filter** (33
  districts — Gujarat's real admin unit, not just "city").
  `Project_Context.md` names Valsad, Dahod, Somnath, Jamnagar, Dwarka as
  deployment points specifically.
- **Camera detail panel**: metadata + optional hyperlink out to the
  camera's native VMS viewer (`vms_url`) — honest that this model is
  registry-only, no centralized video.
- **CRUD + onboarding**: manual entry, CSV bulk import (no wizard —
  explicitly stubbed, see `Project_Context.md` §8), API-based onboarding.
- **Gap analysis**: PostGIS spatial queries (buffers, polygon
  containment) for uncovered zones and ageing infrastructure — this is
  the real spatial-ops payoff of using PostGIS, not just storing points.
- **RBAC + audit trail**: role enforcement at the API layer
  (`dept_admin` / `operator` / `viewer`), `status_history` table logs
  every metadata change. See `Project_Context.md` §6.

## Stack

FastAPI + Jinja2 templates + HTMX/Alpine.js, no build step. Served
straight from FastAPI — no separate frontend service. PostgreSQL +
PostGIS via `shared/db/`.

## Directory layout

```
model1-registry/
└── app/
    ├── routers/     FastAPI routers — cameras, departments, districts,
    │                gap-analysis, export
    ├── templates/   Jinja2 templates (map page, camera detail panel)
    └── static/      Leaflet setup, custom marker icons, HTMX/Alpine glue
```

## Endpoints

See `docs/API_Contract.md` §1 — that's the authoritative list. Update
it in the same PR if you add or change an endpoint here.

## Data model

`cameras`, `departments`, `districts`, `status_history` — defined in
`shared/db/`, sketch in `Project_Context.md` §3. Don't redefine these
locally.

## Explicitly not building

Per `Project_Context.md` §8: no bulk-import wizard UX, no dedicated
audit UI (plain table view is enough), no analog camera support (IP/
ONVIF only, documented as future roadmap in the HLD).

## Status

Not yet started — this is the frame. First real work: `cameras` /
`departments` / `districts` models in `shared/db/`, then the
`GET /api/v1/cameras` + map page.
