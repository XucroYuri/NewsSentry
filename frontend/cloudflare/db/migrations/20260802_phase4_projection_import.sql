-- Phase 4: projection-only import finalize receipts.
-- Safe to replay: this migration is additive and enforces finalize mode exclusivity.

CREATE TABLE IF NOT EXISTS import_projection_finalize_receipts (
    batch_id TEXT PRIMARY KEY REFERENCES import_batches(batch_id),
    job_id TEXT NOT NULL UNIQUE REFERENCES jobs(job_id),
    batch_checksum TEXT NOT NULL,
    artifact_id TEXT NOT NULL UNIQUE REFERENCES artifact_manifests(artifact_id),
    finalized_at TEXT NOT NULL,
    batch_guard TEXT NOT NULL,
    job_guard TEXT NOT NULL,
    artifact_guard TEXT NOT NULL,
    origin TEXT NOT NULL CHECK (origin IN ('api-import', 'container-import')),
    request_idempotency_key_hash TEXT
        CHECK (request_idempotency_key_hash IS NULL OR length(request_idempotency_key_hash) = 64)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_projection_receipts_idempotency_key
    ON import_projection_finalize_receipts(request_idempotency_key_hash)
    WHERE request_idempotency_key_hash IS NOT NULL;

CREATE TRIGGER IF NOT EXISTS trg_projection_receipt_reject_source_receipt
BEFORE INSERT ON import_projection_finalize_receipts
WHEN EXISTS (
    SELECT 1 FROM import_batch_finalize_receipts WHERE batch_id = NEW.batch_id
)
BEGIN
    SELECT RAISE(ABORT, 'import_finalize_receipt_mode_conflict');
END;

CREATE TRIGGER IF NOT EXISTS trg_source_receipt_reject_projection_receipt
BEFORE INSERT ON import_batch_finalize_receipts
WHEN EXISTS (
    SELECT 1 FROM import_projection_finalize_receipts WHERE batch_id = NEW.batch_id
)
BEGIN
    SELECT RAISE(ABORT, 'import_finalize_receipt_mode_conflict');
END;

INSERT OR IGNORE INTO runtime_migration_receipts (migration_id, details_json)
VALUES (
    '20260802_phase4_projection_import',
    '{"finalize_modes":["source-fenced","projection-only"],"authoritative_projection":true}'
);
