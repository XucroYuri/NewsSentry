"""Tests for core/async_store.py — AsyncStore SQLite 存储层。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from news_sentry.core.async_store import AsyncStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def store(tmp_path: Path) -> AsyncStore:
    """创建并初始化 AsyncStore，测试结束后自动关闭。"""
    db_path = tmp_path / "state.db"
    s = AsyncStore(db_path)
    await s.initialize()
    yield s
    await s.close()


# ---------------------------------------------------------------------------
# TestAsyncStoreInitialize
# ---------------------------------------------------------------------------


class TestAsyncStoreInitialize:
    """AsyncStore 初始化、Schema 建表、PRAGMA 设置。"""

    @pytest.mark.asyncio
    async def test_initialize_creates_db_file(self, tmp_path: Path):
        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()
        assert db_path.exists()
        await store.close()

    @pytest.mark.asyncio
    async def test_initialize_creates_all_tables(self, tmp_path: Path):
        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()
        async with store._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ) as cursor:
            rows = await cursor.fetchall()
        table_names = {row[0] for row in rows}
        expected = {"known_ids", "source_health", "cursors", "llm_cache", "event_index"}
        assert expected.issubset(table_names), f"Missing tables: {expected - table_names}"
        await store.close()

    @pytest.mark.asyncio
    async def test_initialize_creates_indexes(self, tmp_path: Path):
        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()
        async with store._db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name"
        ) as cursor:
            rows = await cursor.fetchall()
        index_names = {row[0] for row in rows}
        expected = {"idx_known_ids_seen", "idx_event_target_stage", "idx_event_published"}
        assert expected.issubset(index_names), f"Missing indexes: {expected - index_names}"
        await store.close()

    @pytest.mark.asyncio
    async def test_initialize_is_idempotent(self, tmp_path: Path):
        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()
        await store.initialize()
        await store.close()

    @pytest.mark.asyncio
    async def test_pragma_wal_mode(self, tmp_path: Path):
        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()
        async with store._db.execute("PRAGMA journal_mode") as cursor:
            row = await cursor.fetchone()
        assert row is not None and row[0].lower() == "wal"
        await store.close()

    @pytest.mark.asyncio
    async def test_close_closes_connection(self, tmp_path: Path):
        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()
        await store.close()
        with pytest.raises(AttributeError):
            await store._db.execute("SELECT 1")


# ---------------------------------------------------------------------------
# TestKnownIds
# ---------------------------------------------------------------------------


class TestKnownIds:
    """known_ids 表 CRUD 操作。"""

    @pytest.mark.asyncio
    async def test_is_known_returns_false_for_new_id(self, store: AsyncStore):
        assert await store.is_known("evt-new-001") is False

    @pytest.mark.asyncio
    async def test_mark_known_and_is_known(self, store: AsyncStore):
        await store.mark_known("evt-001")
        assert await store.is_known("evt-001") is True

    @pytest.mark.asyncio
    async def test_mark_known_is_idempotent(self, store: AsyncStore):
        await store.mark_known("evt-002")
        await store.mark_known("evt-002")
        assert await store.is_known("evt-002") is True

    @pytest.mark.asyncio
    async def test_mark_known_persists_across_instances(self, tmp_path: Path):
        db_path = tmp_path / "state.db"
        store1 = AsyncStore(db_path)
        await store1.initialize()
        await store1.mark_known("evt-persist-001")
        await store1.close()

        store2 = AsyncStore(db_path)
        await store2.initialize()
        assert await store2.is_known("evt-persist-001") is True
        await store2.close()

    @pytest.mark.asyncio
    async def test_prune_old_ids_removes_stale_entries(self, tmp_path: Path):
        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()

        # 手动插入一条过期的 known_id
        stale_time = (datetime.now(UTC) - timedelta(days=60)).isoformat()
        await store._db.execute(
            "INSERT INTO known_ids (event_id, seen_at) VALUES (?, ?)",
            ("stale-evt", stale_time),
        )
        await store._db.commit()

        # 插入一条新鲜的
        await store.mark_known("fresh-evt")

        pruned = await store.prune_old_ids(max_age_days=30)
        assert pruned == 1
        assert await store.is_known("stale-evt") is False
        assert await store.is_known("fresh-evt") is True
        await store.close()

    @pytest.mark.asyncio
    async def test_prune_old_ids_returns_zero_when_no_stale(self, store: AsyncStore):
        await store.mark_known("evt-recent")
        pruned = await store.prune_old_ids(max_age_days=30)
        assert pruned == 0

    @pytest.mark.asyncio
    async def test_concurrent_mark_known(self, store: AsyncStore):
        ids = [f"concurrent-{i}" for i in range(20)]
        await asyncio.gather(*(store.mark_known(eid) for eid in ids))
        for eid in ids:
            assert await store.is_known(eid) is True


# ---------------------------------------------------------------------------
# TestSourceHealth
# ---------------------------------------------------------------------------


class TestSourceHealth:
    """source_health 表 CRUD 操作。"""

    @pytest.mark.asyncio
    async def test_get_source_health_returns_none_for_unknown(self, store: AsyncStore):
        assert await store.get_source_health("unknown-src") is None

    @pytest.mark.asyncio
    async def test_record_source_health_success(self, store: AsyncStore):
        await store.record_source_health("src-1", "healthy", error_count=0)
        health = await store.get_source_health("src-1")
        assert health is not None
        assert health["status"] == "healthy"
        assert health["error_count"] == 0

    @pytest.mark.asyncio
    async def test_record_source_health_failure(self, store: AsyncStore):
        await store.record_source_health("src-2", "error", error_count=3)
        health = await store.get_source_health("src-2")
        assert health is not None
        assert health["status"] == "error"
        assert health["error_count"] == 3

    @pytest.mark.asyncio
    async def test_record_source_health_accumulates_errors(self, store: AsyncStore):
        await store.record_source_health("src-3", "error", error_count=1)
        await store.record_source_health("src-3", "error", error_count=2)
        health = await store.get_source_health("src-3")
        assert health is not None
        assert health["error_count"] == 2

    @pytest.mark.asyncio
    async def test_record_source_health_resets_on_success(self, store: AsyncStore):
        await store.record_source_health("src-4", "error", error_count=5)
        await store.record_source_health("src-4", "healthy", error_count=0)
        health = await store.get_source_health("src-4")
        assert health is not None
        assert health["status"] == "healthy"
        assert health["error_count"] == 0

    @pytest.mark.asyncio
    async def test_source_health_persists(self, tmp_path: Path):
        db_path = tmp_path / "state.db"
        store1 = AsyncStore(db_path)
        await store1.initialize()
        await store1.record_source_health("src-persist", "healthy")
        await store1.close()

        store2 = AsyncStore(db_path)
        await store2.initialize()
        health = await store2.get_source_health("src-persist")
        assert health is not None
        assert health["status"] == "healthy"
        await store2.close()

    @pytest.mark.asyncio
    async def test_is_source_degraded_consecutive_failures(self, store: AsyncStore):
        await store.record_source_health("src-deg-1", "error", metadata={"consecutive_failures": 7})
        assert await store.is_source_degraded("src-deg-1") is True

    @pytest.mark.asyncio
    async def test_is_source_degraded_false_healthy(self, store: AsyncStore):
        await store.record_source_health(
            "src-deg-2", "healthy", metadata={"consecutive_failures": 0}
        )
        assert await store.is_source_degraded("src-deg-2") is False

    @pytest.mark.asyncio
    async def test_is_source_degraded_unknown_returns_false(self, store: AsyncStore):
        assert await store.is_source_degraded("nonexistent-src") is False


# ---------------------------------------------------------------------------
# TestCursors
# ---------------------------------------------------------------------------


class TestCursors:
    """cursors 表 CRUD 操作。"""

    @pytest.mark.asyncio
    async def test_get_cursor_returns_none_for_unknown(self, store: AsyncStore):
        assert await store.get_cursor("unknown-src") is None

    @pytest.mark.asyncio
    async def test_set_and_get_cursor(self, store: AsyncStore):
        await store.set_cursor("src-a", "cursor-value-123")
        result = await store.get_cursor("src-a")
        assert result == "cursor-value-123"

    @pytest.mark.asyncio
    async def test_cursor_persists(self, tmp_path: Path):
        db_path = tmp_path / "state.db"
        store1 = AsyncStore(db_path)
        await store1.initialize()
        await store1.set_cursor("src-persist", "val-abc")
        await store1.close()

        store2 = AsyncStore(db_path)
        await store2.initialize()
        assert await store2.get_cursor("src-persist") == "val-abc"
        await store2.close()

    @pytest.mark.asyncio
    async def test_set_cursor_overwrites(self, store: AsyncStore):
        await store.set_cursor("src-b", "old-cursor")
        await store.set_cursor("src-b", "new-cursor")
        assert await store.get_cursor("src-b") == "new-cursor"


# ---------------------------------------------------------------------------
# TestLLMCache
# ---------------------------------------------------------------------------


class TestLLMCache:
    """llm_cache 表 CRUD 操作。"""

    @pytest.mark.asyncio
    async def test_get_cached_response_returns_none_for_miss(self, store: AsyncStore):
        assert await store.get_cached_response("nonexistent-key") is None

    @pytest.mark.asyncio
    async def test_set_and_get_cached_response(self, store: AsyncStore):
        await store.set_cached_response("key-1", "response-data", "gpt-4")
        result = await store.get_cached_response("key-1")
        assert result == "response-data"

    @pytest.mark.asyncio
    async def test_set_cached_response_updates_timestamp(self, store: AsyncStore):
        await store.set_cached_response("key-2", "first-response", "gpt-4")
        await store.set_cached_response("key-2", "updated-response", "gpt-4o")
        result = await store.get_cached_response("key-2")
        assert result == "updated-response"

    @pytest.mark.asyncio
    async def test_evict_if_needed_removes_oldest_entries(self, store: AsyncStore):
        for i in range(5):
            await store.set_cached_response(f"evict-key-{i}", f"val-{i}", "model-a")
        evicted = await store.evict_if_needed(max_entries=3)
        assert evicted == 2
        assert await store.get_cached_response("evict-key-0") is None
        assert await store.get_cached_response("evict-key-1") is None
        assert await store.get_cached_response("evict-key-2") is not None
        assert await store.get_cached_response("evict-key-3") is not None
        assert await store.get_cached_response("evict-key-4") is not None

    @pytest.mark.asyncio
    async def test_evict_if_needed_no_op_when_under_limit(self, store: AsyncStore):
        await store.set_cached_response("under-key", "val", "model-a")
        evicted = await store.evict_if_needed(max_entries=10)
        assert evicted == 0

    @pytest.mark.asyncio
    async def test_set_cached_response_persists(self, tmp_path: Path):
        db_path = tmp_path / "state.db"
        store1 = AsyncStore(db_path)
        await store1.initialize()
        await store1.set_cached_response("persist-key", "persist-val", "model-x")
        await store1.close()

        store2 = AsyncStore(db_path)
        await store2.initialize()
        assert await store2.get_cached_response("persist-key") == "persist-val"
        await store2.close()


# ---------------------------------------------------------------------------
# TestEventIndex
# ---------------------------------------------------------------------------


class TestEventIndex:
    """event_index 表 CRUD 操作。"""

    @staticmethod
    def _make_event(
        event_id: str = "evt-idx-001",
        source_id: str = "src-rss",
        news_value_score: int = 75,
        china_relevance: int = 60,
        title_original: str = "Test title",
        published_at: str = "2026-01-15T10:00:00Z",
        classification: dict[str, Any] | None = None,
    ) -> MagicMock:
        event = MagicMock()
        event.id = event_id
        event.source_id = source_id
        event.news_value_score = news_value_score
        event.china_relevance = china_relevance
        event.title_original = title_original
        event.published_at = published_at
        if classification is not None:
            event.metadata = {"classification": classification}
        else:
            event.metadata = {"classification": {"l0": "politics"}}
        return event

    @pytest.mark.asyncio
    async def test_index_event_inserts_row(self, store: AsyncStore):
        event = self._make_event()
        await store.index_event(event, "italy", "judge")
        rows = await store.query_events("italy", "judge")
        assert len(rows) == 1
        assert rows[0]["event_id"] == "evt-idx-001"

    @pytest.mark.asyncio
    async def test_index_event_extracts_classification_l0(self, store: AsyncStore):
        event = self._make_event(classification={"l0": "economy"})
        await store.index_event(event, "italy", "judge")
        rows = await store.query_events("italy", "judge")
        assert rows[0]["classification_l0"] == "economy"

    @pytest.mark.asyncio
    async def test_index_event_upserts(self, store: AsyncStore):
        event = self._make_event(event_id="evt-upsert")
        await store.index_event(event, "italy", "judge", file_path="old.json")
        # re-index with different file_path
        await store.index_event(event, "italy", "judge", file_path="new.json")
        rows = await store.query_events("italy", "judge")
        assert len(rows) == 1
        assert rows[0]["file_path"] == "new.json"
        # created_at should be preserved
        assert rows[0]["created_at"] is not None

    @pytest.mark.asyncio
    async def test_query_events_filter_by_target_and_stage(self, store: AsyncStore):
        event_italy = self._make_event(event_id="evt-it")
        event_china = self._make_event(event_id="evt-cn")
        await store.index_event(event_italy, "italy", "judge")
        await store.index_event(event_china, "china-watch-en", "judge")

        italy_rows = await store.query_events("italy", "judge")
        assert len(italy_rows) == 1
        assert italy_rows[0]["event_id"] == "evt-it"

        china_rows = await store.query_events("china-watch-en", "judge")
        assert len(china_rows) == 1
        assert china_rows[0]["event_id"] == "evt-cn"

    @pytest.mark.asyncio
    async def test_query_events_returns_empty_for_no_match(self, store: AsyncStore):
        rows = await store.query_events("nonexistent", "judge")
        assert rows == []

    @pytest.mark.asyncio
    async def test_get_event_count(self, store: AsyncStore):
        for i in range(3):
            event = self._make_event(event_id=f"evt-cnt-{i}")
            await store.index_event(event, "italy", "judge")
        count = await store.get_event_count("italy", "judge")
        assert count == 3

    @pytest.mark.asyncio
    async def test_get_stats(self, store: AsyncStore):
        for i in range(3):
            event = self._make_event(
                event_id=f"evt-stats-{i}",
                news_value_score=80,
            )
            await store.index_event(event, "italy", "judge")
        stats = await store.get_stats("italy")
        assert stats["total_events"] == 3
        assert stats["stage_counts"].get("judge") == 3
        assert stats["avg_news_value_score"] == 80.0

    @pytest.mark.asyncio
    async def test_get_stats_empty_target(self, store: AsyncStore):
        stats = await store.get_stats("nonexistent-target")
        assert stats["total_events"] == 0
        assert stats["stage_counts"] == {}
        assert stats["avg_news_value_score"] == 0.0
