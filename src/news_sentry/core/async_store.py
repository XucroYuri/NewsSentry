"""AsyncStore — SQLite 存储层，替代 Memory 的 YAML 全量序列化。"""

from __future__ import annotations

import asyncio
import json
import logging

# aiosqlite worker 线程默认非 daemon，导致 create_app() 后进程无法退出。
# 在非测试环境中 patch aiosqlite.core.Thread 使 worker 为 daemon。
# 测试中不 patch，因为 pytest 的 per-test event loop 依赖 worker 线程正常关闭。
import os as _os
import sqlite3
import time
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite

from news_sentry.skills.filter.classification_taxonomy import canonical_l0, l0_query_values

if not _os.environ.get("PYTEST_CURRENT_TEST"):
    import aiosqlite.core as _aiosqlite_core

    _OrigThread = _aiosqlite_core.Thread  # type: ignore[attr-defined]

    class _DaemonThread(_OrigThread):  # type: ignore[misc, valid-type]
        def __init__(self, *args: object, **kwargs: object) -> None:
            kwargs.setdefault("daemon", True)
            super().__init__(*args, **kwargs)  # type: ignore[arg-type]

    _aiosqlite_core.Thread = _DaemonThread  # type: ignore[assignment, attr-defined]

logger = logging.getLogger(__name__)

_ANALYSIS_STAGES = ("judged", "drafts", "outputted")

_PRAGMA_SETUP = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA cache_size=-64000",
    "PRAGMA foreign_keys=ON",
)

_DDL_KNOWN_IDS = """
CREATE TABLE IF NOT EXISTS known_ids (
    event_id  TEXT PRIMARY KEY,
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
    sentiment         TEXT,
    entity_names      TEXT,
    topic_tags        TEXT,
    created_at        TEXT NOT NULL
)
"""

_DDL_ENTITIES = """
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    mention_count INTEGER DEFAULT 1,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    target_ids TEXT DEFAULT '',
    UNIQUE(canonical_name, entity_type)
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
    canonical_event_ids_json TEXT NOT NULL DEFAULT '[]',
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
    "CREATE INDEX IF NOT EXISTS idx_event_links_source ON event_links(source_event_id)",
    "CREATE INDEX IF NOT EXISTS idx_event_links_target ON event_links(target_event_id)",
    "CREATE INDEX IF NOT EXISTS idx_event_links_target_id ON event_links(target_id)",
    "CREATE INDEX IF NOT EXISTS idx_event_classification ON event_index(classification_l0)",
    "CREATE INDEX IF NOT EXISTS idx_event_source ON event_index(source_id)",
    "CREATE INDEX IF NOT EXISTS idx_event_score ON event_index(news_value_score)",
    "CREATE INDEX IF NOT EXISTS idx_narrative_target ON chain_narratives(target_id)",
    "CREATE INDEX IF NOT EXISTS idx_event_links_type ON event_links(link_type, strength)",
    "CREATE INDEX IF NOT EXISTS idx_event_created ON event_index(created_at)",
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
    "CREATE INDEX IF NOT EXISTS idx_taxonomy_assignments_subject "
    "ON taxonomy_assignments(subject_type, subject_id)",
    "CREATE INDEX IF NOT EXISTS idx_taxonomy_assignments_target_value "
    "ON taxonomy_assignments(target_id, taxonomy_level, taxonomy_value)",
    "CREATE INDEX IF NOT EXISTS idx_canonical_entity_links_event "
    "ON canonical_entity_links(canonical_event_id)",
    "CREATE INDEX IF NOT EXISTS idx_research_artifacts_target_type "
    "ON research_artifacts(target_id, artifact_type)",
    "CREATE INDEX IF NOT EXISTS idx_projection_runs_target_created "
    "ON projection_runs(target_id, created_at)",
)

__all__ = ["AsyncStore"]


class AsyncStore:
    """异步 SQLite 存储层。"""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    @property
    def db_path(self) -> Path:
        """数据库文件路径。"""
        return self._db_path

    async def initialize(self) -> None:
        if self._db is not None:
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        for pragma_sql in _PRAGMA_SETUP:
            await self._db.execute(pragma_sql)
        await self._db.execute(_DDL_KNOWN_IDS)
        await self._db.execute(_DDL_SOURCE_HEALTH)
        await self._db.execute(_DDL_CURSORS)
        await self._db.execute(_DDL_LLM_CACHE)
        await self._db.execute(_DDL_EVENT_INDEX)
        await self._db.execute(_DDL_ENTITIES)
        await self._db.execute(_DDL_EVENT_LINKS)
        await self._db.execute(_DDL_CHAIN_NARRATIVES)
        await self._db.execute(_DDL_FEEDBACK)
        await self._db.execute(_DDL_ALERT_HISTORY)
        await self._db.execute(_DDL_USERS)
        await self._db.execute(_DDL_SESSIONS)
        await self._db.execute(_DDL_NOTIFICATIONS)
        await self._db.execute(_DDL_SCHEMA_VERSION)
        await self._migrate_schema()
        for idx_sql in _DDL_INDEXES:
            await self._db.execute(idx_sql)
        await self._db.commit()
        logger.info("AsyncStore 初始化完成: %s", self._db_path)

    async def _migrate_schema(self) -> None:
        """按版本顺序执行 schema 迁移，确保已有数据库自动升级。"""
        assert self._db is not None
        # 读取当前版本
        async with self._db.execute("SELECT MAX(version) FROM schema_version") as cur:
            row = await cur.fetchone()
        current = row[0] if row and row[0] is not None else 0

        for version_num, description, ddl_list in _SCHEMA_MIGRATIONS:
            if version_num <= current:
                continue
            logger.info("执行 schema 迁移 v%d: %s", version_num, description)
            for ddl in ddl_list:
                try:
                    await self._db.execute(ddl)
                except Exception:  # noqa: S110
                    # 列/索引可能已存在（新数据库已包含，旧数据库需要此迁移）
                    pass
            await self._db.execute(
                "INSERT INTO schema_version (version, description) VALUES (?, ?)",
                (version_num, description),
            )
            await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None
            logger.info("AsyncStore 连接已关闭: %s", self._db_path)

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:
        """返回当前 AsyncStore 连接，供底层存储测试和内部查询复用。"""
        if self._db is None:
            await self.initialize()
        assert self._db is not None
        yield self._db

    def _json_dumps(self, value: Any) -> str:  # noqa: ANN401
        return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)

    def _json_loads(self, value: str | None) -> dict[str, Any]:
        if not value:
            return {}
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _row_with_metadata(self, columns: tuple[str, ...], row: Any) -> dict[str, Any]:  # noqa: ANN401
        item = dict(zip(columns, row, strict=True))
        item["metadata"] = self._json_loads(item.pop("metadata_json", None))
        return item

    @staticmethod
    def _safe_text_attr(event: object, attr: str) -> str | None:
        value = getattr(event, attr, None)
        return value if isinstance(value, str) else None

    @staticmethod
    def _safe_metadata_attr(event: object) -> dict[str, Any]:
        value = getattr(event, "metadata", {})
        return value if isinstance(value, dict) else {}

    # ------------------------------------------------------------------
    # Known IDs
    # ------------------------------------------------------------------

    async def is_known(self, event_id: str) -> bool:
        if self._db is None:
            return False
        async with self._db.execute(
            "SELECT 1 FROM known_ids WHERE event_id = ?", (event_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return row is not None

    async def mark_known(self, event_id: str) -> None:
        if self._db is None:
            return
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            "INSERT OR IGNORE INTO known_ids (event_id, seen_at) VALUES (?, ?)",
            (event_id, now),
        )
        await self._db.commit()

    async def prune_old_ids(self, max_age_days: int = 30) -> int:
        if self._db is None:
            return 0
        cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
        cutoff_str = cutoff.isoformat()
        async with self._db.execute(
            "SELECT COUNT(*) FROM known_ids WHERE seen_at < ?", (cutoff_str,)
        ) as cursor:
            row = await cursor.fetchone()
        stale_count = row[0] if row else 0
        if stale_count > 0:
            await self._db.execute("DELETE FROM known_ids WHERE seen_at < ?", (cutoff_str,))
            await self._db.commit()
            logger.info("pruned %d stale known_ids", stale_count)
        return stale_count

    # ------------------------------------------------------------------
    # Source Health
    # ------------------------------------------------------------------

    async def get_source_health(self, source_id: str) -> dict[str, Any] | None:
        if self._db is None:
            return None
        sql = (
            "SELECT source_id, status, last_check, error_count, metadata "
            "FROM source_health WHERE source_id = ?"
        )
        async with self._db.execute(sql, (source_id,)) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        result: dict[str, Any] = {
            "source_id": row[0],
            "status": row[1],
            "last_check": row[2],
            "error_count": row[3],
        }
        if row[4] is not None:
            try:
                result["metadata"] = json.loads(row[4])
            except json.JSONDecodeError:
                result["metadata"] = {}
        else:
            result["metadata"] = {}
        return result

    async def get_all_source_health(self) -> list[dict[str, Any]]:
        """批量查询所有信源健康状态。"""
        if self._db is None:
            return []
        rows = await self._db.execute_fetchall(
            "SELECT source_id, status, last_check, error_count, metadata "
            "FROM source_health ORDER BY source_id"
        )
        results: list[dict[str, Any]] = []
        for r in rows:
            entry: dict[str, Any] = {
                "source_id": r[0],
                "status": r[1],
                "last_check": r[2],
                "error_count": r[3],
            }
            if r[4]:
                try:
                    entry["metadata"] = json.loads(r[4])
                except (json.JSONDecodeError, TypeError):
                    entry["metadata"] = {}
            results.append(entry)
        return results

    async def record_source_health(
        self,
        source_id: str,
        status: str,
        error_count: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self._db is None:
            return
        now = datetime.now(UTC).isoformat()
        meta_json = json.dumps(metadata, ensure_ascii=False) if metadata else None
        await self._db.execute(
            """INSERT OR REPLACE INTO source_health
               (source_id, status, last_check, error_count, metadata)
               VALUES (?, ?, ?, ?, ?)""",
            (source_id, status, now, error_count, meta_json),
        )
        await self._db.commit()

    async def is_source_degraded(
        self,
        source_id: str,
        max_consecutive_failures: int = 5,
        min_success_rate: float = 0.3,
        min_total_runs: int = 10,
    ) -> bool:
        health = await self.get_source_health(source_id)
        if health is None:
            return False
        meta = health.get("metadata", {})
        consecutive = meta.get("consecutive_failures", 0)
        if isinstance(consecutive, (int, float)) and consecutive >= max_consecutive_failures:
            return True
        total = meta.get("total_runs", 0)
        failures = meta.get("total_failures", 0)
        if (
            isinstance(total, (int, float))
            and isinstance(failures, (int, float))
            and total >= min_total_runs
        ):
            success_rate = (total - failures) / total if total > 0 else 1.0
            if success_rate < min_success_rate:
                return True
        return False

    # ------------------------------------------------------------------
    # Cursors
    # ------------------------------------------------------------------

    async def get_cursor(self, source_id: str) -> str | None:
        if self._db is None:
            return None
        async with self._db.execute(
            "SELECT cursor FROM cursors WHERE source_id = ?", (source_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else None

    async def set_cursor(self, source_id: str, cursor: str) -> None:
        if self._db is None:
            return
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            """INSERT OR REPLACE INTO cursors (source_id, cursor, updated_at)
               VALUES (?, ?, ?)""",
            (source_id, cursor, now),
        )
        await self._db.commit()

    # ------------------------------------------------------------------
    # LLM Cache
    # ------------------------------------------------------------------

    async def get_cached_response(self, cache_key: str) -> str | None:
        if self._db is None:
            return None
        async with self._db.execute(
            "SELECT response FROM llm_cache WHERE cache_key = ?", (cache_key,)
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else None

    async def set_cached_response(self, cache_key: str, response: str, model: str) -> None:
        if self._db is None:
            return
        now = datetime.now(UTC).isoformat()
        async with self._db.execute(
            "SELECT created_at FROM llm_cache WHERE cache_key = ?", (cache_key,)
        ) as cursor:
            existing = await cursor.fetchone()
        if existing is not None:
            await self._db.execute(
                """UPDATE llm_cache SET response = ?, model = ?, updated_at = ?
                   WHERE cache_key = ?""",
                (response, model, now, cache_key),
            )
        else:
            await self._db.execute(
                """INSERT INTO llm_cache (cache_key, response, model, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (cache_key, response, model, now, now),
            )
        await self._db.commit()

    async def evict_if_needed(self, max_entries: int) -> int:
        if self._db is None:
            return 0
        async with self._db.execute("SELECT COUNT(*) FROM llm_cache") as cursor:
            row = await cursor.fetchone()
        count = row[0] if row else 0
        if count <= max_entries:
            return 0
        excess = count - max_entries
        await self._db.execute(
            """DELETE FROM llm_cache WHERE cache_key IN (
                   SELECT cache_key FROM llm_cache
                   ORDER BY updated_at ASC LIMIT ?
               )""",
            (excess,),
        )
        await self._db.commit()
        logger.info("evicted %d LLM cache entries (limit=%d)", excess, max_entries)
        return excess

    # ------------------------------------------------------------------
    # Event Index
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_nlp_fields(event: Any) -> tuple[str | None, str | None, str | None]:  # noqa: ANN401
        """从 event.judge_result.nlp_analysis 提取 SQLite 窄列值。"""
        judge_result = getattr(event, "judge_result", None)
        if judge_result is None:
            return None, None, None
        nlp = getattr(judge_result, "nlp_analysis", None)
        if nlp is None:
            return None, None, None

        sentiment = nlp.sentiment.value if nlp.sentiment is not None else None
        if not isinstance(sentiment, str):
            sentiment = None
        entity_names = ",".join(e.name for e in nlp.entities) if nlp.entities else None
        if not isinstance(entity_names, str):
            entity_names = None
        topic_tags = ",".join(nlp.topic_tags) if nlp.topic_tags else None
        if not isinstance(topic_tags, str):
            topic_tags = None
        return sentiment, entity_names, topic_tags

    async def index_event(
        self,
        event: object,
        target_id: str,
        stage: str,
        file_path: str | None = None,
    ) -> None:
        if self._db is None:
            return
        metadata = self._safe_metadata_attr(event)
        classification = metadata.get("classification", {})
        classification_l0 = classification.get("l0") if isinstance(classification, dict) else None
        classification_l0 = canonical_l0(classification_l0)
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            """INSERT OR REPLACE INTO event_index
               (event_id, target_id, stage, source_id, news_value_score,
                china_relevance, classification_l0, title_original,
                url, published_at, file_path, metadata_json, sentiment, entity_names, topic_tags,
                created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(
                   (SELECT created_at FROM event_index WHERE event_id = ?), ?))""",
            (
                getattr(event, "id", ""),
                target_id,
                stage,
                getattr(event, "source_id", None),
                getattr(event, "news_value_score", None),
                getattr(event, "china_relevance", None),
                classification_l0,
                getattr(event, "title_original", None),
                self._safe_text_attr(event, "url"),
                getattr(event, "published_at", None),
                file_path,
                self._json_dumps(metadata),
                *self._extract_nlp_fields(event),
                getattr(event, "id", ""),
                now,
            ),
        )
        await self._db.commit()

    async def query_events(
        self,
        target_id: str,
        stage: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        if self._db is None:
            return []
        async with self._db.execute(
            """SELECT event_id, target_id, stage, source_id, news_value_score,
                      china_relevance, classification_l0, title_original,
                      published_at, file_path, created_at,
                      sentiment, entity_names, topic_tags
               FROM event_index
               WHERE target_id = ? AND stage = ?
               ORDER BY published_at DESC
               LIMIT ? OFFSET ?""",
            (target_id, stage, limit, offset),
        ) as cursor:
            rows = await cursor.fetchall()
        cols = (
            "event_id",
            "target_id",
            "stage",
            "source_id",
            "news_value_score",
            "china_relevance",
            "classification_l0",
            "title_original",
            "published_at",
            "file_path",
            "created_at",
            "sentiment",
            "entity_names",
            "topic_tags",
        )
        return [dict(zip(cols, row, strict=True)) for row in rows]

    async def list_event_index_rows_for_projection(
        self,
        target_id: str,
        limit: int = 500,
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        """读取 event_index rows for shadow canonical projection."""
        params: list[Any] = [target_id]
        safe_limit = max(1, min(int(limit), 5000))
        if since:
            params.append(self._sqlite_datetime(since))
            query = """
                SELECT event_id, target_id, source_id, title_original, url, published_at,
                       stage, news_value_score, china_relevance,
                       classification_l0, metadata_json, file_path
                FROM event_index
                WHERE target_id = ?
                  AND datetime(COALESCE(published_at, created_at)) >= datetime(?)
                ORDER BY datetime(COALESCE(published_at, created_at)) DESC
                LIMIT ?
                """
        else:
            query = """
                SELECT event_id, target_id, source_id, title_original, url, published_at,
                       stage, news_value_score, china_relevance,
                       classification_l0, metadata_json, file_path
                FROM event_index
                WHERE target_id = ?
                ORDER BY datetime(COALESCE(published_at, created_at)) DESC
                LIMIT ?
                """
        params.append(safe_limit)
        async with self._connect() as conn:
            rows = await conn.execute_fetchall(query, params)
        result: list[dict[str, Any]] = []
        for row in rows:
            result.append(
                {
                    "event_id": row[0],
                    "target_id": row[1],
                    "source_id": row[2],
                    "title": row[3],
                    "url": row[4],
                    "published_at": row[5],
                    "pipeline_stage": row[6],
                    "news_value_score": row[7],
                    "china_relevance": row[8],
                    "l0_category": row[9],
                    "metadata": self._json_loads(row[10]),
                    "file_path": row[11],
                }
            )
        return result

    async def get_event_count(self, target_id: str, stage: str) -> int:
        if self._db is None:
            return 0
        async with self._db.execute(
            "SELECT COUNT(*) FROM event_index WHERE target_id = ? AND stage = ?",
            (target_id, stage),
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_target_event_count(self, target_id: str) -> int:
        """统计 target 在 event_index 中的所有阶段事件数。"""
        if self._db is None:
            return 0
        async with self._db.execute(
            "SELECT COUNT(*) FROM event_index WHERE target_id = ?",
            (target_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_stats(self, target_id: str) -> dict[str, Any]:
        if self._db is None:
            return {"total_events": 0, "stage_counts": {}, "avg_news_value_score": 0.0}
        async with self._db.execute(
            "SELECT COUNT(*) FROM event_index WHERE target_id = ?", (target_id,)
        ) as cursor:
            row = await cursor.fetchone()
        total = row[0] if row else 0
        async with self._db.execute(
            "SELECT stage, COUNT(*) FROM event_index WHERE target_id = ? GROUP BY stage",
            (target_id,),
        ) as cursor:
            stage_rows = await cursor.fetchall()
        stage_counts = {row[0]: row[1] for row in stage_rows}
        avg_sql = (
            "SELECT AVG(news_value_score) FROM event_index "
            "WHERE target_id = ? AND news_value_score IS NOT NULL"
        )
        async with self._db.execute(
            avg_sql,
            (target_id,),
        ) as cursor:
            row = await cursor.fetchone()
        avg_score = round(row[0], 1) if row and row[0] is not None else 0.0
        return {
            "total_events": total,
            "stage_counts": stage_counts,
            "avg_news_value_score": avg_score,
        }

    async def query_events_paginated(
        self,
        target_id: str,
        stage: str,
        *,
        limit: int = 20,
        offset: int = 0,
        source_id: str | None = None,
        classification_l0: str | None = None,
        min_score: int | None = None,
        sentiment: str | None = None,
        entity_name: str | None = None,
        topic_tag: str | None = None,
    ) -> dict[str, Any]:
        """分页查询 event_index，返回 {total: int, rows: list[dict]}。"""
        if self._db is None:
            return {"total": 0, "rows": []}
        conditions = ["target_id = ?", "stage = ?"]
        params: list[Any] = [target_id, stage]

        if source_id is not None:
            conditions.append("source_id = ?")
            params.append(source_id)
        if classification_l0 is not None:
            values = sorted(l0_query_values(classification_l0))
            placeholders = ", ".join("?" for _ in values)
            conditions.append(f"classification_l0 IN ({placeholders})")
            params.extend(values)
        if min_score is not None:
            conditions.append("news_value_score >= ?")
            params.append(min_score)
        if sentiment is not None:
            conditions.append("sentiment = ?")
            params.append(sentiment)
        if entity_name is not None:
            conditions.append("',' || entity_names || ',' LIKE '%,' || ? || ',%'")
            params.append(entity_name)
        if topic_tag is not None:
            conditions.append("',' || topic_tags || ',' LIKE '%,' || ? || ',%'")
            params.append(topic_tag)

        where = " AND ".join(conditions)

        # 总数查询
        count_sql = f"SELECT COUNT(*) FROM event_index WHERE {where}"  # noqa: S608
        async with self._db.execute(count_sql, params) as cursor:
            row = await cursor.fetchone()
            total = row[0] if row else 0

        # 分页查询
        data_sql = (
            "SELECT event_id, source_id, news_value_score, china_relevance, "  # noqa: S608
            "classification_l0, published_at, file_path, title_original, "
            "sentiment, entity_names, topic_tags "
            f"FROM event_index WHERE {where} "
            "ORDER BY published_at DESC LIMIT ? OFFSET ?"
        )
        async with self._db.execute(data_sql, params + [limit, offset]) as cursor:
            rows = await cursor.fetchall()

        result_rows = []
        for r in rows:
            result_rows.append(
                {
                    "event_id": r[0],
                    "source_id": r[1],
                    "news_value_score": r[2],
                    "china_relevance": r[3],
                    "classification_l0": canonical_l0(r[4]),
                    "published_at": r[5],
                    "file_path": r[6],
                    "title_original": r[7],
                    "sentiment": r[8],
                    "entity_names": r[9],
                    "topic_tags": r[10],
                }
            )

        return {"total": total, "rows": result_rows}

    async def get_stats_aggregated(self, target_id: str) -> dict[str, Any]:
        """聚合统计查询，返回事件总数、平均分、按分类/来源计数。"""
        if self._db is None:
            return {
                "total_events": 0,
                "avg_news_value_score": None,
                "avg_china_relevance": None,
                "by_classification": {},
                "by_source": {},
                "sentiment_breakdown": {},
                "top_entities": [],
            }
        async with self._db.execute(
            "SELECT COUNT(*) FROM event_index WHERE target_id = ?",
            [target_id],
        ) as cursor:
            row = await cursor.fetchone()
            total = row[0] if row else 0

        if total == 0:
            return {
                "total_events": 0,
                "avg_news_value_score": None,
                "avg_china_relevance": None,
                "by_classification": {},
                "by_source": {},
                "sentiment_breakdown": {},
                "top_entities": [],
            }

        async with self._db.execute(
            "SELECT AVG(news_value_score), AVG(china_relevance) "
            "FROM event_index WHERE target_id = ? "
            "AND news_value_score IS NOT NULL",
            [target_id],
        ) as cursor:
            row = await cursor.fetchone()
            avg_score = row[0] if row and row[0] is not None else None
            avg_relevance = row[1] if row and row[1] is not None else None

        by_classification: dict[str, int] = defaultdict(int)
        async with self._db.execute(
            "SELECT classification_l0, COUNT(*) FROM event_index "
            "WHERE target_id = ? AND classification_l0 IS NOT NULL "
            "GROUP BY classification_l0",
            [target_id],
        ) as cursor:
            async for row in cursor:
                by_classification[canonical_l0(row[0])] += row[1]

        by_source: dict[str, int] = {}
        async with self._db.execute(
            "SELECT source_id, COUNT(*) FROM event_index "
            "WHERE target_id = ? AND source_id IS NOT NULL "
            "GROUP BY source_id",
            [target_id],
        ) as cursor:
            async for row in cursor:
                by_source[row[0]] = row[1]

        # Phase 31: sentiment 分布
        sentiment_breakdown: dict[str, int] = {}
        async with self._db.execute(
            "SELECT sentiment, COUNT(*) FROM event_index WHERE target_id = ? GROUP BY sentiment",
            [target_id],
        ) as cursor:
            async for row in cursor:
                key = row[0] if row[0] is not None else "none"
                sentiment_breakdown[key] = row[1]

        # Phase 32: top entities
        top_entities: list[dict[str, Any]] = []
        async with self._db.execute(
            "SELECT canonical_name, entity_type, mention_count "
            "FROM entities ORDER BY mention_count DESC LIMIT 10"
        ) as cursor:
            async for row in cursor:
                top_entities.append(
                    {
                        "name": row[0],
                        "entity_type": row[1],
                        "mention_count": row[2],
                    }
                )

        return {
            "total_events": total,
            "avg_news_value_score": round(avg_score, 2) if avg_score is not None else None,
            "avg_china_relevance": round(avg_relevance, 2) if avg_relevance is not None else None,
            "by_classification": by_classification,
            "by_source": by_source,
            "sentiment_breakdown": sentiment_breakdown,
            "top_entities": top_entities,
        }

    async def get_event_file_path(self, event_id: str) -> str | None:
        """根据 event_id 查找对应的 .md 文件路径。"""
        if self._db is None:
            return None
        async with self._db.execute(
            "SELECT file_path FROM event_index WHERE event_id = ?",
            [event_id],
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

    async def get_event_index_row(self, target_id: str, event_id: str) -> dict[str, Any] | None:
        """按 target_id + event_id 读取 event_index 行。"""
        if self._db is None:
            return None
        async with self._db.execute(
            """SELECT event_id, target_id, stage, source_id,
                      news_value_score, china_relevance, classification_l0,
                      title_original, published_at, file_path, sentiment,
                      entity_names, topic_tags, created_at
               FROM event_index
               WHERE target_id = ? AND event_id = ?""",
            (target_id, event_id),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        cols = (
            "event_id",
            "target_id",
            "stage",
            "source_id",
            "news_value_score",
            "china_relevance",
            "classification_l0",
            "title_original",
            "published_at",
            "file_path",
            "sentiment",
            "entity_names",
            "topic_tags",
            "created_at",
        )
        return dict(zip(cols, row, strict=True))

    # ------------------------------------------------------------------
    # Shadow Canonical Store
    # ------------------------------------------------------------------

    async def upsert_canonical_event(self, row: dict[str, Any]) -> str:
        """插入或更新 shadow canonical event，返回 canonical_event_id。"""
        canonical_event_id = str(row["canonical_event_id"])
        if self._db is None:
            return canonical_event_id
        await self._db.execute(
            """INSERT INTO canonical_events
               (canonical_event_id, target_id, title, summary, event_time,
                status, confidence, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(canonical_event_id) DO UPDATE SET
                   target_id = excluded.target_id,
                   title = excluded.title,
                   summary = excluded.summary,
                   event_time = excluded.event_time,
                   status = excluded.status,
                   confidence = excluded.confidence,
                   metadata_json = excluded.metadata_json,
                   updated_at = CURRENT_TIMESTAMP""",
            (
                canonical_event_id,
                row["target_id"],
                row["title"],
                row.get("summary", ""),
                row.get("event_time"),
                row.get("status", "active"),
                row.get("confidence", 0),
                self._json_dumps(row.get("metadata")),
            ),
        )
        await self._db.commit()
        return canonical_event_id

    async def upsert_event_mention(self, row: dict[str, Any]) -> str:
        """插入或更新 canonical event mention，返回 mention_id。"""
        mention_id = str(row["mention_id"])
        if self._db is None:
            return mention_id
        await self._db.execute(
            """INSERT INTO event_mentions
               (mention_id, canonical_event_id, event_id, target_id, source_id,
                url, title, published_at, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(mention_id) DO UPDATE SET
                   canonical_event_id = excluded.canonical_event_id,
                   event_id = excluded.event_id,
                   target_id = excluded.target_id,
                   source_id = excluded.source_id,
                   url = excluded.url,
                   title = excluded.title,
                   published_at = excluded.published_at,
                   metadata_json = excluded.metadata_json,
                   updated_at = CURRENT_TIMESTAMP""",
            (
                mention_id,
                row["canonical_event_id"],
                row["event_id"],
                row["target_id"],
                row.get("source_id"),
                row.get("url"),
                row["title"],
                row.get("published_at"),
                self._json_dumps(row.get("metadata")),
            ),
        )
        await self._db.commit()
        return mention_id

    async def upsert_canonical_relation(self, row: dict[str, Any]) -> str:
        """插入或更新 canonical event relation，返回 relation_id。"""
        relation_id = str(row["relation_id"])
        if self._db is None:
            return relation_id
        await self._db.execute(
            """INSERT INTO canonical_event_relations
               (relation_id, source_canonical_event_id, target_canonical_event_id,
                relation_type, confidence, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(relation_id) DO UPDATE SET
                   source_canonical_event_id = excluded.source_canonical_event_id,
                   target_canonical_event_id = excluded.target_canonical_event_id,
                   relation_type = excluded.relation_type,
                   confidence = excluded.confidence,
                   metadata_json = excluded.metadata_json,
                   updated_at = CURRENT_TIMESTAMP""",
            (
                relation_id,
                row["source_canonical_event_id"],
                row["target_canonical_event_id"],
                row["relation_type"],
                row.get("confidence", 0),
                self._json_dumps(row.get("metadata")),
            ),
        )
        await self._db.commit()
        return relation_id

    async def upsert_taxonomy_assignment(self, row: dict[str, Any]) -> str:
        """插入或更新 taxonomy assignment，返回 assignment_id。"""
        assignment_id = str(row["assignment_id"])
        if self._db is None:
            return assignment_id
        await self._db.execute(
            """INSERT INTO taxonomy_assignments
               (assignment_id, subject_type, subject_id, target_id, taxonomy_level,
                taxonomy_value, confidence, source, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(assignment_id) DO UPDATE SET
                   subject_type = excluded.subject_type,
                   subject_id = excluded.subject_id,
                   target_id = excluded.target_id,
                   taxonomy_level = excluded.taxonomy_level,
                   taxonomy_value = excluded.taxonomy_value,
                   confidence = excluded.confidence,
                   source = excluded.source,
                   metadata_json = excluded.metadata_json,
                   updated_at = CURRENT_TIMESTAMP""",
            (
                assignment_id,
                row["subject_type"],
                row["subject_id"],
                row["target_id"],
                row["taxonomy_level"],
                row["taxonomy_value"],
                row.get("confidence", 0),
                row.get("source", "projection"),
                self._json_dumps(row.get("metadata")),
            ),
        )
        await self._db.commit()
        return assignment_id

    async def record_projection_run(self, row: dict[str, Any]) -> str:
        """记录 shadow projection run，返回 projection_run_id。"""
        projection_run_id = str(row["projection_run_id"])
        if self._db is None:
            return projection_run_id
        await self._db.execute(
            """INSERT INTO projection_runs
               (projection_run_id, target_id, mode, input_events, canonical_events,
                mentions, auto_merged, needs_review, unprojectable, diagnostics_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(projection_run_id) DO UPDATE SET
                   target_id = excluded.target_id,
                   mode = excluded.mode,
                   input_events = excluded.input_events,
                   canonical_events = excluded.canonical_events,
                   mentions = excluded.mentions,
                   auto_merged = excluded.auto_merged,
                   needs_review = excluded.needs_review,
                   unprojectable = excluded.unprojectable,
                   diagnostics_json = excluded.diagnostics_json""",
            (
                projection_run_id,
                row["target_id"],
                row["mode"],
                row.get("input_events", 0),
                row.get("canonical_events", 0),
                row.get("mentions", 0),
                row.get("auto_merged", 0),
                row.get("needs_review", 0),
                row.get("unprojectable", 0),
                self._json_dumps(row.get("diagnostics")),
            ),
        )
        await self._db.commit()
        return projection_run_id

    async def apply_canonical_projection(
        self,
        *,
        candidates: list[dict[str, Any]],
        projection_run: dict[str, Any],
    ) -> str:
        """在单个事务内应用 canonical projection，失败时整体回滚。"""
        projection_run_id = str(projection_run["projection_run_id"])
        if self._db is None:
            await self.initialize()
        async with self._lock:
            async with aiosqlite.connect(str(self._db_path)) as conn:
                for pragma_sql in _PRAGMA_SETUP:
                    await conn.execute(pragma_sql)
                try:
                    await conn.execute("BEGIN IMMEDIATE")
                    for candidate in candidates:
                        await conn.execute(
                            """INSERT INTO canonical_events
                               (canonical_event_id, target_id, title, summary, event_time,
                                status, confidence, metadata_json)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                               ON CONFLICT(canonical_event_id) DO UPDATE SET
                                   target_id = excluded.target_id,
                                   title = excluded.title,
                                   summary = excluded.summary,
                                   event_time = excluded.event_time,
                                   status = excluded.status,
                                   confidence = excluded.confidence,
                                   metadata_json = excluded.metadata_json,
                                   updated_at = CURRENT_TIMESTAMP""",
                            (
                                candidate["canonical_event_id"],
                                candidate["target_id"],
                                candidate["title"],
                                candidate.get("summary", ""),
                                candidate.get("event_time"),
                                candidate.get("status", "active"),
                                candidate.get("confidence", 0),
                                self._json_dumps(candidate.get("metadata")),
                            ),
                        )
                        for mention in candidate.get("mention_rows", []):
                            await conn.execute(
                                """INSERT INTO event_mentions
                                   (mention_id, canonical_event_id, event_id, target_id,
                                    source_id, url, title, published_at, metadata_json)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                   ON CONFLICT(mention_id) DO UPDATE SET
                                       canonical_event_id = excluded.canonical_event_id,
                                       event_id = excluded.event_id,
                                       target_id = excluded.target_id,
                                       source_id = excluded.source_id,
                                       url = excluded.url,
                                       title = excluded.title,
                                       published_at = excluded.published_at,
                                       metadata_json = excluded.metadata_json,
                                       updated_at = CURRENT_TIMESTAMP""",
                                (
                                    mention["mention_id"],
                                    mention["canonical_event_id"],
                                    mention["event_id"],
                                    mention["target_id"],
                                    mention.get("source_id"),
                                    mention.get("url"),
                                    mention["title"],
                                    mention.get("published_at"),
                                    self._json_dumps(mention.get("metadata")),
                                ),
                            )
                        for taxonomy in candidate.get("taxonomy_rows", []):
                            await conn.execute(
                                """INSERT INTO taxonomy_assignments
                                   (assignment_id, subject_type, subject_id, target_id,
                                    taxonomy_level, taxonomy_value, confidence, source,
                                    metadata_json)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                   ON CONFLICT(assignment_id) DO UPDATE SET
                                       subject_type = excluded.subject_type,
                                       subject_id = excluded.subject_id,
                                       target_id = excluded.target_id,
                                       taxonomy_level = excluded.taxonomy_level,
                                       taxonomy_value = excluded.taxonomy_value,
                                       confidence = excluded.confidence,
                                       source = excluded.source,
                                       metadata_json = excluded.metadata_json,
                                       updated_at = CURRENT_TIMESTAMP""",
                                (
                                    taxonomy["assignment_id"],
                                    taxonomy["subject_type"],
                                    taxonomy["subject_id"],
                                    taxonomy["target_id"],
                                    taxonomy["taxonomy_level"],
                                    taxonomy["taxonomy_value"],
                                    taxonomy.get("confidence", 0),
                                    taxonomy.get("source", "projection"),
                                    self._json_dumps(taxonomy.get("metadata")),
                                ),
                            )
                    await conn.execute(
                        """INSERT INTO projection_runs
                           (projection_run_id, target_id, mode, input_events,
                            canonical_events, mentions, auto_merged, needs_review,
                            unprojectable, diagnostics_json)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(projection_run_id) DO UPDATE SET
                               target_id = excluded.target_id,
                               mode = excluded.mode,
                               input_events = excluded.input_events,
                               canonical_events = excluded.canonical_events,
                               mentions = excluded.mentions,
                               auto_merged = excluded.auto_merged,
                               needs_review = excluded.needs_review,
                               unprojectable = excluded.unprojectable,
                               diagnostics_json = excluded.diagnostics_json""",
                        (
                            projection_run_id,
                            projection_run["target_id"],
                            projection_run["mode"],
                            projection_run.get("input_events", 0),
                            projection_run.get("canonical_events", 0),
                            projection_run.get("mentions", 0),
                            projection_run.get("auto_merged", 0),
                            projection_run.get("needs_review", 0),
                            projection_run.get("unprojectable", 0),
                            self._json_dumps(projection_run.get("diagnostics")),
                        ),
                    )
                except Exception:
                    await conn.rollback()
                    raise
                await conn.commit()
        return projection_run_id

    async def list_canonical_events(
        self,
        *,
        target_id: str,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """列出 target 下的 canonical events。"""
        if self._db is None:
            return []
        if status is not None:
            rows = await self._db.execute_fetchall(
                """SELECT canonical_event_id, target_id, title, summary, event_time, status,
                          confidence, metadata_json, created_at, updated_at
                   FROM canonical_events
                   WHERE target_id = ? AND status = ?
                   ORDER BY COALESCE(event_time, updated_at) DESC
                   LIMIT ? OFFSET ?""",
                (target_id, status, limit, offset),
            )
        else:
            rows = await self._db.execute_fetchall(
                """SELECT canonical_event_id, target_id, title, summary, event_time, status,
                          confidence, metadata_json, created_at, updated_at
                   FROM canonical_events
                   WHERE target_id = ?
                   ORDER BY COALESCE(event_time, updated_at) DESC
                   LIMIT ? OFFSET ?""",
                (target_id, limit, offset),
            )
        columns = (
            "canonical_event_id",
            "target_id",
            "title",
            "summary",
            "event_time",
            "status",
            "confidence",
            "metadata_json",
            "created_at",
            "updated_at",
        )
        return [self._row_with_metadata(columns, row) for row in rows]

    async def get_canonical_event(self, canonical_event_id: str) -> dict[str, Any] | None:
        """读取单个 canonical event。"""
        if self._db is None:
            return None
        async with self._db.execute(
            """SELECT canonical_event_id, target_id, title, summary, event_time, status,
                      confidence, metadata_json, created_at, updated_at
               FROM canonical_events
               WHERE canonical_event_id = ?""",
            (canonical_event_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        columns = (
            "canonical_event_id",
            "target_id",
            "title",
            "summary",
            "event_time",
            "status",
            "confidence",
            "metadata_json",
            "created_at",
            "updated_at",
        )
        return self._row_with_metadata(columns, row)

    async def list_event_mentions(self, canonical_event_id: str) -> list[dict[str, Any]]:
        """列出 canonical event 的 mentions。"""
        if self._db is None:
            return []
        rows = await self._db.execute_fetchall(
            """SELECT mention_id, canonical_event_id, event_id, target_id, source_id,
                      url, title, published_at, metadata_json, created_at, updated_at
               FROM event_mentions
               WHERE canonical_event_id = ?
               ORDER BY COALESCE(published_at, updated_at) DESC""",
            (canonical_event_id,),
        )
        columns = (
            "mention_id",
            "canonical_event_id",
            "event_id",
            "target_id",
            "source_id",
            "url",
            "title",
            "published_at",
            "metadata_json",
            "created_at",
            "updated_at",
        )
        return [self._row_with_metadata(columns, row) for row in rows]

    async def list_canonical_relations(self, canonical_event_id: str) -> list[dict[str, Any]]:
        """列出 source 或 target 匹配的 canonical event relations。"""
        if self._db is None:
            return []
        rows = await self._db.execute_fetchall(
            """SELECT relation_id, source_canonical_event_id, target_canonical_event_id,
                      relation_type, confidence, metadata_json, created_at, updated_at
               FROM canonical_event_relations
               WHERE source_canonical_event_id = ? OR target_canonical_event_id = ?
               ORDER BY updated_at DESC""",
            (canonical_event_id, canonical_event_id),
        )
        columns = (
            "relation_id",
            "source_canonical_event_id",
            "target_canonical_event_id",
            "relation_type",
            "confidence",
            "metadata_json",
            "created_at",
            "updated_at",
        )
        return [self._row_with_metadata(columns, row) for row in rows]

    # ------------------------------------------------------------------
    # Entity Tracking (Phase 32)
    # ------------------------------------------------------------------

    async def upsert_entity(
        self,
        name: str,
        entity_type: str,
        target_id: str,
        seen_at: str,
    ) -> None:
        """插入或更新实体记录（同名+同类型视为同一实体）。"""
        if self._db is None:
            return
        await self._db.execute(
            """INSERT INTO entities (canonical_name, entity_type, first_seen, last_seen, target_ids)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(canonical_name, entity_type) DO UPDATE SET
                   mention_count = mention_count + 1,
                   last_seen = excluded.last_seen,
                   target_ids = CASE
                       WHEN ',' || target_ids || ',' LIKE '%,' || excluded.target_ids || ',%'
                       THEN target_ids
                       ELSE target_ids || ',' || excluded.target_ids
                   END""",
            (name, entity_type, seen_at, seen_at, target_id),
        )
        await self._db.commit()

    async def query_entities(
        self,
        entity_type: str | None = None,
        target_id: str | None = None,
        min_mentions: int = 1,
        limit: int = 20,
        sort: str = "mention_count",
    ) -> list[dict[str, Any]]:
        """查询实体列表，支持过滤和排序。"""
        if self._db is None:
            return []
        conditions = ["mention_count >= ?"]
        params: list[Any] = [min_mentions]
        if entity_type is not None:
            conditions.append("entity_type = ?")
            params.append(entity_type)
        if target_id is not None:
            conditions.append("',' || target_ids || ',' LIKE '%,' || ? || ',%'")
            params.append(target_id)
        where = " AND ".join(conditions)
        order = "mention_count DESC" if sort == "mention_count" else "last_seen DESC"
        sql = (
            f"SELECT id, canonical_name, entity_type, mention_count, "  # noqa: S608
            f"first_seen, last_seen, target_ids "
            f"FROM entities WHERE {where} ORDER BY {order} LIMIT ?"
        )
        async with self._db.execute(sql, params + [limit]) as cursor:
            rows = await cursor.fetchall()
        cols = (
            "id",
            "canonical_name",
            "entity_type",
            "mention_count",
            "first_seen",
            "last_seen",
            "target_ids",
        )
        return [dict(zip(cols, row, strict=True)) for row in rows]

    async def query_entity_detail(self, entity_id: int) -> dict[str, Any] | None:
        """查询实体详情，附带最近关联事件。"""
        if self._db is None:
            return None
        async with self._db.execute(
            "SELECT id, canonical_name, entity_type, mention_count, "
            "first_seen, last_seen, target_ids FROM entities WHERE id = ?",
            [entity_id],
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        cols = (
            "id",
            "canonical_name",
            "entity_type",
            "mention_count",
            "first_seen",
            "last_seen",
            "target_ids",
        )
        entity = dict(zip(cols, row, strict=True))
        # 关联事件：从 event_index 的 entity_names LIKE 匹配
        name = entity["canonical_name"]
        recent_events: list[dict[str, Any]] = []
        async with self._db.execute(
            "SELECT event_id, title_original, published_at, sentiment, news_value_score "
            "FROM event_index WHERE ',' || entity_names || ',' LIKE '%,' || ? || ',%' "
            "ORDER BY published_at DESC LIMIT 10",
            [name],
        ) as cursor:
            rows = await cursor.fetchall()
        ev_cols = ("event_id", "title_original", "published_at", "sentiment", "news_value_score")
        recent_events = [dict(zip(ev_cols, r, strict=True)) for r in rows]
        entity["recent_events"] = recent_events
        return entity

    # ------------------------------------------------------------------
    # Event Links (Phase 35)
    # ------------------------------------------------------------------

    async def create_link(
        self,
        source_event_id: str,
        target_event_id: str,
        link_type: str,
        strength: float,
        signals: dict[str, Any],
        target_id: str,
    ) -> None:
        """写入事件关联（UNIQUE 约束去重）。"""
        if self._db is None:
            return
        signals_json = json.dumps(signals, ensure_ascii=False)
        await self._db.execute(
            """INSERT OR IGNORE INTO event_links
               (source_event_id, target_event_id, link_type, strength, signals, target_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (source_event_id, target_event_id, link_type, strength, signals_json, target_id),
        )
        await self._db.commit()

    async def get_event_links(self, event_id: str) -> list[dict[str, Any]]:
        """获取某事件的所有直接关联（双向）。"""
        if self._db is None:
            return []
        results: list[dict[str, Any]] = []
        # 作为 source 的关联
        async with self._db.execute(
            "SELECT target_event_id, link_type, strength, signals, created_at "
            "FROM event_links WHERE source_event_id = ?",
            [event_id],
        ) as cursor:
            async for row in cursor:
                results.append(
                    {
                        "linked_event_id": row[0],
                        "link_type": row[1],
                        "strength": row[2],
                        "direction": "forward",
                        "signals": json.loads(row[3]) if row[3] else {},
                        "created_at": row[4],
                    }
                )
        # 作为 target 的关联
        async with self._db.execute(
            "SELECT source_event_id, link_type, strength, signals, created_at "
            "FROM event_links WHERE target_event_id = ?",
            [event_id],
        ) as cursor:
            async for row in cursor:
                results.append(
                    {
                        "linked_event_id": row[0],
                        "link_type": row[1],
                        "strength": row[2],
                        "direction": "backward",
                        "signals": json.loads(row[3]) if row[3] else {},
                        "created_at": row[4],
                    }
                )
        return results

    async def find_candidates(
        self,
        target_id: str,
        event_id: str,
        days: int = 7,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """查找同一 target 最近 N 天的候选关联事件（排除自身）。"""
        if self._db is None:
            return []
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        capped_limit = max(1, int(limit))
        async with self._db.execute(
            "SELECT event_id, entity_names, topic_tags, published_at, title_original "
            "FROM event_index WHERE target_id = ? AND event_id != ? "
            "AND published_at >= ? ORDER BY published_at DESC LIMIT ?",
            [target_id, event_id, cutoff, capped_limit],
        ) as cursor:
            rows = await cursor.fetchall()
        cols = ("event_id", "entity_names", "topic_tags", "published_at", "title_original")
        return [dict(zip(cols, row, strict=True)) for row in rows]

    async def get_event_chain(
        self,
        event_id: str,
        depth: int = 5,
    ) -> list[dict[str, Any]]:
        """向前向后遍历关联链，返回链上所有事件。"""
        if self._db is None:
            return []
        visited: set[str] = set()
        chain_events: list[dict[str, Any]] = []

        # 收集链上所有 event_id (BFS)
        queue = [event_id]
        visited.add(event_id)
        while queue and len(visited) < depth * 2 + 1:
            current = queue.pop(0)
            linked_ids: set[str] = set()
            async with self._db.execute(
                "SELECT target_event_id FROM event_links WHERE source_event_id = ?",
                [current],
            ) as cursor:
                async for row in cursor:
                    linked_ids.add(row[0])
            async with self._db.execute(
                "SELECT source_event_id FROM event_links WHERE target_event_id = ?",
                [current],
            ) as cursor:
                async for row in cursor:
                    linked_ids.add(row[0])
            for lid in linked_ids:
                if lid not in visited:
                    visited.add(lid)
                    queue.append(lid)

        # 批量查询事件信息
        if not visited:
            return []
        placeholders = ",".join("?" for _ in visited)
        async with self._db.execute(
            f"SELECT event_id, title_original, published_at, sentiment, "  # noqa: S608
            f"entity_names, topic_tags, news_value_score FROM event_index "
            f"WHERE event_id IN ({placeholders}) ORDER BY published_at ASC",
            list(visited),
        ) as cursor:
            rows = await cursor.fetchall()
        for row in rows:
            chain_events.append(
                {
                    "event_id": row[0],
                    "title_original": row[1],
                    "published_at": row[2],
                    "sentiment": row[3],
                    "entity_names": row[4],
                    "topic_tags": row[5],
                    "news_value_score": row[6],
                }
            )
        return chain_events

    async def get_active_chains(self, target_id: str) -> list[dict[str, Any]]:
        """获取当前 target 的活跃追踪链（含叙述摘要）。"""
        if self._db is None:
            return []
        # 找所有有 link 的 root events
        async with self._db.execute(
            "SELECT DISTINCT source_event_id FROM event_links WHERE target_id = ?",
            [target_id],
        ) as cursor:
            root_ids = [r[0] for r in await cursor.fetchall()]

        if not root_ids:
            return []

        # 批量获取 narratives
        narrative_map: dict[str, str] = {}
        if root_ids:
            placeholders = ",".join("?" * len(root_ids))
            async with self._db.execute(
                f"SELECT chain_root_id, narrative FROM chain_narratives "  # noqa: S608
                f"WHERE chain_root_id IN ({placeholders})",
                root_ids,
            ) as cursor:
                for row in await cursor.fetchall():
                    narrative_map[row[0]] = row[1]

        chains: list[dict[str, Any]] = []
        for root_id in root_ids:
            chain = await self.get_event_chain(root_id, depth=10)
            if chain:
                latest = chain[-1]
                narr = narrative_map.get(root_id, "")
                chains.append(
                    {
                        "root_event_id": root_id,
                        "event_count": len(chain),
                        "latest_time": latest.get("published_at", ""),
                        "latest_title": latest.get("title_original", ""),
                        "has_narrative": bool(narr),
                        "narrative_summary": narr[:50] + "..." if len(narr) > 50 else narr,
                    }
                )
        return sorted(chains, key=lambda c: c["latest_time"], reverse=True)

    # ------------------------------------------------------------------
    # Chain Narratives (Phase 36)
    # ------------------------------------------------------------------

    async def get_narrative(self, chain_root_id: str) -> dict[str, Any] | None:
        """获取链的叙述。"""
        if self._db is None:
            return None
        async with self._db.execute(
            "SELECT chain_root_id, target_id, narrative, narrative_hash, "
            "event_count, model_used, created_at, updated_at "
            "FROM chain_narratives WHERE chain_root_id = ?",
            [chain_root_id],
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        cols = (
            "chain_root_id",
            "target_id",
            "narrative",
            "narrative_hash",
            "event_count",
            "model_used",
            "created_at",
            "updated_at",
        )
        return dict(zip(cols, row, strict=True))

    async def upsert_narrative(
        self,
        chain_root_id: str,
        target_id: str,
        narrative: str,
        narrative_hash: str,
        event_count: int,
        model_used: str,
    ) -> None:
        """写入或更新链叙述。"""
        if self._db is None:
            return
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            """INSERT INTO chain_narratives
               (chain_root_id, target_id, narrative, narrative_hash,
                event_count, model_used, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(chain_root_id) DO UPDATE SET
                   narrative = excluded.narrative,
                   narrative_hash = excluded.narrative_hash,
                   event_count = excluded.event_count,
                   model_used = excluded.model_used,
                   updated_at = excluded.updated_at""",
            (
                chain_root_id,
                target_id,
                narrative,
                narrative_hash,
                event_count,
                model_used,
                now,
                now,
            ),
        )
        await self._db.commit()

    @staticmethod
    def compute_chain_hash(events: list[dict[str, Any]]) -> str:
        """计算事件列表的 SHA-256 摘要。"""
        from hashlib import sha256

        parts = "|".join(
            f"{e.get('event_id', '')}:{e.get('published_at', '')}:{e.get('title_original', '')}"
            for e in sorted(events, key=lambda x: x.get("event_id", ""))
        )
        return sha256(parts.encode()).hexdigest()

    # ------------------------------------------------------------------
    # Trend Analysis (Phase 37)
    # ------------------------------------------------------------------

    async def get_sentiment_daily_counts(
        self, target_id: str, days: int = 14
    ) -> list[dict[str, Any]]:
        """按天统计情感分布，返回 [{day, sentiment, count}, ...]."""
        if self._db is None:
            return []
        async with self._db.execute(
            "SELECT date(published_at) AS day, sentiment, COUNT(*) AS cnt "
            "FROM event_index "
            "WHERE target_id = ? AND stage IN (?, ?, ?) "
            "AND published_at >= date('now', ? || ' days') "
            "AND sentiment IS NOT NULL "
            "GROUP BY day, sentiment ORDER BY day",
            [target_id, *_ANALYSIS_STAGES, f"-{days}"],
        ) as cursor:
            rows = await cursor.fetchall()
        return [{"day": r[0], "sentiment": r[1], "count": r[2]} for r in rows]

    async def get_topic_daily_counts(self, target_id: str, days: int = 14) -> list[dict[str, Any]]:
        """按天统计每个 topic 的出现次数，返回 [{topic, day, count}, ...]."""
        if self._db is None:
            return []
        async with self._db.execute(
            "SELECT date(published_at) AS day, topic_tags "
            "FROM event_index "
            "WHERE target_id = ? AND stage IN (?, ?, ?) "
            "AND published_at >= date('now', ? || ' days') "
            "AND topic_tags IS NOT NULL AND topic_tags != ''",
            [target_id, *_ANALYSIS_STAGES, f"-{days}"],
        ) as cursor:
            rows = await cursor.fetchall()
        # Python 层拆分 topic_tags 并按 (topic, day) 聚合
        counts: dict[tuple[str, str], int] = {}
        for day, tags_str in rows:
            for tag in tags_str.split(","):
                tag = tag.strip()
                if tag:
                    key = (tag, day)
                    counts[key] = counts.get(key, 0) + 1
        return [
            {"topic": topic, "day": day, "count": cnt}
            for (topic, day), cnt in sorted(counts.items())
        ]

    async def get_top_topics(
        self, target_id: str, days: int = 7, limit: int = 10
    ) -> list[dict[str, Any]]:
        """获取最近 N 天最热主题排名。"""
        if self._db is None:
            return []
        async with self._db.execute(
            "SELECT topic_tags FROM event_index "
            "WHERE target_id = ? AND stage IN (?, ?, ?) "
            "AND published_at >= date('now', ? || ' days') "
            "AND topic_tags IS NOT NULL AND topic_tags != ''",
            [target_id, *_ANALYSIS_STAGES, f"-{days}"],
        ) as cursor:
            rows = await cursor.fetchall()
        topic_counts: dict[str, int] = {}
        for (tags_str,) in rows:
            for tag in tags_str.split(","):
                tag = tag.strip()
                if tag:
                    topic_counts[tag] = topic_counts.get(tag, 0) + 1
        sorted_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)[:limit]
        return [{"topic": t, "count": c} for t, c in sorted_topics]

    # ------------------------------------------------------------------
    # Smart Alerts (Phase 38)
    # ------------------------------------------------------------------

    async def get_recent_links(
        self,
        target_id: str,
        hours: int = 24,
        limit: int = 500,
        since_run_started_at: str | datetime | None = None,
    ) -> list[dict[str, Any]]:
        """获取最近 N 小时新增的 event_links。"""
        if self._db is None:
            return []
        params: list[Any] = [target_id, f"-{hours}"]
        if since_run_started_at is not None:
            params.append(self._sqlite_datetime(since_run_started_at))
            query = (
                "SELECT el.source_event_id, el.target_event_id, el.link_type, "
                "el.strength, el.target_id, ei.title_original "
                "FROM event_links el "
                "LEFT JOIN event_index ei ON ei.event_id = el.target_event_id "
                "WHERE el.target_id = ? "
                "AND el.created_at >= datetime('now', ? || ' hours') "
                "AND el.created_at >= ? "
                "ORDER BY el.created_at DESC LIMIT ?"
            )
        else:
            query = (
                "SELECT el.source_event_id, el.target_event_id, el.link_type, "
                "el.strength, el.target_id, ei.title_original "
                "FROM event_links el "
                "LEFT JOIN event_index ei ON ei.event_id = el.target_event_id "
                "WHERE el.target_id = ? "
                "AND el.created_at >= datetime('now', ? || ' hours') "
                "ORDER BY el.created_at DESC LIMIT ?"
            )
        params.append(max(1, int(limit)))
        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        cols = (
            "source_event_id",
            "target_event_id",
            "link_type",
            "strength",
            "target_id",
            "title_original",
        )
        return [dict(zip(cols, row, strict=True)) for row in rows]

    @staticmethod
    def _sqlite_datetime(value: str | datetime) -> str:
        """把 ISO/datetime 时间归一成 SQLite datetime('now') 同格式。"""
        if isinstance(value, datetime):
            parsed = value
        else:
            text = str(value)
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return text.replace("T", " ")[:19]
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(UTC).replace(tzinfo=None)
        return parsed.strftime("%Y-%m-%d %H:%M:%S")

    async def get_entity_daily_mentions(
        self, entity_name: str, target_id: str, days: int = 7
    ) -> list[dict[str, Any]]:
        """获取某实体在每天中的提及次数。"""
        if self._db is None:
            return []
        pattern = f"%,{entity_name},%"
        async with self._db.execute(
            "SELECT date(published_at) AS day, COUNT(*) AS cnt "
            "FROM event_index "
            "WHERE target_id = ? AND stage IN (?, ?, ?) "
            "AND published_at >= date('now', ? || ' days') "
            "AND ',' || entity_names || ',' LIKE ? "
            "GROUP BY day ORDER BY day",
            [target_id, *_ANALYSIS_STAGES, f"-{days}", pattern],
        ) as cursor:
            rows = await cursor.fetchall()
        return [{"day": r[0], "count": r[1]} for r in rows]

    # ------------------------------------------------------------------
    # Dashboard Enhancement (Phase 39)
    # ------------------------------------------------------------------

    async def get_today_stats(self, target_id: str) -> dict[str, Any]:
        """获取今日 vs 昨日对比统计。"""
        empty = {
            "today_count": 0,
            "today_avg_score": None,
            "today_max_score": None,
            "yesterday_count": 0,
            "yesterday_avg_score": None,
        }
        if self._db is None:
            return empty

        # 今日统计
        async with self._db.execute(
            "SELECT COUNT(*), AVG(news_value_score), MAX(news_value_score) "
            "FROM event_index WHERE target_id = ? AND stage IN (?, ?, ?) "
            "AND date(published_at) = date('now')",
            [target_id, *_ANALYSIS_STAGES],
        ) as cursor:
            row = await cursor.fetchone()
        today_count = row[0] if row else 0
        today_avg = row[1] if row and row[1] is not None else None
        today_max = row[2] if row and row[2] is not None else None

        # 昨日统计
        async with self._db.execute(
            "SELECT COUNT(*), AVG(news_value_score) "
            "FROM event_index WHERE target_id = ? AND stage IN (?, ?, ?) "
            "AND date(published_at) = date('now', '-1 day')",
            [target_id, *_ANALYSIS_STAGES],
        ) as cursor:
            row = await cursor.fetchone()
        yesterday_count = row[0] if row else 0
        yesterday_avg = row[1] if row and row[1] is not None else None

        return {
            "today_count": today_count,
            "today_avg_score": round(today_avg, 1) if today_avg is not None else None,
            "today_max_score": today_max,
            "yesterday_count": yesterday_count,
            "yesterday_avg_score": round(yesterday_avg, 1) if yesterday_avg is not None else None,
        }

    async def get_top_events(
        self, target_id: str, days: int = 7, limit: int = 5
    ) -> list[dict[str, Any]]:
        """获取最近 N 天最高分事件。"""
        if self._db is None:
            return []
        async with self._db.execute(
            "SELECT event_id, title_original, news_value_score, source_id, published_at "
            "FROM event_index "
            "WHERE target_id = ? AND stage IN (?, ?, ?) "
            "AND published_at >= date('now', ? || ' days') "
            "ORDER BY news_value_score DESC LIMIT ?",
            [target_id, *_ANALYSIS_STAGES, f"-{days}", limit],
        ) as cursor:
            rows = await cursor.fetchall()
        cols = ("event_id", "title_original", "news_value_score", "source_id", "published_at")
        return [dict(zip(cols, row, strict=True)) for row in rows]

    # ------------------------------------------------------------------
    # Governance / Maintenance (Phase 40)
    # ------------------------------------------------------------------

    async def prune_old_data(self, target_id: str, max_age_days: int = 30) -> dict[str, int]:
        """清理过期数据：事件、孤儿 links、旧 known_ids。"""
        result: dict[str, int] = {
            "deleted_events": 0,
            "deleted_links": 0,
            "deleted_ids": 0,
        }
        if self._db is None:
            return result

        cutoff = f"-{max_age_days}"

        # 1. 删除过期事件
        async with self._db.execute(
            "SELECT COUNT(*) FROM event_index "
            "WHERE target_id = ? AND created_at < date('now', ? || ' days')",
            [target_id, cutoff],
        ) as cursor:
            row = await cursor.fetchone()
        result["deleted_events"] = row[0] if row else 0
        if result["deleted_events"] > 0:
            await self._db.execute(
                "DELETE FROM event_index "
                "WHERE target_id = ? AND created_at < date('now', ? || ' days')",
                [target_id, cutoff],
            )

        # 2. 删除孤儿 links（source_event_id 不在 event_index 中）
        async with self._db.execute(
            "SELECT COUNT(*) FROM event_links "
            "WHERE target_id = ? "
            "AND source_event_id NOT IN (SELECT event_id FROM event_index)",
            [target_id],
        ) as cursor:
            row = await cursor.fetchone()
        result["deleted_links"] = row[0] if row else 0
        if result["deleted_links"] > 0:
            await self._db.execute(
                "DELETE FROM event_links "
                "WHERE target_id = ? "
                "AND source_event_id NOT IN (SELECT event_id FROM event_index)",
                [target_id],
            )

        # 3. 清理旧 known_ids
        result["deleted_ids"] = await self.prune_old_ids(max_age_days)

        await self._db.commit()
        return result

    async def backup_db(self, backup_dir: Path) -> Path:
        """备份数据库到指定目录。"""
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"state_{timestamp}.db"

        if self._db is not None:
            await self._db.commit()
            with sqlite3.connect(backup_path) as target:
                await self._db.backup(target)

        # 清理旧备份（保留最近 7 个）
        backups = sorted(backup_dir.glob("state_*.db"))
        if len(backups) > 7:
            for old_backup in backups[:-7]:
                old_backup.unlink(missing_ok=True)

        return backup_path

    # ------------------------------------------------------------------
    # Feedback + Alert History (Phase 41)
    # ------------------------------------------------------------------

    async def save_feedback(
        self,
        target_id: str,
        event_id: str,
        verdict_type: str,
        comment: str = "",
        original_recommendation: str | None = None,
        keywords_matched: list[str] | None = None,
        source_id: str | None = None,
    ) -> int:
        """保存人工反馈，返回记录 ID。"""
        if self._db is None:
            return 0
        async with self._db.execute(
            """INSERT INTO feedback
               (event_id, target_id, verdict_type, original_recommendation,
                comment, keywords_matched, source_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                target_id,
                verdict_type,
                original_recommendation,
                comment or None,
                json.dumps(keywords_matched) if keywords_matched else None,
                source_id,
            ),
        ) as cursor:
            await self._db.commit()
            return cursor.lastrowid or 0

    async def get_feedback(self, target_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """获取反馈列表。"""
        if self._db is None:
            return []
        self._db.row_factory = aiosqlite.Row
        async with self._db.execute(
            """SELECT id, event_id, target_id, verdict_type,
                      original_recommendation, comment, keywords_matched,
                      source_id, created_at
               FROM feedback
               WHERE target_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (target_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
        self._db.row_factory = None
        return [dict(r) for r in rows]

    async def get_feedback_stats(self, target_id: str) -> dict[str, int]:
        """获取反馈统计。"""
        if self._db is None:
            return {"total": 0, "publish_override": 0, "archive_override": 0, "comment": 0}
        self._db.row_factory = aiosqlite.Row
        async with self._db.execute(
            """SELECT verdict_type, COUNT(*) as cnt
               FROM feedback WHERE target_id = ?
               GROUP BY verdict_type""",
            (target_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        self._db.row_factory = None
        counts = {r["verdict_type"]: r["cnt"] for r in rows}
        return {
            "total": sum(counts.values()),
            "publish_override": counts.get("publish_override", 0),
            "archive_override": counts.get("archive_override", 0),
            "comment": counts.get("comment", 0),
        }

    async def save_alert_history(self, target_id: str, alerts: list[dict[str, Any]]) -> int:
        """批量保存告警记录，返回插入数量。"""
        if not alerts or self._db is None:
            return 0
        rows = []
        for alert in alerts:
            details = alert.get("details", {})
            rows.append(
                (
                    target_id,
                    str(alert.get("alert_key") or self._alert_history_key(target_id, alert)),
                    alert["type"],
                    alert["severity"],
                    alert["message"],
                    json.dumps(details, ensure_ascii=False, sort_keys=True),
                )
            )
        cursor = await self._db.executemany(
            """INSERT OR IGNORE INTO alert_history
               (target_id, alert_key, alert_type, severity, message, details)
               VALUES (?, ?, ?, ?, ?, ?)""",
            rows,
        )
        await self._db.commit()
        return max(int(cursor.rowcount or 0), 0)

    @staticmethod
    def _alert_history_key(target_id: str, alert: dict[str, Any]) -> str:
        """计算告警历史幂等键。"""
        details = json.dumps(
            alert.get("details", {}),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return ":".join(
            [
                target_id,
                str(alert.get("type") or ""),
                str(alert.get("severity") or ""),
                details,
            ]
        )

    async def get_alert_history(self, target_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """获取历史告警。"""
        if self._db is None:
            return []
        self._db.row_factory = aiosqlite.Row
        async with self._db.execute(
            """SELECT id, target_id, alert_key, alert_type, severity,
                      message, details, created_at
               FROM alert_history
               WHERE target_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (target_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
        self._db.row_factory = None
        return [dict(r) for r in rows]

    async def get_event_by_id(self, target_id: str, event_id: str) -> dict[str, Any] | None:
        """根据 event_id 查找事件详情。"""
        if self._db is None:
            return None
        self._db.row_factory = aiosqlite.Row
        async with self._db.execute(
            """SELECT event_id, target_id, stage, source_id,
                      news_value_score, china_relevance, classification_l0,
                      title_original, published_at, file_path, sentiment,
                      entity_names, topic_tags, created_at
               FROM event_index
               WHERE target_id = ? AND event_id = ?""",
            (target_id, event_id),
        ) as cursor:
            row = await cursor.fetchone()
        self._db.row_factory = None
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    async def get_user(self, username: str) -> dict[str, Any] | None:
        """获取用户信息。"""
        if self._db is None:
            return None
        self._db.row_factory = aiosqlite.Row
        async with self._db.execute(
            "SELECT username, password_hash, salt, role, api_key, must_change_pw, "
            "       created_at, updated_at FROM users WHERE username = ?",
            (username,),
        ) as cursor:
            row = await cursor.fetchone()
        self._db.row_factory = None
        return dict(row) if row else None

    async def create_user(
        self,
        username: str,
        password_hash: str,
        salt: str,
        role: str = "admin",
        api_key: str | None = None,
        must_change_pw: int = 0,
    ) -> bool:
        """创建用户，返回是否成功。"""
        if self._db is None:
            return False
        now = datetime.now(UTC).isoformat()
        try:
            await self._db.execute(
                "INSERT INTO users (username, password_hash, salt, role, api_key, "
                "                   must_change_pw, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (username, password_hash, salt, role, api_key, must_change_pw, now, now),
            )
            await self._db.commit()
            return True
        except Exception:
            return False

    async def update_user_password(self, username: str, password_hash: str, salt: str) -> bool:
        """更新用户密码。"""
        if self._db is None:
            return False
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            "UPDATE users SET password_hash = ?, salt = ?, must_change_pw = 0, "
            "                 updated_at = ? WHERE username = ?",
            (password_hash, salt, now, username),
        )
        await self._db.commit()
        return self._db.total_changes > 0

    async def update_user_api_key(self, username: str, api_key: str | None) -> bool:
        """更新用户的 API Key。"""
        if self._db is None:
            return False
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            "UPDATE users SET api_key = ?, updated_at = ? WHERE username = ?",
            (api_key, now, username),
        )
        await self._db.commit()
        return self._db.total_changes > 0

    async def list_users(self) -> list[dict[str, Any]]:
        """列出所有用户。"""
        if self._db is None:
            return []
        self._db.row_factory = aiosqlite.Row
        async with self._db.execute(
            "SELECT username, role, api_key, must_change_pw, created_at, updated_at FROM users"
        ) as cursor:
            rows = await cursor.fetchall()
        self._db.row_factory = None
        return [dict(r) for r in rows]

    async def delete_user(self, username: str) -> bool:
        """删除用户。"""
        if self._db is None:
            return False
        await self._db.execute("DELETE FROM users WHERE username = ?", (username,))
        await self._db.commit()
        return self._db.total_changes > 0

    # ------------------------------------------------------------------
    # Sessions — Token 持久化
    # ------------------------------------------------------------------

    async def create_session(
        self, token: str, username: str, role: str, has_api_key: bool, ttl: float
    ) -> None:
        """创建或刷新 session token。"""
        if self._db is None:
            return
        import hashlib

        token_hash = hashlib.sha256(token.encode()).hexdigest()
        now = time.time()
        await self._db.execute(
            "INSERT OR REPLACE INTO sessions (token_hash, username, role, has_api_key, "
            "        created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
            (token_hash, username, role, int(has_api_key), now, now + ttl),
        )
        await self._db.commit()

    async def get_session(self, token: str) -> dict[str, Any] | None:
        """根据 token 查询 session。"""
        if self._db is None:
            return None
        import hashlib

        token_hash = hashlib.sha256(token.encode()).hexdigest()
        self._db.row_factory = aiosqlite.Row
        async with self._db.execute(
            "SELECT username, role, has_api_key, created_at, expires_at "
            "FROM sessions WHERE token_hash = ?",
            (token_hash,),
        ) as cursor:
            row = await cursor.fetchone()
        self._db.row_factory = None
        if row is None:
            return None
        info = dict(row)
        info["has_api_key"] = bool(info["has_api_key"])
        return info

    async def delete_session(self, token: str) -> bool:
        """删除单个 session。"""
        if self._db is None:
            return False
        import hashlib

        token_hash = hashlib.sha256(token.encode()).hexdigest()
        await self._db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
        await self._db.commit()
        return self._db.total_changes > 0

    async def delete_expired_sessions(self) -> int:
        """清理过期 session，返回删除数。"""
        if self._db is None:
            return 0
        cur = await self._db.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))
        await self._db.commit()
        return cur.rowcount

    async def list_active_sessions(self) -> list[dict[str, Any]]:
        """列出所有未过期的 session。"""
        if self._db is None:
            return []
        self._db.row_factory = aiosqlite.Row
        async with self._db.execute(
            "SELECT username, role, has_api_key, created_at, expires_at "
            "FROM sessions WHERE expires_at >= ?",
            (time.time(),),
        ) as cursor:
            rows = await cursor.fetchall()
        self._db.row_factory = None
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Notifications — 通知设置持久化（替代 notifications.json）
    # ------------------------------------------------------------------

    async def get_notifications(self) -> dict[str, Any]:
        """获取通知设置，不存在则返回空 dict。"""
        if self._db is None:
            return {}
        async with self._db.execute("SELECT config FROM notifications WHERE id = 1") as cursor:
            row = await cursor.fetchone()
        if row is None:
            return {}
        try:
            return json.loads(row[0])  # type: ignore[no-any-return]
        except (json.JSONDecodeError, TypeError):
            return {}

    async def save_notifications(self, config: dict[str, Any]) -> None:
        """写入通知设置。"""
        if self._db is None:
            return
        config_json = json.dumps(config, ensure_ascii=False)
        await self._db.execute(
            "INSERT OR REPLACE INTO notifications (id, config) VALUES (1, ?)",
            (config_json,),
        )
        await self._db.commit()
