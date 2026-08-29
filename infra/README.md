# infra/

Local dev + VPS deployment config. Per `Project_Context.md` §2: Docker
Compose locally and on the VPS for parity, Nginx/Caddy reverse proxy +
TLS in front.

## `docker-compose.yml`

Skeleton — services get filled in as they become real, not written
ahead of need:

- `db`: PostgreSQL + PostGIS — needed from day one for `shared/db/`.
- `app`: the FastAPI app (Model 1 + Model 2 routers).
- `mediamtx`: RTSP→WebRTC/HLS bridge — add once Model 2 starts on live
  ingestion, not before.
- `proxy`: Nginx/Caddy — add once there's more than one thing to route
  to.

Explicitly not building for the demo: API gateway/rate limiting
(mentioned in `Project_Context.md` §7 as the statewide-scale answer,
not needed at 50-camera demo scale), network segmentation (documented
in the HLD only, not implemented — one VPS for the demo).
