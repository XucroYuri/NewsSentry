CREATE TABLE IF NOT EXISTS reader_translation_jobs (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    dedupe_key TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    target_lang TEXT NOT NULL,
    source_lang TEXT NOT NULL DEFAULT '',
    markdown TEXT NOT NULL CHECK (length(markdown) BETWEEN 1 AND 24000),
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'timed_out')),
    error_code TEXT,
    error_message TEXT,
    error_status INTEGER,
    attempt_count INTEGER NOT NULL CHECK (attempt_count > 0),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    started_at INTEGER,
    finished_at INTEGER,
    result_key TEXT,
    result_json TEXT CHECK (result_json IS NULL OR length(result_json) <= 650000),
    UNIQUE (dedupe_key, attempt_count)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_reader_translation_active
    ON reader_translation_jobs(dedupe_key) WHERE status IN ('queued', 'running');
CREATE INDEX IF NOT EXISTS idx_reader_translation_owner
    ON reader_translation_jobs(owner, id);
