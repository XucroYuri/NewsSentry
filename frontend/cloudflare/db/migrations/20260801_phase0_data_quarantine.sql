-- Phase 0: retain rejected timestamp/URL payloads outside the public event path.
CREATE TABLE IF NOT EXISTS quarantined_events (
    quarantine_id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    reviewed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_quarantined_events_reason_created
    ON quarantined_events(reason_code, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_quarantined_events_source_created
    ON quarantined_events(target_id, source_id, created_at DESC);
