# Model 1 — Registry & GIS Foundation

Full spec: `Project_Context.md` §3 & `Model1ImplementationPlan.md`.

## What this owns

The camera registry and the GIS map dashboard. This handles camera onboarding, metadata tracking, status management, spatial visualization across Gujarat, department/district categorization, and audit logging.

## Features Implemented

- **Interactive GIS Map (`/`)**: Leaflet + OpenStreetMap, marker clustering via `Leaflet.markercluster`, connectivity status markers (🟢 online, 🔴 offline, 🟡 maintenance), district dropdown filtering, department layer toggles, and rich popup cards with VMS stream viewer links.
- **Camera Registry & Table View (`/cameras`)**: HTMX-driven sortable/filterable table, soft delete (`is_active = false`), and bulk CSV import (`/api/v1/cameras/bulk`).
- **Camera CRUD Modal Forms**: Alpine.js v3 + HTMX modal for creating and updating camera metadata, writing automated audit logs to `status_history`.
- **Department View (`/departments`)**: Read-only view with active camera counts per department.
- **District View (`/districts`)**: Coverage view for all 33 Gujarat districts.
- **Model 2 Stubs**: Inert navigation links for `/detections`, `/watchlist`, `/alerts`.

## Stack

FastAPI + Jinja2 templates + HTMX + Alpine.js (no Node build step). PostgreSQL + PostGIS via `shared/db/`.

## Directory layout

```
model1-registry/
└── app/
    ├── routers/     FastAPI routers — cameras, departments, districts, pages
    ├── templates/   Jinja2 HTML templates (map.html, cameras_list.html, camera_form.html, etc.)
    └── static/      Leaflet map logic (map.js) & CSS design system (main.css)
```

## Status

✅ **Completed — Phase 1 & Foundation Built**. Full CRUD, GIS map dashboard, dark theme glassmorphism UI, seed data, and docker setup are operational.
