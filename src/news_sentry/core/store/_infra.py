"""AsyncStore: InfraStoreMixin 功能域。

从 async_store.py 自动拆分。
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from ._base import AsyncStoreBase

logger = logging.getLogger(__name__)
class InfraStoreMixin(AsyncStoreBase):
    # ------------------------------------------------------------------
    # Known IDs
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
    # ------------------------------------------------------------------
    # Source Health
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
    # ------------------------------------------------------------------
    # Cursors
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
    # ------------------------------------------------------------------
    # LLM Cache
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
