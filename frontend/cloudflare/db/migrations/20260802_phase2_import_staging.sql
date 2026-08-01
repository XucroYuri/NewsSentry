-- Phase 2 transactional chunked import staging.
-- The chunk limits enforced in workers/lib/import-staging.ts are project
-- safety margins for shadow/canary replay, not Cloudflare D1 hard limits.
-- Recovery note: do not blindly rerun this file after a partial ALTER failure.
-- Use docs/deployment/cloudflare-phase2-migration-runbook.md to inspect
-- d1_migrations plus PRAGMA table_info and apply only missing additive pieces.

ALTER TABLE import_batches
    ADD COLUMN expected_chunks INTEGER NOT NULL DEFAULT 0 CHECK (expected_chunks >= 0);

ALTER TABLE import_batches
    ADD COLUMN committed_chunks INTEGER NOT NULL DEFAULT 0 CHECK (committed_chunks >= 0);

ALTER TABLE import_batches
    ADD COLUMN payload_bytes INTEGER NOT NULL DEFAULT 0 CHECK (payload_bytes >= 0);

ALTER TABLE import_batches
    ADD COLUMN output_watermark TEXT;

ALTER TABLE import_batches
    ADD COLUMN error_message TEXT;

ALTER TABLE import_batch_chunks
    ADD COLUMN error_message TEXT;

CREATE TABLE IF NOT EXISTS import_staged_events (
    batch_id TEXT NOT NULL REFERENCES import_batches(batch_id),
    chunk_no INTEGER NOT NULL,
    event_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    event_fingerprint TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    staged_at TEXT NOT NULL,
    PRIMARY KEY (batch_id, event_id)
);

CREATE INDEX IF NOT EXISTS idx_import_staged_events_batch_chunk
    ON import_staged_events(batch_id, chunk_no);

CREATE TABLE IF NOT EXISTS import_batch_finalize_receipts (
    batch_id TEXT PRIMARY KEY REFERENCES import_batches(batch_id),
    job_id TEXT NOT NULL REFERENCES jobs(job_id),
    target_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    batch_checksum TEXT NOT NULL,
    lease_token TEXT NOT NULL,
    fencing_version INTEGER NOT NULL,
    output_watermark TEXT,
    finalized_at TEXT NOT NULL,
    batch_guard TEXT NOT NULL,
    job_guard TEXT NOT NULL,
    source_guard TEXT NOT NULL
);

INSERT OR IGNORE INTO runtime_migration_receipts (
    migration_id,
    details_json
) VALUES (
    '20260802_phase2_import_staging',
    '{"mode":"shadow-canary","authoritative":false,"public_import_replaced":false}'
);
