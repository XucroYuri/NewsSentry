-- Phase 1 shadow control-plane state. These tables are additive and do not
-- replace the legacy ops_state/public_read_snapshots path until canary gates pass.
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    replay_of_job_id TEXT,
    job_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    capability TEXT NOT NULL,
    scheduled_for TEXT NOT NULL,
    scheduled_window TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN (
            'pending', 'enqueued', 'leased', 'running', 'importing',
            'committed', 'snapshot_pending', 'succeeded', 'retry_scheduled',
            'dead_lettered', 'cancelled'
        )),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
    lease_token TEXT,
    lease_owner TEXT,
    lease_until TEXT,
    fencing_version INTEGER NOT NULL DEFAULT 0,
    input_cursor TEXT,
    output_watermark TEXT,
    last_error_code TEXT,
    last_error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_status_scheduled
    ON jobs(status, scheduled_for);
CREATE INDEX IF NOT EXISTS idx_jobs_source_status
    ON jobs(target_id, source_id, status);
CREATE INDEX IF NOT EXISTS idx_jobs_lease_until
    ON jobs(lease_until)
    WHERE lease_until IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_jobs_replay
    ON jobs(replay_of_job_id)
    WHERE replay_of_job_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS job_attempts (
    attempt_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(job_id),
    attempt_no INTEGER NOT NULL,
    worker_version TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    outcome TEXT,
    retryable INTEGER NOT NULL DEFAULT 0 CHECK (retryable IN (0, 1)),
    latency_ms INTEGER,
    container_used INTEGER NOT NULL DEFAULT 0 CHECK (container_used IN (0, 1)),
    details_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(job_id, attempt_no)
);

CREATE INDEX IF NOT EXISTS idx_job_attempts_job_started
    ON job_attempts(job_id, started_at DESC);

CREATE TABLE IF NOT EXISTS job_outbox (
    outbox_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL UNIQUE REFERENCES jobs(job_id),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'dispatched', 'confirmed')),
    dispatch_attempts INTEGER NOT NULL DEFAULT 0,
    next_dispatch_at TEXT NOT NULL,
    dispatched_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_job_outbox_dispatch
    ON job_outbox(status, next_dispatch_at);

CREATE TABLE IF NOT EXISTS source_runtime_state (
    target_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    tier TEXT NOT NULL DEFAULT 'P2' CHECK (tier IN ('P0', 'P1', 'P2')),
    capability TEXT NOT NULL DEFAULT 'container',
    state TEXT NOT NULL DEFAULT 'active'
        CHECK (state IN ('active', 'degraded', 'cooling_down', 'suspended', 'dead')),
    next_due_at TEXT NOT NULL,
    last_attempt_at TEXT,
    last_success_at TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    rolling_success_rate REAL,
    backoff_until TEXT,
    cursor TEXT,
    etag TEXT,
    last_modified TEXT,
    quarantine_count INTEGER NOT NULL DEFAULT 0,
    config_version TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (target_id, source_id)
);

CREATE INDEX IF NOT EXISTS idx_source_runtime_due
    ON source_runtime_state(state, next_due_at);
CREATE INDEX IF NOT EXISTS idx_source_runtime_backoff
    ON source_runtime_state(backoff_until)
    WHERE backoff_until IS NOT NULL;

CREATE TABLE IF NOT EXISTS import_batches (
    batch_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL UNIQUE REFERENCES jobs(job_id),
    status TEXT NOT NULL DEFAULT 'received'
        CHECK (status IN ('received', 'validated', 'importing', 'committed', 'rejected', 'failed')),
    received_count INTEGER NOT NULL DEFAULT 0,
    valid_count INTEGER NOT NULL DEFAULT 0,
    quarantined_count INTEGER NOT NULL DEFAULT 0,
    imported_count INTEGER NOT NULL DEFAULT 0,
    updated_count INTEGER NOT NULL DEFAULT 0,
    checksum TEXT NOT NULL,
    started_at TEXT NOT NULL,
    committed_at TEXT,
    error_code TEXT
);

CREATE TABLE IF NOT EXISTS import_batch_chunks (
    batch_id TEXT NOT NULL REFERENCES import_batches(batch_id),
    chunk_no INTEGER NOT NULL CHECK (chunk_no >= 0),
    checksum TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'committed', 'failed')),
    statement_count INTEGER NOT NULL DEFAULT 0,
    payload_bytes INTEGER NOT NULL DEFAULT 0,
    committed_at TEXT,
    PRIMARY KEY (batch_id, chunk_no)
);

CREATE TABLE IF NOT EXISTS quarantine_context (
    quarantine_id TEXT PRIMARY KEY REFERENCES quarantined_events(quarantine_id),
    batch_id TEXT REFERENCES import_batches(batch_id),
    job_id TEXT REFERENCES jobs(job_id),
    event_fingerprint TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_quarantine_context_job
    ON quarantine_context(job_id)
    WHERE job_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS snapshot_generations (
    generation_id TEXT PRIMARY KEY,
    status TEXT NOT NULL
        CHECK (status IN ('building', 'ready', 'active', 'superseded', 'failed')),
    source_watermark TEXT,
    item_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    activated_at TEXT,
    failure_code TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_snapshot_generations_single_active
    ON snapshot_generations(status)
    WHERE status = 'active';

CREATE TABLE IF NOT EXISTS snapshot_generation_items (
    generation_id TEXT NOT NULL REFERENCES snapshot_generations(generation_id),
    key TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    item_count INTEGER NOT NULL DEFAULT 0,
    payload_bytes INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (generation_id, key)
);

CREATE TABLE IF NOT EXISTS runtime_migration_receipts (
    migration_id TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now')),
    deploy_commit TEXT,
    details_json TEXT NOT NULL DEFAULT '{}'
);

INSERT OR IGNORE INTO runtime_migration_receipts (
    migration_id,
    details_json
) VALUES (
    '20260801_phase1_job_runtime',
    '{"mode":"shadow","authoritative":false}'
);
