-- ============================================================
-- Sentinel — Model 1 (Registry & GIS) + shared foundation schema
-- ============================================================
-- Scope note: Model 2 (detections, tracks, watchlists, alerts,
-- ground-truth annotations) is intentionally NOT defined here.
-- See docs/DATASET.md and Project_Context.md §4 — that schema is
-- owned by whoever builds the analytics pipeline, once they've
-- decided how they want to store embeddings/tracks/matches. This
-- file only covers what Model 1 needs to stand alone: departments,
-- districts, users, cameras, and the camera audit trail.
--
-- Tested against a real Postgres 16 + PostGIS 3.4 instance
-- (matching infra/docker-compose.yml, db name `sentinel`) —
-- every statement below actually ran clean, not just eyeballed.
-- ============================================================

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()

-- ============================================================
-- Shared foundation
-- ============================================================

CREATE TABLE departments (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL UNIQUE,
    category    TEXT,            -- e.g. Home/Police, Food & Civil Supplies, RTO, Municipal Corporation
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE districts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL UNIQUE,          -- Gujarat's 33 districts
    boundary    GEOGRAPHY(MULTIPOLYGON, 4326), -- null until a real shapefile is sourced
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_districts_boundary ON districts USING GIST (boundary);

CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username        TEXT NOT NULL UNIQUE,
    email           TEXT UNIQUE,
    hashed_password TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('dept_admin', 'operator', 'viewer')),
    department_id   UUID REFERENCES departments(id) ON DELETE SET NULL,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_users_department ON users (department_id);

-- ============================================================
-- Model 1 — Registry & GIS
-- ============================================================
--
-- `cameras` carries two kinds of columns, kept visually grouped
-- below because they come from different places and get filled
-- in at different times:
--
--   1. Registry/onboarding fields (Project_Context.md §3) — set by
--      us: department, district, ownership, retention, RBAC-relevant
--      metadata. These are what the hackathon's Model 1 brief is
--      actually about.
--   2. Grid catalogue fields (GET /api/ingest on the camera grid
--      itself, docs/API_Contract.md §0 + model2-analytics/README.md)
--      — mirrored from the source so we don't hard-code stream URLs
--      or assume a uniform codec/resolution across ~80,000 cameras.
--      Notably: the grid gives a human-written location LABEL
--      ("06 Timbavadi gate-Junagadh"), not coordinates. `location`
--      stays nullable and gets backfilled once someone geocodes the
--      label (or a department confirms it during onboarding) —
--      seed.sql only ever sets it where that's already unambiguous.

CREATE TABLE cameras (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                  TEXT NOT NULL,

    -- registry / onboarding fields
    department_id         UUID REFERENCES departments(id) ON DELETE RESTRICT,
    district_id           UUID REFERENCES districts(id) ON DELETE SET NULL,
    location              GEOGRAPHY(POINT, 4326),          -- nullable, see note above
    camera_type           TEXT,                            -- fixed/PTZ/dome/bullet — no fixed taxonomy given yet
    ownership             TEXT,                            -- government | private (societies/malls, per the brief)
    storage_type          TEXT,                            -- cloud | local, per the brief's wording
    retention_days        INT,
    vms_url               TEXT,                            -- optional hyperlink out to native VMS viewer
    connectivity_status   TEXT NOT NULL DEFAULT 'offline'
                           CHECK (connectivity_status IN ('online', 'offline', 'maintenance')),
    is_active             BOOLEAN NOT NULL DEFAULT true,    -- soft delete — see open question on DELETE endpoint
    decommissioned_at     TIMESTAMPTZ,

    -- grid catalogue fields, mirrored from GET /api/ingest
    source_grid_id        TEXT UNIQUE,                     -- "id" from /api/ingest — resync key, not our PK
    location_label        TEXT,                            -- raw "location" string from /api/ingest, e.g. "06 Timbavadi gate-Junagadh"
    is_live               BOOLEAN,                          -- grid's reported "live" flag
    codec                 TEXT,                            -- h264 | hevc | '' (grid reports blank when unknown) — mixed per model2-analytics/README
    stream_width          INT,
    stream_height         INT,
    stream_fps            REAL,
    bitrate_kbps          INT,
    rtsp_url              TEXT,
    whep_url              TEXT,                            -- grid calls this "webrtc_url"; it's WHEP specifically
    hls_url               TEXT,
    grid_synced_at         TIMESTAMPTZ,                     -- last time this row was refreshed from /api/ingest

    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_cameras_location ON cameras USING GIST (location);
CREATE INDEX idx_cameras_department ON cameras (department_id);
CREATE INDEX idx_cameras_district ON cameras (district_id);
CREATE INDEX idx_cameras_status ON cameras (connectivity_status);
CREATE INDEX idx_cameras_active ON cameras (is_active);

CREATE TABLE status_history (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    camera_id     UUID NOT NULL REFERENCES cameras(id) ON DELETE RESTRICT,
    changed_field TEXT NOT NULL,
    old_value     TEXT,
    new_value     TEXT,
    changed_by    UUID REFERENCES users(id) ON DELETE SET NULL,
    changed_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_status_history_camera ON status_history (camera_id, changed_at DESC);