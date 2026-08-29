# infra/

Local dev + VPS deployment config. Per `Project_Context.md` §2: Docker
Compose locally and on the VPS for parity, Nginx/Caddy reverse proxy +
TLS in front.

## `docker-compose.yml`

Skeleton — services get filled in as they become real, not written
ahead of need:

- `db`: PostgreSQL + PostGIS — needed from day one for `shared/db/`,
  and self-seeding (see below).
- `app`: the FastAPI app (Model 1 + Model 2 routers).
- `mediamtx`: RTSP→WebRTC/HLS bridge — add once Model 2 starts on live
  ingestion, not before.
- `proxy`: Nginx/Caddy — add once there's more than one thing to route
  to.

### Getting a working database — the whole point of this section

```bash
cd infra
docker compose up -d db
```

That's it. On first run, Postgres's own bootstrap mechanism mounts and
runs `shared/db/schema.sql` → `shared/db/triggers.sql` →
`shared/db/seed.sql`, in that order (see the numbered volume mounts in
`docker-compose.yml` — `docker-entrypoint-initdb.d` scripts run in
sorted-name order, once, only when the data volume is empty), so a
fresh `up` gives you the full schema, the audit triggers, 5
departments, all 33 districts, and the 30 seed cameras — no manual
`psql -f` step needed. This is the exact same sequence that was run
and verified by hand against a real Postgres 16 + PostGIS 3.4 instance
while building those files.

Check it worked:

```bash
docker compose exec db psql -U sentinel -d sentinel -c "SELECT count(*) FROM cameras;"
# -> 30
```

**If you change `schema.sql`/`triggers.sql`/`seed.sql` and want them to
re-run**, the init scripts only fire on an empty volume — you need to
actually drop the data:

```bash
docker compose down -v   # -v removes the sentinel_pgdata volume — destructive, dev-only
docker compose up -d db
```

`down` without `-v` just stops the container and keeps your data —
that's the normal day-to-day command once you're past first setup.

Explicitly not building for the demo: API gateway/rate limiting
(mentioned in `Project_Context.md` §7 as the statewide-scale answer,
not needed at 50-camera demo scale), network segmentation (documented
in the HLD only, not implemented — one VPS for the demo).