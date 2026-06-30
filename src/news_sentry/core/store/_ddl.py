"""AsyncStore — SQLite 存储层，替代 Memory 的 YAML 全量序列化。"""

from __future__ import annotations

import logging

# aiosqlite worker 线程默认非 daemon，导致 create_app() 后进程无法退出。
# 在非测试环境中 patch aiosqlite.core.Thread 使 worker 为 daemon。
# 测试中不 patch，因为 pytest 的 per-test event loop 依赖 worker 线程正常关闭。
import os as _os

if not _os.environ.get("PYTEST_CURRENT_TEST"):
    import aiosqlite.core as _aiosqlite_core

    _OrigThread = _aiosqlite_core.Thread  # type: ignore[attr-defined]

    class _DaemonThread(_OrigThread):  # type: ignore[misc, valid-type]
        def __init__(self, *args: object, **kwargs: object) -> None:
            kwargs.setdefault("daemon", True)
            super().__init__(*args, **kwargs)

    _aiosqlite_core.Thread = _DaemonThread  # type: ignore[attr-defined]

logger = logging.getLogger(__name__)

_ANALYSIS_STAGES = ("judged", "drafts", "outputted")

_PRAGMA_SETUP = (
    "PRAGMA busy_timeout=15000",
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA cache_size=-64000",
    "PRAGMA foreign_keys=ON",
)

_DDL_KNOWN_IDS = """
CREATE TABLE IF NOT EXISTS known_ids (
    event_id  TEXT PRIMARY KEY,
    gid       TEXT,
    seen_at   TEXT NOT NULL
)
"""

_DDL_SOURCE_HEALTH = """
CREATE TABLE IF NOT EXISTS source_health (
    source_id   TEXT PRIMARY KEY,
    status      TEXT NOT NULL,
    last_check  TEXT NOT NULL,
    error_count INTEGER DEFAULT 0,
    metadata    TEXT
)
"""

_DDL_CURSORS = """
CREATE TABLE IF NOT EXISTS cursors (
    source_id  TEXT PRIMARY KEY,
    cursor     TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_DDL_LLM_CACHE = """
CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key  TEXT PRIMARY KEY,
    response   TEXT NOT NULL,
    model      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_DDL_EVENT_INDEX = """
CREATE TABLE IF NOT EXISTS event_index (
    event_id          TEXT PRIMARY KEY,
    target_id         TEXT NOT NULL,
    stage             TEXT NOT NULL,
    source_id         TEXT,
    news_value_score  INTEGER,
    china_relevance   INTEGER,
    classification_l0 TEXT,
    title_original    TEXT,
    url               TEXT,
    published_at      TEXT,
    file_path         TEXT,
    metadata_json     TEXT,
    public_translation_ready INTEGER NOT NULL DEFAULT 0,
    sentiment         TEXT,
    entity_names      TEXT,
    topic_tags        TEXT,
    created_at        TEXT NOT NULL,
    gid               TEXT
)
"""

_DDL_EVENT_INDEX_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS event_index_fts USING fts5(
    title_original,
    source_id,
    entity_names,
    topic_tags,
    metadata_json,
    content='event_index',
    content_rowid='rowid',
    tokenize='unicode61'
)
"""

# FTS5 triggers — keep virtual index in sync with event_index table
_DDL_FTS_TRIGGERS = (
    """CREATE TRIGGER IF NOT EXISTS event_index_ai AFTER INSERT ON event_index BEGIN
        INSERT INTO event_index_fts(
            rowid, title_original, source_id, entity_names, topic_tags, metadata_json
        ) VALUES (
            new.rowid, new.title_original, new.source_id,
            new.entity_names, new.topic_tags, new.metadata_json
        );
    END""",
    """CREATE TRIGGER IF NOT EXISTS event_index_ad AFTER DELETE ON event_index BEGIN
        INSERT INTO event_index_fts(event_index_fts, rowid, title_original, source_id,
            entity_names, topic_tags, metadata_json)
        VALUES ('delete', old.rowid, old.title_original, old.source_id,
            old.entity_names, old.topic_tags, old.metadata_json);
    END""",
    """CREATE TRIGGER IF NOT EXISTS event_index_au AFTER UPDATE ON event_index BEGIN
        INSERT INTO event_index_fts(event_index_fts, rowid, title_original, source_id,
            entity_names, topic_tags, metadata_json)
        VALUES ('delete', old.rowid, old.title_original, old.source_id,
            old.entity_names, old.topic_tags, old.metadata_json);
        INSERT INTO event_index_fts(
            rowid, title_original, source_id, entity_names, topic_tags, metadata_json
        ) VALUES (
            new.rowid, new.title_original, new.source_id,
            new.entity_names, new.topic_tags, new.metadata_json
        );
    END""",
)

_DDL_ENTITIES = """
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    mention_count INTEGER DEFAULT 1,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    target_ids TEXT DEFAULT '',
    aliases TEXT NOT NULL DEFAULT '',
    confidence INTEGER NOT NULL DEFAULT 0,
    needs_review INTEGER NOT NULL DEFAULT 0,
    first_seen_source_id TEXT,
    last_seen_source_id TEXT,
    is_manual INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(canonical_name, entity_type)
)
"""

_DDL_ENTITY_EVENT_MENTIONS = """
CREATE TABLE IF NOT EXISTS entity_event_mentions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id INTEGER NOT NULL,
    event_id TEXT NOT NULL,
    source_id TEXT,
    confidence INTEGER NOT NULL DEFAULT 0,
    is_manual INTEGER NOT NULL DEFAULT 0,
    mention_context TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (entity_id) REFERENCES entities(id),
    FOREIGN KEY (event_id) REFERENCES event_index(event_id),
    UNIQUE(entity_id, event_id)
)
"""

_DDL_ENTITY_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS entity_fts USING fts5(
    canonical_name,
    aliases,
    entity_type,
    content='entities',
    content_rowid='id'
)
"""

_DDL_ENTITY_FTS_TRIGGERS = (
    """CREATE TRIGGER IF NOT EXISTS entity_fts_ai AFTER INSERT ON entities BEGIN
        INSERT INTO entity_fts(rowid, canonical_name, aliases, entity_type)
        VALUES (new.id, new.canonical_name, new.aliases, new.entity_type);
    END""",
    """CREATE TRIGGER IF NOT EXISTS entity_fts_ad AFTER DELETE ON entities BEGIN
        INSERT INTO entity_fts(entity_fts, rowid, canonical_name, aliases, entity_type)
        VALUES ('delete', old.id, old.canonical_name, old.aliases, old.entity_type);
    END""",
    """CREATE TRIGGER IF NOT EXISTS entity_fts_au AFTER UPDATE ON entities BEGIN
        INSERT INTO entity_fts(entity_fts, rowid, canonical_name, aliases, entity_type)
        VALUES ('delete', old.id, old.canonical_name, old.aliases, old.entity_type);
        INSERT INTO entity_fts(rowid, canonical_name, aliases, entity_type)
        VALUES (new.id, new.canonical_name, new.aliases, new.entity_type);
    END""",
)

_DDL_ENTITY_EVENT_ANNOTATIONS = """
CREATE TABLE IF NOT EXISTS entity_event_annotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id INTEGER NOT NULL,
    event_id TEXT,
    field TEXT NOT NULL,
    old_value TEXT NOT NULL DEFAULT '',
    new_value TEXT NOT NULL DEFAULT '',
    annotation_type TEXT NOT NULL DEFAULT 'manual',
    created_by TEXT NOT NULL DEFAULT 'local-user',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    reviewed INTEGER NOT NULL DEFAULT 0,
    reviewed_by TEXT,
    reviewed_at TEXT,
    FOREIGN KEY (entity_id) REFERENCES entities(id),
    FOREIGN KEY (event_id) REFERENCES event_index(event_id)
)
"""

_DDL_EVENT_LINKS = """
CREATE TABLE IF NOT EXISTS event_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_event_id TEXT NOT NULL,
    target_event_id TEXT NOT NULL,
    link_type TEXT NOT NULL,
    strength REAL NOT NULL DEFAULT 0.5,
    signals TEXT NOT NULL DEFAULT '{}',
    target_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_event_id, target_event_id, link_type)
)
"""

_DDL_CHAIN_NARRATIVES = """
CREATE TABLE IF NOT EXISTS chain_narratives (
    chain_root_id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL,
    narrative TEXT NOT NULL,
    narrative_hash TEXT NOT NULL,
    event_count INTEGER NOT NULL DEFAULT 0,
    model_used TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_DDL_FEEDBACK = """
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    verdict_type TEXT NOT NULL,
    original_recommendation TEXT,
    comment TEXT,
    keywords_matched TEXT,
    source_id TEXT,
    created_at TEXT DEFAULT (datetime('now'))
)
"""

_DDL_ALERT_HISTORY = """
CREATE TABLE IF NOT EXISTS alert_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id TEXT NOT NULL,
    alert_key TEXT,
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    details TEXT,
    created_at TEXT DEFAULT (datetime('now'))
)
"""

_DDL_USERS = """
CREATE TABLE IF NOT EXISTS users (
    username       TEXT PRIMARY KEY,
    password_hash  TEXT NOT NULL,
    salt           TEXT NOT NULL,
    role           TEXT NOT NULL DEFAULT 'admin',
    api_key        TEXT,
    must_change_pw INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
)
"""

_DDL_SESSIONS = """
CREATE TABLE IF NOT EXISTS sessions (
    token_hash     TEXT PRIMARY KEY,
    username       TEXT NOT NULL,
    role           TEXT NOT NULL,
    has_api_key    INTEGER NOT NULL DEFAULT 0,
    created_at     REAL NOT NULL,
    expires_at     REAL NOT NULL
)
"""

_DDL_NOTIFICATIONS = """
CREATE TABLE IF NOT EXISTS notifications (
    id        INTEGER PRIMARY KEY CHECK (id = 1),
    config    TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_DDL_CANONICAL_EVENTS = """
CREATE TABLE IF NOT EXISTS canonical_events (
    canonical_event_id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    event_time TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    confidence REAL NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

_DDL_EVENT_MENTIONS = """
CREATE TABLE IF NOT EXISTS event_mentions (
    mention_id TEXT PRIMARY KEY,
    canonical_event_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    source_id TEXT,
    url TEXT,
    title TEXT NOT NULL,
    published_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (canonical_event_id) REFERENCES canonical_events(canonical_event_id)
)
"""

_DDL_CANONICAL_EVENT_RELATIONS = """
CREATE TABLE IF NOT EXISTS canonical_event_relations (
    relation_id TEXT PRIMARY KEY,
    source_canonical_event_id TEXT NOT NULL,
    target_canonical_event_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_canonical_event_id) REFERENCES canonical_events(canonical_event_id),
    FOREIGN KEY (target_canonical_event_id) REFERENCES canonical_events(canonical_event_id)
)
"""

_DDL_CANONICAL_GRAPH_OPERATIONS = """
CREATE TABLE IF NOT EXISTS canonical_graph_operations (
    operation_id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL,
    operation_type TEXT NOT NULL,
    decision_artifact_id TEXT,
    primary_canonical_event_id TEXT NOT NULL,
    result_canonical_event_id TEXT,
    status TEXT NOT NULL DEFAULT 'applied',
    changes_json TEXT NOT NULL DEFAULT '[]',
    warnings_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_by TEXT NOT NULL DEFAULT 'local-user',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

_DDL_TAXONOMY_ASSIGNMENTS = """
CREATE TABLE IF NOT EXISTS taxonomy_assignments (
    assignment_id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    taxonomy_level TEXT NOT NULL,
    taxonomy_value TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'projection',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

_DDL_CANONICAL_ENTITY_LINKS = """
CREATE TABLE IF NOT EXISTS canonical_entity_links (
    link_id TEXT PRIMARY KEY,
    canonical_event_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    entity_name TEXT NOT NULL,
    entity_type TEXT,
    confidence REAL NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (canonical_event_id) REFERENCES canonical_events(canonical_event_id)
)
"""

_DDL_RESEARCH_ARTIFACTS = """
CREATE TABLE IF NOT EXISTS research_artifacts (
    artifact_id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    subject_type TEXT NOT NULL DEFAULT 'canonical_event',
    subject_id TEXT NOT NULL DEFAULT '',
    canonical_event_ids_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'open',
    visibility TEXT NOT NULL DEFAULT 'local_private',
    created_by TEXT NOT NULL DEFAULT 'local-user',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

_DDL_PROJECTION_RUNS = """
CREATE TABLE IF NOT EXISTS projection_runs (
    projection_run_id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    input_events INTEGER NOT NULL DEFAULT 0,
    canonical_events INTEGER NOT NULL DEFAULT 0,
    mentions INTEGER NOT NULL DEFAULT 0,
    auto_merged INTEGER NOT NULL DEFAULT 0,
    needs_review INTEGER NOT NULL DEFAULT 0,
    unprojectable INTEGER NOT NULL DEFAULT 0,
    diagnostics_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

_DDL_AI_ENRICHMENT_USAGE = """
CREATE TABLE IF NOT EXISTS ai_enrichment_usage (
    usage_date TEXT PRIMARY KEY,
    request_count INTEGER NOT NULL DEFAULT 0,
    cooldown_until TEXT,
    last_error TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

_DDL_AI_ENRICHMENT_EVENTS = """
CREATE TABLE IF NOT EXISTS ai_enrichment_events (
    target_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    field_hash TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    model TEXT,
    route_id TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (target_id, event_id)
)
"""

_DDL_NOTIFICATION_RULES = """
CREATE TABLE IF NOT EXISTS notification_rules (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    rule_json TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

# Schema 迁移 — 版本化 DDL 变更，确保已有数据库自动升级
_DDL_SCHEMA_VERSION = """
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_SCHEMA_MIGRATIONS: list[tuple[int, str, list[str]]] = [
    # v1: 初始 schema（已由各 CREATE TABLE IF NOT EXISTS 覆盖，此处仅记录）
    (1, "Initial schema — 11 tables", []),
    # v2: Phase 31 NLP 列（之前用 try/except ALTER TABLE 处理）
    (
        2,
        "Add NLP columns to event_index",
        [
            "ALTER TABLE event_index ADD COLUMN sentiment TEXT",
            "ALTER TABLE event_index ADD COLUMN entity_names TEXT",
            "ALTER TABLE event_index ADD COLUMN topic_tags TEXT",
        ],
    ),
    # v3: Token 持久化 — sessions 表
    (3, "Add sessions table for token persistence", []),
    # v4: 通知设置 — notifications 表（替代 notifications.json）
    (4, "Add notifications table for settings persistence", []),
    # v5: 智能告警历史幂等键，避免重复检查 recent links 时无限膨胀。
    (
        5,
        "Add idempotency key to alert_history",
        [
            "ALTER TABLE alert_history ADD COLUMN alert_key TEXT",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_alert_history_key "
            "ON alert_history(target_id, alert_key)",
        ],
    ),
    (
        6,
        "create shadow canonical projection tables",
        [
            _DDL_CANONICAL_EVENTS,
            _DDL_EVENT_MENTIONS,
            _DDL_CANONICAL_EVENT_RELATIONS,
            _DDL_TAXONOMY_ASSIGNMENTS,
            _DDL_CANONICAL_ENTITY_LINKS,
            _DDL_RESEARCH_ARTIFACTS,
            _DDL_PROJECTION_RUNS,
        ],
    ),
    (
        7,
        "Add projection source fields to event_index",
        [
            "ALTER TABLE event_index ADD COLUMN url TEXT",
            "ALTER TABLE event_index ADD COLUMN metadata_json TEXT",
        ],
    ),
    (
        8,
        "Expand research artifacts for professional workflow",
        [
            "ALTER TABLE research_artifacts ADD COLUMN subject_type TEXT NOT NULL "
            "DEFAULT 'canonical_event'",
            "ALTER TABLE research_artifacts ADD COLUMN subject_id TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE research_artifacts ADD COLUMN status TEXT NOT NULL DEFAULT 'open'",
            "ALTER TABLE research_artifacts ADD COLUMN visibility TEXT NOT NULL "
            "DEFAULT 'local_private'",
            "ALTER TABLE research_artifacts ADD COLUMN created_by TEXT NOT NULL "
            "DEFAULT 'local-user'",
        ],
    ),
    (
        9,
        "create canonical graph operation log",
        [_DDL_CANONICAL_GRAPH_OPERATIONS],
    ),
    (
        10,
        "create AI enrichment state tables",
        [_DDL_AI_ENRICHMENT_USAGE, _DDL_AI_ENRICHMENT_EVENTS],
    ),
    (
        11,
        "Add public translation readiness to event_index",
        ["ALTER TABLE event_index ADD COLUMN public_translation_ready INTEGER NOT NULL DEFAULT 0"],
    ),
    (
        12,
        "Add FTS5 full-text search virtual table",
        [_DDL_EVENT_INDEX_FTS] + list(_DDL_FTS_TRIGGERS),
    ),
    (
        13,
        "Entity tracking v2 — extend entities table + entity_event_mentions + entity_fts",
        [
            "ALTER TABLE entities ADD COLUMN aliases TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE entities ADD COLUMN confidence INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE entities ADD COLUMN needs_review INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE entities ADD COLUMN first_seen_source_id TEXT",
            "ALTER TABLE entities ADD COLUMN last_seen_source_id TEXT",
            "ALTER TABLE entities ADD COLUMN is_manual INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE entities ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'",
            _DDL_ENTITY_EVENT_MENTIONS,
            _DDL_ENTITY_FTS,
        ]
        + list(_DDL_ENTITY_FTS_TRIGGERS),
    ),
    (
        14,
        "Entity annotations — manual correction audit trail",
        [_DDL_ENTITY_EVENT_ANNOTATIONS],
    ),
    (
        15,
        "Notification rules — user alert rule storage",
        [_DDL_NOTIFICATION_RULES],
    ),
    (
        16,
        "Add gid column to event_index and known_ids — "
        "UUID4 identifier alongside content-hash event_id",
        [
            "ALTER TABLE event_index ADD COLUMN gid TEXT",
            "ALTER TABLE known_ids ADD COLUMN gid TEXT",
        ],
    ),
]

_DDL_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_known_ids_seen ON known_ids(seen_at)",
    "CREATE INDEX IF NOT EXISTS idx_event_target_stage ON event_index(target_id, stage)",
    "CREATE INDEX IF NOT EXISTS idx_event_published ON event_index(published_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_event_sentiment ON event_index(sentiment)",
    "CREATE INDEX IF NOT EXISTS idx_event_topic_tags ON event_index(topic_tags)",
    "CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type)",
    "CREATE INDEX IF NOT EXISTS idx_entities_mentions ON entities(mention_count DESC)",
    "CREATE INDEX IF NOT EXISTS idx_entities_last_seen ON entities(last_seen DESC)",
    "CREATE INDEX IF NOT EXISTS idx_entities_needs_review ON entities(needs_review)",
    "CREATE INDEX IF NOT EXISTS idx_eem_event ON entity_event_mentions(event_id)",
    "CREATE INDEX IF NOT EXISTS idx_eem_entity ON entity_event_mentions(entity_id)",
    "CREATE INDEX IF NOT EXISTS idx_eem_source ON entity_event_mentions(source_id)",
    "CREATE INDEX IF NOT EXISTS idx_eea_entity ON entity_event_annotations(entity_id)",
    "CREATE INDEX IF NOT EXISTS idx_eea_event ON entity_event_annotations(event_id)",
    "CREATE INDEX IF NOT EXISTS idx_eea_reviewed ON entity_event_annotations(reviewed)",
    "CREATE INDEX IF NOT EXISTS idx_event_links_source ON event_links(source_event_id)",
    "CREATE INDEX IF NOT EXISTS idx_event_links_target ON event_links(target_event_id)",
    "CREATE INDEX IF NOT EXISTS idx_event_links_target_id ON event_links(target_id)",
    "CREATE INDEX IF NOT EXISTS idx_event_classification ON event_index(classification_l0)",
    "CREATE INDEX IF NOT EXISTS idx_event_source ON event_index(source_id)",
    "CREATE INDEX IF NOT EXISTS idx_event_score ON event_index(news_value_score)",
    "CREATE INDEX IF NOT EXISTS idx_narrative_target ON chain_narratives(target_id)",
    "CREATE INDEX IF NOT EXISTS idx_event_links_type ON event_links(link_type, strength)",
    "CREATE INDEX IF NOT EXISTS idx_event_created ON event_index(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_event_public_translation_ready "
    "ON event_index(target_id, stage, public_translation_ready, published_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_event_public_stage_ready_target "
    "ON event_index(stage, public_translation_ready, target_id)",
    "CREATE INDEX IF NOT EXISTS idx_event_public_stage_ready_time "
    "ON event_index(stage, public_translation_ready, "
    "published_at DESC, created_at DESC, event_id DESC)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_alert_history_key "
    "ON alert_history(target_id, alert_key)",
    "CREATE INDEX IF NOT EXISTS idx_canonical_events_target_status_time "
    "ON canonical_events(target_id, status, event_time)",
    "CREATE INDEX IF NOT EXISTS idx_event_mentions_canonical ON event_mentions(canonical_event_id)",
    "CREATE INDEX IF NOT EXISTS idx_event_mentions_target_event "
    "ON event_mentions(target_id, event_id)",
    "CREATE INDEX IF NOT EXISTS idx_event_mentions_url ON event_mentions(url)",
    "CREATE INDEX IF NOT EXISTS idx_canonical_relations_source "
    "ON canonical_event_relations(source_canonical_event_id)",
    "CREATE INDEX IF NOT EXISTS idx_canonical_relations_target "
    "ON canonical_event_relations(target_canonical_event_id)",
    "CREATE INDEX IF NOT EXISTS idx_canonical_graph_ops_target_type "
    "ON canonical_graph_operations(target_id, operation_type, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_canonical_graph_ops_artifact "
    "ON canonical_graph_operations(target_id, decision_artifact_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_canonical_graph_ops_artifact_unique "
    "ON canonical_graph_operations(target_id, decision_artifact_id) "
    "WHERE decision_artifact_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_canonical_graph_ops_primary "
    "ON canonical_graph_operations(target_id, primary_canonical_event_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_taxonomy_assignments_subject "
    "ON taxonomy_assignments(subject_type, subject_id)",
    "CREATE INDEX IF NOT EXISTS idx_taxonomy_assignments_target_value "
    "ON taxonomy_assignments(target_id, taxonomy_level, taxonomy_value)",
    "CREATE INDEX IF NOT EXISTS idx_canonical_entity_links_event "
    "ON canonical_entity_links(canonical_event_id)",
    "CREATE INDEX IF NOT EXISTS idx_research_artifacts_target_type "
    "ON research_artifacts(target_id, artifact_type)",
    "CREATE INDEX IF NOT EXISTS idx_research_artifacts_subject "
    "ON research_artifacts(target_id, subject_type, subject_id, artifact_type, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_research_artifacts_status "
    "ON research_artifacts(target_id, artifact_type, status, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_projection_runs_target_created "
    "ON projection_runs(target_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_ai_enrichment_events_status "
    "ON ai_enrichment_events(target_id, status, updated_at)",
)

_RESEARCH_ARTIFACT_COLUMNS = (
    "artifact_id",
    "target_id",
    "artifact_type",
    "title",
    "body",
    "subject_type",
    "subject_id",
    "canonical_event_ids_json",
    "status",
    "visibility",
    "created_by",
    "metadata_json",
    "created_at",
    "updated_at",
)

_RESEARCH_ARTIFACT_TYPES = {
    "review_state",
    "annotation",
    "note",
    "merge_decision",
    "split_decision",
}
_RESEARCH_ARTIFACT_STATUSES = {"open", "resolved", "archived"}

_CANONICAL_GRAPH_OPERATION_COLUMNS = (
    "operation_id",
    "target_id",
    "operation_type",
    "decision_artifact_id",
    "primary_canonical_event_id",
    "result_canonical_event_id",
    "status",
    "changes_json",
    "warnings_json",
    "metadata_json",
    "created_by",
    "created_at",
)
_CANONICAL_GRAPH_OPERATION_TYPES = {"merge", "split"}
_CANONICAL_GRAPH_OPERATION_STATUSES = {"applied"}

__all__ = [
    "_PRAGMA_SETUP",
    "_DDL_KNOWN_IDS",
    "_DDL_SOURCE_HEALTH",
    "_DDL_CURSORS",
    "_DDL_LLM_CACHE",
    "_DDL_EVENT_INDEX",
    "_DDL_EVENT_INDEX_FTS",
    "_DDL_FTS_TRIGGERS",
    "_DDL_ENTITIES",
    "_DDL_ENTITY_EVENT_MENTIONS",
    "_DDL_ENTITY_FTS",
    "_DDL_ENTITY_FTS_TRIGGERS",
    "_DDL_ENTITY_EVENT_ANNOTATIONS",
    "_DDL_EVENT_LINKS",
    "_DDL_CHAIN_NARRATIVES",
    "_DDL_FEEDBACK",
    "_DDL_ALERT_HISTORY",
    "_DDL_USERS",
    "_DDL_SESSIONS",
    "_DDL_NOTIFICATIONS",
    "_DDL_CANONICAL_EVENTS",
    "_DDL_EVENT_MENTIONS",
    "_DDL_CANONICAL_EVENT_RELATIONS",
    "_DDL_CANONICAL_GRAPH_OPERATIONS",
    "_DDL_TAXONOMY_ASSIGNMENTS",
    "_DDL_CANONICAL_ENTITY_LINKS",
    "_DDL_RESEARCH_ARTIFACTS",
    "_DDL_PROJECTION_RUNS",
    "_DDL_AI_ENRICHMENT_USAGE",
    "_DDL_AI_ENRICHMENT_EVENTS",
    "_DDL_NOTIFICATION_RULES",
    "_DDL_SCHEMA_VERSION",
    "_SCHEMA_MIGRATIONS",
    "_DDL_INDEXES",
    "_DDL_FTS_TRIGGERS",
    "_RESEARCH_ARTIFACT_COLUMNS",
    "_RESEARCH_ARTIFACT_TYPES",
    "_RESEARCH_ARTIFACT_STATUSES",
    "_CANONICAL_GRAPH_OPERATION_COLUMNS",
    "_CANONICAL_GRAPH_OPERATION_TYPES",
    "_CANONICAL_GRAPH_OPERATION_STATUSES",
]
