# Sentinel — Gujarat CCTV Integration & GIS Platform

Sentinel is a unified CCTV management, registry, GIS mapping, and video analytics platform built for Gujarat's statewide surveillance network.

---

## 🚀 Quick Start (Running with Docker Compose)

The entire platform (PostgreSQL + PostGIS database and the FastAPI application) can be brought up in a single command using Docker Compose.

### Prerequisites
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (with Docker Compose v2+)

### Launch Instructions

1. **Clone & navigate to `infra/`**:
   ```bash
   cd infra
   ```

2. **Start the containers**:
   ```bash
   docker compose up -d
   ```
   *This automatically builds the FastAPI app container (`infra/Dockerfile`) and PostgreSQL + PostGIS + pgvector database container (`infra/Dockerfile.db`).*

3. **Access the Web Dashboard**:
   Open your browser and navigate to:
   👉 **`http://localhost:8000`**

   - **Interactive Map Dashboard**: `http://localhost:8000/`
   - **Camera Registry & CRUD**: `http://localhost:8000/cameras`
   - **Department Management**: `http://localhost:8000/departments`
   - **District Overview**: `http://localhost:8000/districts`
   - **Swagger OpenAPI Docs**: `http://localhost:8000/docs`

4. **Resetting Database & Seed Data** (if needed):
   ```bash
   docker compose down -v
   docker compose up -d
   ```

---

## 🛠️ Technology Stack

- **Backend Framework**: FastAPI (Python 3.12)
- **Database**: PostgreSQL 16 + PostGIS 3.4 + `pgvector` extension
- **ORM & Migrations**: SQLAlchemy 2.0 + GeoAlchemy2
- **Frontend Architecture**: Server-rendered Jinja2 templates + HTMX + Alpine.js (via CDN, no Node build step)
- **Mapping & GIS**: Leaflet.js + `Leaflet.markercluster` + OpenStreetMap tiles
- **Containerization**: Docker Compose (`infra/docker-compose.yml`)

---

## 📁 Repository Structure

```
├── Project_Context.md       Our working technical specification & architectural decisions
├── HackathonPortal.md       Official hackathon challenge brief
├── Model1ImplementationPlan.md Implementation plan for Model 1 (Registry & GIS)
├── docs/
│   ├── API_Contract.md      REST & WebSocket API specification
│   └── DATASET.md           Dataset notes & video stream catalogue
├── shared/                  Shared codebase across models
│   ├── db/                  SQLAlchemy models, schema.sql, triggers.sql, seed.sql
│   ├── schemas/             Pydantic request & response models
│   └── adapters/            VMS adapter interface definitions
├── model1-registry/         Model 1 — Registry & GIS Foundation
│   └── app/                 FastAPI application (routers, templates, static CSS/JS)
├── model2-analytics/        Model 2 — Analytics & Vehicle Tracking (ANPR, Watchlists, Alerts)
└── infra/                   Docker environment (`docker-compose.yml`, `Dockerfile`, `Dockerfile.db`)
```

---

## 🔌 API Endpoints Summary

### Model 1 — Registry & GIS
- `GET /api/v1/cameras` — List, filter by department, district, and status
- `POST /api/v1/cameras` — Create new camera (manual entry)
- `POST /api/v1/cameras/bulk` — CSV bulk camera import
- `GET /api/v1/cameras/{id}` — Get camera detail & VMS stream URL
- `PATCH /api/v1/cameras/{id}` — Update camera (automatically writes `status_history` audit log)
- `DELETE /api/v1/cameras/{id}` — Soft delete camera (`is_active = false`)
- `GET /api/v1/cameras/{id}/history` — Camera audit history
- `GET /api/v1/departments` — List departments with active camera counts
- `GET /api/v1/districts` — List all 33 Gujarat districts with camera counts

---

## 📄 License & Project Context

See [Project_Context.md](file:///c:/Hackathons/Sentinel-CCTV-Hackathon/Project_Context.md) for full architectural background, rationale, and design principles.
