# Model 2 — Unified Viewing & Analytics (ANPR + Watchlist)

Full spec: `Project_Context.md` §4. Model 2 handles vehicle re-identification, license plate recognition (ANPR), cross-camera tracking, watchlist correlation, and real-time alert generation.

## Schema & Seed Data Ready

The database tables and sample seed data for Model 2 are already live in `shared/db/`:
- `vehicles_watchlist`: Active plate watchlists with severity & department tagging.
- `vehicle_tracks`: Cross-camera vehicle identities with vector embeddings.
- `detections`: Individual sightings with camera location, timestamp, and plate OCR confidence.
- `alerts`: Automatic alerts generated on watchlist match.

## Endpoints

See `docs/API_Contract.md` §2 for full specifications (`/api/v1/detections`, `/api/v1/vehicle-tracks/{plate}`, `/api/v1/watchlist`, `/api/v1/alerts`, `/api/v1/ws/alerts`).

## Status

🚧 **Database Foundation Ready** — Schema, ORM models, and seed data are in place in `shared/db/`. Pipeline algorithms (YOLO plate detector, OCR engine, vector track matcher) and WebSocket endpoints are next up for development.
