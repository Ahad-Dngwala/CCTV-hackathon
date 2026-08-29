# Sentinel — Gujarat CCTV Integration Platform

Hackathon build for the Gujarat CCTV unification challenge. Model 1
(Registry & GIS Foundation) first, Model 2 (Unified Viewing & Analytics —
ANPR + watchlist correlation) on top of it.

**Read `Project_Context.md` before touching anything.** It's the real
working spec — architecture decisions, tech stack rationale, data model,
timeline, and the "don't re-litigate this" list. `HackathonPortal.md` is
the official brief it's derived from. This README is just the map to the
repo itself.

## Repo structure

```
├── Project_Context.md      Our working spec — read this first
├── HackathonPortal.md      Official hackathon brief
├── docs/
│   ├── API_Contract.md     REST + WebSocket contract between Model 1 and Model 2
│   └── DATASET.md          Dataset sourcing/synthesis notes (owner: TBD)
├── shared/                 Code both models depend on — DB models, Pydantic
│                           schemas, VMS adapter interface. Single source of
│                           truth for anything Model 2 reads that Model 1 writes.
├── model1-registry/        Camera registry + map (Leaflet, PostGIS gap analysis,
│                           department/district filters, audit trail)
├── model2-analytics/       ANPR pipeline + watchlist + alerts + cross-camera
│                           vehicle tracking
└── infra/                  docker-compose, reverse proxy config
```

## Why `shared/` exists

Model 1 and Model 2 are **one FastAPI codebase**, not two services talking
over a network (see `Project_Context.md` §2 — this was a deliberate stack
choice specifically so Model 2 doesn't need a separate service just to
read Model 1's camera data). `shared/` is where that shared ground lives:

- `shared/db/` — SQLAlchemy models + Alembic migrations. If you're adding
  a column to `cameras` or a new table like `detections`, it goes here,
  not duplicated inside a model dir.
- `shared/schemas/` — Pydantic request/response models. These are what
  `docs/API_Contract.md` describes in prose; the schemas are the
  enforceable version.
- `shared/adapters/` — the VMS adapter interface
  (`connect()` / `get_stream()` / `get_metadata()`) every vendor
  integration implements. One adapter class per vendor.

If your change only touches `model1-registry/` or `model2-analytics/`,
stay there. If it touches the DB schema or a type both models pass
around, it belongs in `shared/` — and update `docs/API_Contract.md` in
the same PR so the contract doesn't go stale.

## Getting started

1. Read `Project_Context.md` in full.
2. Read the README in whichever of `model1-registry/` or
   `model2-analytics/` you're picking up — each has its own scope,
   endpoint list, and open TODOs.
3. Check `docs/API_Contract.md` before adding or changing an endpoint —
   if it's not documented there, document it as you build it.
4. `infra/docker-compose.yml` is the local dev environment (Postgres +
   PostGIS, and eventually MediaMTX). See `infra/README.md`.

## Status

Early scaffold — see `Project_Context.md` §8 for the actual week-by-week
plan and §9 for what's still undecided. This structure will keep
changing as Week 1 progresses; if you rename or move something, update
this README and the affected model's README in the same commit.
