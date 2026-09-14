-- ============================================================
-- Migration 003 — ANPR / OCR extended columns on detections
-- ============================================================
-- Safe: all new columns are nullable with no DEFAULT expressions,
-- so no existing rows are affected and no table rewrite is needed
-- (Postgres adds nullable columns without locking on modern versions).
--
-- Run order: after 002_vms_systems_adapter_config.sql
-- ============================================================

ALTER TABLE detections
    ADD COLUMN IF NOT EXISTS ocr_confidence      REAL,
    ADD COLUMN IF NOT EXISTS plate_confidence    REAL,
    ADD COLUMN IF NOT EXISTS plate_crop_path     TEXT,
    ADD COLUMN IF NOT EXISTS anpr_provider       TEXT,
    ADD COLUMN IF NOT EXISTS source_type         TEXT,
    ADD COLUMN IF NOT EXISTS video_timestamp_ms  REAL;

-- Partial index for fast plate lookups scoped to provider
CREATE INDEX IF NOT EXISTS idx_detections_provider
    ON detections (anpr_provider)
    WHERE anpr_provider IS NOT NULL;

-- Fast lookup for temporal aggregation queries (recorded video jobs)
CREATE INDEX IF NOT EXISTS idx_detections_plate_time
    ON detections (detected_plate, "timestamp" DESC)
    WHERE detected_plate IS NOT NULL;
