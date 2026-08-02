-- Phase 2 DLQ replay and durable DLQ consumption audit receipts.
-- Replay never mutates the original terminal job; it creates a new pending job
-- with replay_of_job_id and records the operator action here.

CREATE TABLE IF NOT EXISTS dlq_replay_receipts (
    receipt_id TEXT PRIMARY KEY,
    original_job_id TEXT NOT NULL REFERENCES jobs(job_id),
    new_job_id TEXT NOT NULL UNIQUE REFERENCES jobs(job_id),
    operator_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    requested_version TEXT NOT NULL,
    worker_version TEXT,
    deploy_commit TEXT,
    created_at TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_dlq_replay_receipts_original
    ON dlq_replay_receipts(original_job_id, created_at DESC);

CREATE TABLE IF NOT EXISTS dlq_consumption_receipts (
    receipt_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(job_id),
    queue_name TEXT NOT NULL,
    message_body_json TEXT NOT NULL,
    worker_version TEXT,
    consumed_at TEXT NOT NULL,
    UNIQUE(job_id, queue_name)
);

CREATE INDEX IF NOT EXISTS idx_dlq_consumption_receipts_consumed
    ON dlq_consumption_receipts(consumed_at DESC);

INSERT OR IGNORE INTO runtime_migration_receipts (
    migration_id,
    details_json
) VALUES (
    '20260802_phase2_dlq_replay_receipts',
    '{"mode":"shadow","operator_replay":true,"dlq_consumer_ack_requires_receipt":true}'
);
