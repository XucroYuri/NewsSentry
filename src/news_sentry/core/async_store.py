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
        await self._db.execute(_DDL_ENTITIES)
        await self._db.execute(_DDL_EVENT_LINKS)
        await self._db.execute(_DDL_CHAIN_NARRATIVES)
        # Phase 31: 为已有数据库添加 NLP 列
        for col in ("sentiment", "entity_names", "topic_tags"):
            try:
                await self._db.execute(
                    f"ALTER TABLE event_index ADD COLUMN {col} TEXT"  # noqa: S608
                )
            except Exception:  # noqa: S110
                pass  # 列已存在
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
        classification = (
            event.metadata.get("classification", {}) if hasattr(event, "metadata") else {}
        )
        classification_l0 = classification.get("l0") if isinstance(classification, dict) else None
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            """INSERT OR REPLACE INTO event_index
               (event_id, target_id, stage, source_id, news_value_score,
                china_relevance, classification_l0, title_original,
                published_at, file_path, sentiment, entity_names, topic_tags,
                created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(
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
            conditions.append("classification_l0 = ?")
            params.append(classification_l0)
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
                    "classification_l0": r[4],
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

        by_classification: dict[str, int] = {}
        async with self._db.execute(
            "SELECT classification_l0, COUNT(*) FROM event_index "
            "WHERE target_id = ? AND classification_l0 IS NOT NULL "
            "GROUP BY classification_l0",
            [target_id],
        ) as cursor:
            async for row in cursor:
                by_classification[row[0]] = row[1]

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
    ) -> list[dict[str, Any]]:
        """查找同一 target 最近 N 天的候选关联事件（排除自身）。"""
        if self._db is None:
            return []
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        async with self._db.execute(
            "SELECT event_id, entity_names, topic_tags, published_at, title_original "
            "FROM event_index WHERE target_id = ? AND event_id != ? "
            "AND published_at >= ? ORDER BY published_at DESC",
            [target_id, event_id, cutoff],
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
            "WHERE target_id = ? AND stage = 'judged' "
            "AND published_at >= date('now', ? || ' days') "
            "AND sentiment IS NOT NULL "
            "GROUP BY day, sentiment ORDER BY day",
            [target_id, f"-{days}"],
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
            "WHERE target_id = ? AND stage = 'judged' "
            "AND published_at >= date('now', ? || ' days') "
            "AND topic_tags IS NOT NULL AND topic_tags != ''",
            [target_id, f"-{days}"],
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
            "WHERE target_id = ? AND stage = 'judged' "
            "AND published_at >= date('now', ? || ' days') "
            "AND topic_tags IS NOT NULL AND topic_tags != ''",
            [target_id, f"-{days}"],
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

    async def get_recent_links(self, target_id: str, hours: int = 24) -> list[dict[str, Any]]:
        """获取最近 N 小时新增的 event_links。"""
        if self._db is None:
            return []
        async with self._db.execute(
            "SELECT el.source_event_id, el.target_event_id, el.link_type, "
            "el.strength, el.target_id, ei.title_original "
            "FROM event_links el "
            "LEFT JOIN event_index ei ON ei.event_id = el.target_event_id "
            "WHERE el.target_id = ? "
            "AND el.created_at >= datetime('now', ? || ' hours') "
            "ORDER BY el.created_at DESC",
            [target_id, f"-{hours}"],
        ) as cursor:
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
            "WHERE target_id = ? AND stage = 'judged' "
            "AND published_at >= date('now', ? || ' days') "
            "AND ',' || entity_names || ',' LIKE ? "
            "GROUP BY day ORDER BY day",
            [target_id, f"-{days}", pattern],
        ) as cursor:
            rows = await cursor.fetchall()
        return [{"day": r[0], "count": r[1]} for r in rows]
