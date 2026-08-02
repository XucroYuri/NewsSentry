-- Phase 3: separate immutable import bodies from D1 query projections.
-- Safe to replay: this migration is additive and does not rewrite existing rows.

CREATE TABLE IF NOT EXISTS artifact_manifests (
    artifact_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL UNIQUE,
    job_id TEXT NOT NULL,
    object_key TEXT NOT NULL UNIQUE,
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    payload_bytes INTEGER NOT NULL CHECK (payload_bytes >= 0),
    content_type TEXT NOT NULL,
    r2_etag TEXT NOT NULL,
    r2_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'stored'
        CHECK (status IN ('stored', 'committed', 'failed')),
    created_at TEXT NOT NULL,
    finalized_at TEXT,
    error_code TEXT,
    error_message TEXT,
    details_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_artifact_manifests_status_created
    ON artifact_manifests(status, created_at);
CREATE INDEX IF NOT EXISTS idx_artifact_manifests_job
    ON artifact_manifests(job_id);

INSERT OR IGNORE INTO runtime_migration_receipts (
    migration_id, details_json
) VALUES (
    '20260802_phase3_durable_artifacts',
    '{"schema_version":"2026-08-02.import-artifact.v1","storage":"r2-standard","projection":"d1"}'
);
