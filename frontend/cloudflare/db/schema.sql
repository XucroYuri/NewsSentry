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
    archived INTEGER DEFAULT 0
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

-- 用户/Token 表（简化为 Workers 静态配置，暂不需要）
-- 认证将在后续阶段通过 Cloudflare Access 实现
