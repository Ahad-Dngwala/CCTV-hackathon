-- migration: vms_systems config-driven onboarding
-- --------------------------------------------------
-- Adds the two columns that let a VMS system be *reconnectable at
-- runtime* instead of only ever a static, permanently-disconnected
-- record: which adapter type built it, and what config it needs to
-- reconnect (base_url/api_key for rest_api and windy, host/user/pass
-- for onvif — see model3_federation/adapters/registry.py).
--
-- Both are nullable: a row created the old way (POST /systems with no
-- adapter_type) still has NULL/NULL here and behaves exactly as
-- before — permanently 'disconnected', no adapter, purely a record.
-- Existing rows are untouched by this migration.
--
-- SECURITY NOTE — read before running this in anything but a hackathon
-- demo: `config` is stored as plain JSONB, so API keys and ONVIF
-- passwords currently sit in the database in plaintext. That matches
-- the rest of this codebase's current secret-handling (RTSP credentials
-- are handled similarly per shared/adapters/factory.py), but it's a
-- real gap, not a stylistic choice — before this goes anywhere near
-- production data, encrypt `config` at the application layer (e.g.
-- Fernet with a key from an env var / secrets manager, never a DB-
-- level "encrypted column" that the app server can still read
-- unencrypted anyway) or move secrets to a proper secrets manager and
-- store only a reference here.

ALTER TABLE vms_systems
    ADD COLUMN IF NOT EXISTS adapter_type TEXT,
    ADD COLUMN IF NOT EXISTS config       JSONB;

COMMENT ON COLUMN vms_systems.adapter_type IS
    'Registry key from model3_federation/adapters/registry.py (e.g. rest_api, windy, onvif). '
    'NULL means this row has no live adapter behind it (manual/record-only onboarding).';

COMMENT ON COLUMN vms_systems.config IS
    'Adapter-specific connection config (base_url/api_key, host/user/pass, ...). '
    'PLAINTEXT — see migration file header before storing real credentials.';
