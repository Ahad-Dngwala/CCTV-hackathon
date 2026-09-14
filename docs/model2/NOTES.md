# Model 2 — working notes (not the doc pass yet)

Internal scratch file, not a polished doc. Purpose: when Model 2 gets
its own real documentation pass, everything below is already scoped
out so it doesn't need rediscovering by re-reading `model1-registry/`
from scratch. Treat this as a table of contents with breadcrumbs, not
prose to publish as-is.

## What lives inside `model1-registry/` but is actually Model 2

- **`app/routers/streams.py`** — the whole live-view relay. Decodes
  RTSP (H.264 + HEVC) server-side via OpenCV/FFmpeg and re-serves it as
  MJPEG (`multipart/x-mixed-replace`) to sidestep browser HEVC decode
  gaps and WebRTC firewall issues. Two routers in this one file:
  - `router` (`/api/v1/cameras/...`) — `/grid/{grid_id}/frame` (single
    latest JPEG, used by grid matrix cards), `/grid/{grid_id}/live`
    (MJPEG stream by grid id), `/{camera_id}/live` (MJPEG stream by DB
    UUID).
  - `streams_router` (`/api/v1/streams/...`) — `/catalogue`, returns
    every live camera's HLS/RTSP/MJPEG/WHEP URLs, sourced from DB when
    grid-synced cameras exist, falling back to a synthesized cam01–30
    catalogue otherwise.
  - `CameraStreamReader` — one background thread per actively-viewed
    camera, auto-stops after ~10s of no viewers. Worth knowing before
    a doc pass: reconnect logic tolerates up to ~9s of failed reads
    before forcing a reconnect, because remote grid cameras have GOP
    keyframe intervals up to 10-12s — a naive fast-reconnect policy
    would thrash against that.
- **`app/routers/pages.py`** — Model 2 owns these page routes, mixed
  into the same file as Model 1's:
  `/live` (`live.html`), `/detections` + `/detection`
  (`detection.html`, live AI vehicle detection — resolves cam04/cam22
  UUIDs for the JS), `/recorded-detection` (`recorded_detection.html`),
  `/watchlist` (`watchlist.html`), `/watchlist/persons`
  (`persons_watchlist.html`), `/face-detection` (`face_detection.html`),
  `/alerts` (`alerts.html`), `/anpr` (`anpr.html`).
- **`app/main.py`'s router mounting** — used to be runtime auto-discovery,
  now a normal static import (same shape as Model 3's). One residual
  shim from the old approach is still there: a `sys.modules` alias so
  `anpr.py`'s WS alert broadcaster still finds the same `detections`
  module instance it looked up under the old auto-loader's naming
  scheme. See [docs/PLATFORM.md §3](../PLATFORM.md#3-model-2s-router-mounting).
- **`app.state.frame_queue`** — created in `model1-registry/app/main.py`'s
  `lifespan()`, written to by Model 2's ingestion pipeline. Model 1
  never touches it; it's initialized in Model 1's file purely because
  that's where the app object lives.
- **Grid-sync columns on `cameras`** — `source_grid_id`, `codec`,
  `stream_width/height/fps`, `bitrate_kbps`, `rtsp_url`, `whep_url`,
  `hls_url`, `grid_synced_at`. Populated by
  `model2_analytics/app/ingestion/catalogue.py`'s `CataloguePoller` +
  `upsert_cameras_to_db`, read (never written) by Model 1's own API.

## Already documented elsewhere — don't duplicate

- `docs/API_Contract.md` §2 already has the full Model 2 endpoint table
  (watchlist CRUD, recorded/face-detection job workers, WebSocket
  channels) — this file only covers what's physically inside Model 1's
  package, not Model 2's own directory.
- `model2_analytics/README.md` and `docs/DATASET.md` §2 cover the
  ingestion/dataset side already.

## Loose ends worth resolving in the real doc pass

- Reconcile `docs/API_Contract.md`'s `GET /api/v1/detections/stats` and
  `GET /api/v1/vehicle-tracks/{plate}` status markers against what's
  actually implemented in `model2_analytics/app/routers/` at doc-pass
  time — these move fast enough that the marker in the contract file
  may already be behind.
