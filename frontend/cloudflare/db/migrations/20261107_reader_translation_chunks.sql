CREATE TABLE IF NOT EXISTS reader_translation_chunks (
    job_id TEXT NOT NULL REFERENCES reader_translation_jobs(id),
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0 AND chunk_index < 32),
    plan_version TEXT NOT NULL,
    markdown TEXT NOT NULL CHECK (length(markdown) BETWEEN 1 AND 24000),
    generation INTEGER NOT NULL DEFAULT 0 CHECK (generation >= 0),
    execution_count INTEGER NOT NULL DEFAULT 0 CHECK (execution_count BETWEEN 0 AND 2),
    result_json TEXT CHECK (result_json IS NULL OR length(result_json) <= 650000),
    finished_at INTEGER,
    PRIMARY KEY (job_id, chunk_index)
);

INSERT OR IGNORE INTO runtime_migration_receipts (migration_id, details_json)
VALUES ('20261107_reader_translation_chunks_r6', '{"scope":"reader-preview","plan":"markdown-blocks-v1"}');
