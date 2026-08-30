# infra/ — Docker & Infrastructure Environment

This directory contains the Docker Compose configuration and container definitions for local development and VPS deployment.

---

## 📦 Container Setup

| Container | Image / Dockerfile | Purpose |
|---|---|---|
| `db` | `Dockerfile.db` (`postgis/postgis:16-3.4` + `pgvector`) | PostgreSQL + PostGIS spatial engine + vector embeddings |
| `app` | `Dockerfile` (`python:3.12-slim`) | Sentinel FastAPI Web App (Model 1 & Model 2) |

---

## 🚀 Commands

### Starting the Environment

From the `infra/` directory (or root):

```bash
cd infra
docker compose up -d
```

Compose automatically builds `infra/Dockerfile.db` for the database and `infra/Dockerfile` for the app.

### Database Initialization & Seed Data

On initial boot, PostgreSQL runs scripts mounted from `shared/db/`:
1. `20-schema.sql` — Creates extensions (`postgis`, `pgcrypto`, `vector`), tables, constraints, and indexes.
2. `30-triggers.sql` — Sets `updated_at` timestamps and logs audit entries in `status_history`.
3. `40-seed.sql` — Populates 5 departments, 33 Gujarat districts, 30 seed cameras with rich metadata, and sample vehicle watchlists/alerts.

### Resetting Data (Clean Re-seed)

Postgres init scripts fire only when the data volume is empty. To reset and re-seed from scratch:

```bash
docker compose down -v --rmi local
docker compose up -d
```

### Checking Database Status

```bash
docker compose exec db psql -U sentinel -d sentinel -c "SELECT count(*) FROM cameras;"
```

---

## 🔒 Configuration

Environment settings are configured via `DATABASE_URL` in `docker-compose.yml`:
`postgresql://sentinel:sentinel_dev@db:5432/sentinel`