-- News Sentry D1 Schema — 镜像 AsyncStore 表结构
-- 同步规则: 修改 Python AsyncStore 的 CREATE TABLE 时，必须同步更新此文件

-- 事件表（核心数据对象）
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL,
    target_label TEXT DEFAULT '',
    region_id TEXT DEFAULT '',
    source_id TEXT NOT NULL,
    source_name TEXT DEFAULT '',
    source_type TEXT DEFAULT 'unknown',
    credibility_label TEXT,
    published_at TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    title TEXT NOT NULL,
    original_title TEXT,
    summary TEXT,
    recommendation_reason TEXT,
    full_content TEXT,
    original_url TEXT,
    detail_url TEXT DEFAULT '',
    image_urls TEXT DEFAULT '[]',
    tags TEXT DEFAULT '[]',
    issue_tags TEXT DEFAULT '[]',
    related_tags TEXT DEFAULT '[]',
    region_tags TEXT DEFAULT '[]',
    entities TEXT DEFAULT '[]',
    language TEXT DEFAULT 'mixed',
    pipeline_stage TEXT DEFAULT 'collected',
    processing_history TEXT DEFAULT '[]',
    value_label TEXT DEFAULT '普通',
    value_score REAL,
    china_relevance_label TEXT DEFAULT '未知',
    related_count INTEGER DEFAULT 0,
    discussion_count INTEGER,
    classification TEXT DEFAULT '{}',
    extra TEXT DEFAULT '{}',
    breaking_score REAL,
    breaking_label TEXT,
    breaking_reason TEXT,
    breaking_confidence INTEGER,
    breaking_dimensions TEXT DEFAULT '{}',
    breaking_score_version TEXT,
    target_timezone TEXT DEFAULT 'UTC',
    published_at_local TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_events_target_id ON events(target_id);
CREATE INDEX IF NOT EXISTS idx_events_region_id ON events(region_id);
CREATE INDEX IF NOT EXISTS idx_events_published_at ON events(published_at);
CREATE INDEX IF NOT EXISTS idx_events_pipeline_stage ON events(pipeline_stage);
CREATE INDEX IF NOT EXISTS idx_events_source_id ON events(source_id);
CREATE INDEX IF NOT EXISTS idx_events_value_label ON events(value_label);
CREATE INDEX IF NOT EXISTS idx_events_public_featured ON events(pipeline_stage, value_score DESC, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_public_breaking ON events(pipeline_stage, breaking_score DESC, published_at DESC);

CREATE TABLE IF NOT EXISTS event_localizations (
    event_id TEXT NOT NULL,
    locale TEXT NOT NULL,
    localized_title TEXT NOT NULL,
    localized_summary TEXT,
    localized_recommendation_reason TEXT,
    localized_tags TEXT DEFAULT '[]',
    localized_issue_tags TEXT DEFAULT '[]',
    localized_related_tags TEXT DEFAULT '[]',
    localized_region_tags TEXT DEFAULT '[]',
    localized_language TEXT NOT NULL,
    quality_score INTEGER DEFAULT 0,
    model TEXT DEFAULT '',
    route_id TEXT DEFAULT '',
    updated_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (event_id, locale)
);

CREATE INDEX IF NOT EXISTS idx_event_localizations_locale ON event_localizations(locale, event_id);

CREATE TABLE IF NOT EXISTS breaking_score_stats (
    scope_key TEXT PRIMARY KEY,
    window_days INTEGER NOT NULL,
    mean_score REAL DEFAULT 0,
    stddev_score REAL DEFAULT 0,
    p50 REAL DEFAULT 0,
    p75 REAL DEFAULT 0,
    p90 REAL DEFAULT 0,
    p95 REAL DEFAULT 0,
    sample_count INTEGER DEFAULT 0,
    updated_at TEXT DEFAULT (datetime('now'))
);

-- 来源表
CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT DEFAULT 'rss',
    url TEXT DEFAULT '',
    language TEXT DEFAULT 'mixed',
    enabled INTEGER DEFAULT 1,
    credibility_label TEXT,
    fetch_interval_seconds INTEGER DEFAULT 900,
    consecutive_failures INTEGER DEFAULT 0,
    total_runs INTEGER DEFAULT 0,
    total_failures INTEGER DEFAULT 0,
    last_run_at TEXT,
    extra TEXT DEFAULT '{}'
);

-- 目标表
CREATE TABLE IF NOT EXISTS targets (
    target_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    region_id TEXT DEFAULT 'global',
    primary_language TEXT DEFAULT 'en',
    region_type TEXT DEFAULT 'country',
    source_count INTEGER DEFAULT 0,
    event_count INTEGER DEFAULT 0,
    lifecycle TEXT DEFAULT '{}',
    archived INTEGER DEFAULT 0,
    cloudflare_collect_enabled INTEGER NOT NULL DEFAULT 1,
    timezone TEXT DEFAULT 'UTC'
);

-- 来源健康表
CREATE TABLE IF NOT EXISTS source_health (
    source_id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL,
    consecutive_failures INTEGER DEFAULT 0,
    total_runs INTEGER DEFAULT 0,
    total_failures INTEGER DEFAULT 0,
    last_run_at TEXT,
    last_failure_at TEXT,
    last_error TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Cloudflare-native ops state for scheduled collection/translation runs.
CREATE TABLE IF NOT EXISTS ops_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now')),
    lock_until TEXT
);

CREATE TABLE IF NOT EXISTS ops_runs (
    run_id TEXT PRIMARY KEY,
    task TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    details_json TEXT DEFAULT '{}'
);

-- Public read snapshots keep the hot public reader paths off aggregate queries.
CREATE TABLE IF NOT EXISTS public_read_snapshots (
    key TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    source_latest_public_at TEXT,
    item_count INTEGER DEFAULT 0,
    payload_bytes INTEGER DEFAULT 0,
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Invalid or implausibly future events are retained for audit without entering
-- the public event/read-model path.
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

-- 用户/Token 表（简化为 Workers 静态配置，暂不需要）
-- 认证将在后续阶段通过 Cloudflare Access 实现

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
    expected_chunks INTEGER NOT NULL DEFAULT 0 CHECK (expected_chunks >= 0),
    committed_chunks INTEGER NOT NULL DEFAULT 0 CHECK (committed_chunks >= 0),
    payload_bytes INTEGER NOT NULL DEFAULT 0 CHECK (payload_bytes >= 0),
    output_watermark TEXT,
    started_at TEXT NOT NULL,
    committed_at TEXT,
    error_code TEXT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS import_batch_chunks (
    batch_id TEXT NOT NULL REFERENCES import_batches(batch_id),
    chunk_no INTEGER NOT NULL CHECK (chunk_no >= 0),
    checksum TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'committed', 'failed')),
    statement_count INTEGER NOT NULL DEFAULT 0,
    payload_bytes INTEGER NOT NULL DEFAULT 0,
    committed_at TEXT,
    error_message TEXT,
    PRIMARY KEY (batch_id, chunk_no)
);

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
