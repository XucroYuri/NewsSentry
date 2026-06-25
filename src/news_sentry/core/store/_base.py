"""AsyncStore 基础层：数据库连接、初始化、迁移、工具方法。

此文件从 async_store.py 自动拆分，包含：
- AsyncStoreBase 类定义（__init__, initialize, _migrate_schema, close）
- 工具方法（_json_dumps, _json_loads, _safe_text_attr, _safe_metadata_attr 等）
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from news_sentry.core.public_translation import public_publication_ready_for_row
from news_sentry.core.store._ddl import (
    _CANONICAL_GRAPH_OPERATION_COLUMNS,
    _DDL_AI_ENRICHMENT_EVENTS,
    _DDL_AI_ENRICHMENT_USAGE,
    _DDL_ALERT_HISTORY,
    _DDL_CHAIN_NARRATIVES,
    _DDL_CURSORS,
    _DDL_ENTITIES,
    _DDL_ENTITY_EVENT_ANNOTATIONS,
    _DDL_ENTITY_EVENT_MENTIONS,
    _DDL_ENTITY_FTS,
    _DDL_ENTITY_FTS_TRIGGERS,
    _DDL_EVENT_INDEX,
    _DDL_EVENT_INDEX_FTS,
    _DDL_EVENT_LINKS,
    _DDL_FEEDBACK,
    _DDL_FTS_TRIGGERS,
    _DDL_INDEXES,
    _DDL_KNOWN_IDS,
    _DDL_LLM_CACHE,
    _DDL_NOTIFICATION_RULES,
    _DDL_NOTIFICATIONS,
    _DDL_SCHEMA_VERSION,
    _DDL_SESSIONS,
    _DDL_SOURCE_HEALTH,
    _DDL_USERS,
    _PRAGMA_SETUP,
    _RESEARCH_ARTIFACT_COLUMNS,
    _SCHEMA_MIGRATIONS,
)

logger = logging.getLogger(__name__)


class AsyncStoreBase:
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
        await self._db.execute(_DDL_ENTITY_EVENT_MENTIONS)
        await self._db.execute(_DDL_ENTITY_EVENT_ANNOTATIONS)
        await self._db.execute(_DDL_EVENT_LINKS)
        await self._db.execute(_DDL_CHAIN_NARRATIVES)
        await self._db.execute(_DDL_FEEDBACK)
        await self._db.execute(_DDL_ALERT_HISTORY)
        await self._db.execute(_DDL_USERS)
        await self._db.execute(_DDL_SESSIONS)
        await self._db.execute(_DDL_NOTIFICATIONS)
        await self._db.execute(_DDL_AI_ENRICHMENT_USAGE)
        await self._db.execute(_DDL_AI_ENRICHMENT_EVENTS)
        await self._db.execute(_DDL_NOTIFICATION_RULES)
        await self._db.execute(_DDL_SCHEMA_VERSION)
        await self._migrate_schema()

        # FTS5 全文搜索虚拟表 + 触发器
        await self._db.execute(_DDL_EVENT_INDEX_FTS)
        for trigger_sql in _DDL_FTS_TRIGGERS:
            try:
                await self._db.execute(trigger_sql)
            except Exception:
                logger.debug("FTS5 trigger already exists, skipping", exc_info=True)

        # 实体 FTS5 索引 + 触发器
        await self._db.execute(_DDL_ENTITY_FTS)
        for trigger_sql in _DDL_ENTITY_FTS_TRIGGERS:
            try:
                await self._db.execute(trigger_sql)
            except Exception:
                logger.debug("Entity FTS5 trigger already exists, skipping", exc_info=True)

        await self._refresh_public_translation_readiness()
        await self._cleanup_duplicate_canonical_graph_operation_artifacts()
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

    async def _cleanup_duplicate_canonical_graph_operation_artifacts(self) -> None:
        """Remove legacy duplicate artifact operation rows before adding the unique index."""
        assert self._db is not None
        await self._db.execute(
            """DELETE FROM canonical_graph_operations
               WHERE decision_artifact_id IS NOT NULL
                 AND rowid IN (
                     SELECT rowid
                     FROM (
                         SELECT rowid,
                                ROW_NUMBER() OVER (
                                    PARTITION BY target_id, decision_artifact_id
                                    ORDER BY created_at ASC, operation_id ASC, rowid ASC
                                ) AS duplicate_rank
                         FROM canonical_graph_operations
                         WHERE decision_artifact_id IS NOT NULL
                     )
                     WHERE duplicate_rank > 1
                 )"""
        )

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None
            logger.info("AsyncStore 连接已关闭: %s", self._db_path)

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:
        """返回当前 AsyncStore 连接，供底层存储测试和内部查询复用。"""
        yield await self._ensure_db()

    async def _ensure_db(self) -> aiosqlite.Connection:
        if self._db is None:
            await self.initialize()
        assert self._db is not None
        return self._db

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

    def _deep_merge_dict(self, base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        merged = dict(base)
        for key, value in patch.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = self._deep_merge_dict(merged[key], value)
            else:
                merged[key] = value
        return merged

    def _row_with_metadata(self, columns: tuple[str, ...], row: Any) -> dict[str, Any]:  # noqa: ANN401
        item = dict(zip(columns, row, strict=True))
        item["metadata"] = self._json_loads(item.pop("metadata_json", None))
        return item

    def _publication_ready_from_index_row(self, row: dict[str, Any]) -> int:
        return 1 if public_publication_ready_for_row(row) else 0

    def _publication_row_from_event(
        self,
        event: object,
        target_id: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "gid": getattr(event, "gid", ""),
            "event_id": getattr(event, "id", ""),
            "target_id": target_id,
            "title_original": getattr(event, "title_original", None),
            "content_original": getattr(event, "content_original", None),
            "description": getattr(event, "description", None),
            "metadata": metadata,
        }

    async def _refresh_public_translation_readiness(self) -> None:
        assert self._db is not None
        try:
            rows = await self._db.execute_fetchall(
                "SELECT gid, event_id, target_id, title_original, metadata_json FROM event_index"
            )
        except sqlite3.OperationalError:
            return
        for _gid, event_id, target_id, title_original, metadata_json in rows:
            ready = self._publication_ready_from_index_row(
                {
                    "event_id": event_id,
                    "target_id": target_id,
                    "title_original": title_original,
                    "metadata": self._json_loads(metadata_json),
                }
            )
            await self._db.execute(
                "UPDATE event_index SET public_translation_ready = ? "
                "WHERE target_id = ? AND event_id = ?",
                (ready, target_id, event_id),
            )

    def _research_artifact_from_row(self, row: Sequence[Any]) -> dict[str, Any]:
        artifact = self._row_with_metadata(_RESEARCH_ARTIFACT_COLUMNS, row)
        raw_ids = artifact.pop("canonical_event_ids_json", "[]")
        try:
            canonical_event_ids = json.loads(raw_ids or "[]")
        except (json.JSONDecodeError, TypeError):
            canonical_event_ids = []
        artifact["canonical_event_ids"] = (
            canonical_event_ids if isinstance(canonical_event_ids, list) else []
        )
        return artifact

    def _canonical_graph_operation_from_row(self, row: Sequence[Any]) -> dict[str, Any]:
        operation = self._row_with_metadata(_CANONICAL_GRAPH_OPERATION_COLUMNS, row)
        for field_name in ("changes", "warnings"):
            raw_value = operation.pop(f"{field_name}_json", "[]")
            try:
                parsed = json.loads(raw_value or "[]")
            except (json.JSONDecodeError, TypeError):
                parsed = []
            operation[field_name] = parsed if isinstance(parsed, list) else []
        return operation

    @staticmethod
    def _safe_text_attr(event: object, attr: str) -> str | None:
        value = getattr(event, attr, None)
        return value if isinstance(value, str) else None

    @staticmethod
    def _safe_metadata_attr(event: object) -> dict[str, Any]:
        value = getattr(event, "metadata", {})
        return value if isinstance(value, dict) else {}

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

    # ------------------------------------------------------------------
