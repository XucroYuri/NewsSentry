ALTER TABLE events ADD COLUMN breaking_score REAL;
ALTER TABLE events ADD COLUMN breaking_label TEXT;
ALTER TABLE events ADD COLUMN breaking_reason TEXT;
ALTER TABLE events ADD COLUMN breaking_confidence INTEGER;
ALTER TABLE events ADD COLUMN breaking_dimensions TEXT DEFAULT '{}';
ALTER TABLE events ADD COLUMN breaking_score_version TEXT;
ALTER TABLE events ADD COLUMN target_timezone TEXT DEFAULT 'UTC';
ALTER TABLE events ADD COLUMN published_at_local TEXT;
ALTER TABLE targets ADD COLUMN timezone TEXT DEFAULT 'UTC';

CREATE INDEX IF NOT EXISTS idx_events_public_breaking
ON events(pipeline_stage, breaking_score DESC, published_at DESC);

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

CREATE INDEX IF NOT EXISTS idx_event_localizations_locale
ON event_localizations(locale, event_id);

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
