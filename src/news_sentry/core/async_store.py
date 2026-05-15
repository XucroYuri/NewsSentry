"""AsyncStore — SQLite 存储层，替代 Memory 的 YAML 全量序列化。"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

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
    published_at      TEXT,
    file_path         TEXT,
    created_at        TEXT NOT NULL
)
"""

_DDL_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_known_ids_seen ON known_ids(seen_at)",
    "CREATE INDEX IF NOT EXISTS idx_event_target_stage ON event_index(target_id, stage)",
    "CREATE INDEX IF NOT EXISTS idx_event_published ON event_index(published_at DESC)",
)

__all__ = ["AsyncStore"]


class AsyncStore:
    """异步 SQLite 存储层。"""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

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
        for idx_sql in _DDL_INDEXES:
            await self._db.execute(idx_sql)
        await self._db.commit()
        logger.info("AsyncStore 初始化完成: %s", self._db_path)

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None
            logger.info("AsyncStore 连接已关闭: %s", self._db_path)

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

    async def index_event(
        self,
        event: object,
        target_id: str,
        stage: str,
        file_path: str | None = None,
    ) -> None:
        if self._db is None:
            return
        classification = (
            event.metadata.get("classification", {}) if hasattr(event, "metadata") else {}
        )
        classification_l0 = classification.get("l0") if isinstance(classification, dict) else None
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            """INSERT OR REPLACE INTO event_index
               (event_id, target_id, stage, source_id, news_value_score,
                china_relevance, classification_l0, title_original,
                published_at, file_path, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(
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
                getattr(event, "published_at", None),
                file_path,
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
                      published_at, file_path, created_at
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
        )
        return [dict(zip(cols, row, strict=True)) for row in rows]

    async def get_event_count(self, target_id: str, stage: str) -> int:
        if self._db is None:
            return 0
        async with self._db.execute(
            "SELECT COUNT(*) FROM event_index WHERE target_id = ? AND stage = ?",
            (target_id, stage),
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
