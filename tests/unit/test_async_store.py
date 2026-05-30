"""Tests for core/async_store.py — AsyncStore SQLite 存储层。"""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
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
    async def test_get_all_source_health(self, store: AsyncStore) -> None:
        await store.record_source_health("src_a", "healthy", error_count=0)
        await store.record_source_health(
            "src_b", "degraded", error_count=3, metadata={"last_error": "timeout"}
        )
        results = await store.get_all_source_health()
        assert len(results) == 2
        ids = {r["source_id"] for r in results}
        assert ids == {"src_a", "src_b"}
        degraded = next(r for r in results if r["source_id"] == "src_b")
        assert degraded["status"] == "degraded"
        assert degraded["error_count"] == 3

    @pytest.mark.asyncio
    async def test_get_all_source_health_empty(self, store: AsyncStore) -> None:
        results = await store.get_all_source_health()
        assert results == []

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
    async def test_index_event_ignores_mock_url_and_non_dict_metadata(
        self,
        store: AsyncStore,
    ):
        event = MagicMock()
        event.id = "evt-partial"
        event.source_id = "ansa"
        event.news_value_score = 82
        event.china_relevance = 10
        event.title_original = "Partial mock"
        event.published_at = "2026-05-30T08:00:00Z"
        event.metadata = MagicMock()

        await store.index_event(event, "italy", "judge")

        async with store._connect() as conn:
            async with conn.execute(
                "SELECT url, metadata_json FROM event_index WHERE event_id = ?",
                ("evt-partial",),
            ) as cursor:
                row = await cursor.fetchone()
        assert row is not None
        assert row[0] is None
        assert row[1] == "{}"

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
    async def test_get_target_event_count_counts_all_stages(self, store: AsyncStore):
        await store.index_event(self._make_event(event_id="evt-draft"), "italy", "drafts")
        await store.index_event(self._make_event(event_id="evt-arch"), "italy", "archive")
        await store.index_event(self._make_event(event_id="evt-other"), "japan", "drafts")

        assert await store.get_target_event_count("italy") == 2
        assert await store.get_target_event_count("japan") == 1
        assert await store.get_target_event_count("germany") == 0

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


# ---------------------------------------------------------------------------
# TestEventIndexQueries
# ---------------------------------------------------------------------------


class TestEventIndexQueries:
    """event_index 查询方法测试。"""

    @pytest.fixture
    async def store_with_events(self, tmp_path: Path) -> AsyncStore:
        """创建包含测试数据的 AsyncStore。"""
        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()

        # 插入 5 条测试事件
        now = datetime.now(UTC).isoformat()
        for i in range(5):
            await store._db.execute(  # noqa: SLF001
                "INSERT OR REPLACE INTO event_index "
                "(event_id, target_id, stage, source_id, news_value_score, "
                "china_relevance, classification_l0, published_at, file_path, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"ne-italy-src{i:04d}",
                    "italy",
                    "drafts",
                    "ansa" if i % 2 == 0 else "repubblica",
                    60 + i * 5,
                    20 + i * 3,
                    "international" if i % 2 == 0 else "politics",
                    now,
                    f"data/italy/drafts/outputted_src{i:04d}_ne-italy-src{i:04d}.md",
                    now,
                ),
            )
        await store._db.commit()  # noqa: SLF001
        return store

    @pytest.mark.asyncio
    async def test_query_events_paginated_basic(
        self,
        store_with_events: AsyncStore,
    ) -> None:
        """基本分页查询。"""
        result = await store_with_events.query_events_paginated(
            target_id="italy",
            stage="drafts",
            limit=2,
            offset=0,
        )
        assert result["total"] == 5
        assert len(result["rows"]) == 2

    @pytest.mark.asyncio
    async def test_query_events_paginated_second_page(
        self,
        store_with_events: AsyncStore,
    ) -> None:
        """第二页查询。"""
        result = await store_with_events.query_events_paginated(
            target_id="italy",
            stage="drafts",
            limit=2,
            offset=2,
        )
        assert result["total"] == 5
        assert len(result["rows"]) == 2

    @pytest.mark.asyncio
    async def test_query_events_filter_by_source(
        self,
        store_with_events: AsyncStore,
    ) -> None:
        """按 source_id 筛选。"""
        result = await store_with_events.query_events_paginated(
            target_id="italy",
            stage="drafts",
            source_id="ansa",
            limit=10,
            offset=0,
        )
        assert result["total"] == 3  # 索引 0, 2, 4

    @pytest.mark.asyncio
    async def test_query_events_filter_by_classification(
        self,
        store_with_events: AsyncStore,
    ) -> None:
        """按 classification_l0 筛选。"""
        result = await store_with_events.query_events_paginated(
            target_id="italy",
            stage="drafts",
            classification_l0="politics",
            limit=10,
            offset=0,
        )
        assert result["total"] == 2

        legacy_result = await store_with_events.query_events_paginated(
            target_id="italy",
            stage="drafts",
            classification_l0="international-relations",
            limit=10,
            offset=0,
        )
        assert legacy_result["total"] == 3

    @pytest.mark.asyncio
    async def test_query_events_filter_by_min_score(
        self,
        store_with_events: AsyncStore,
    ) -> None:
        """按最低 news_value_score 筛选。"""
        result = await store_with_events.query_events_paginated(
            target_id="italy",
            stage="drafts",
            min_score=70,
            limit=10,
            offset=0,
        )
        assert result["total"] == 3  # 75, 80, 85

    @pytest.mark.asyncio
    async def test_get_stats_aggregated(
        self,
        store_with_events: AsyncStore,
    ) -> None:
        """聚合统计查询。"""
        stats = await store_with_events.get_stats_aggregated(target_id="italy")
        assert stats["total_events"] == 5
        assert stats["avg_news_value_score"] is not None
        assert 60 <= stats["avg_news_value_score"] <= 85
        assert stats["avg_china_relevance"] is not None
        assert stats["by_classification"]["international-relations"] == 3
        assert stats["by_classification"]["politics"] == 2
        assert stats["by_source"]["ansa"] == 3
        assert stats["by_source"]["repubblica"] == 2

    @pytest.mark.asyncio
    async def test_get_stats_empty(self, tmp_path: Path) -> None:
        """空 target 统计。"""
        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()
        stats = await store.get_stats_aggregated(target_id="nonexistent")
        assert stats["total_events"] == 0
        assert stats["avg_news_value_score"] is None
        await store.close()

    @pytest.mark.asyncio
    async def test_get_event_file_path(
        self,
        store_with_events: AsyncStore,
    ) -> None:
        """根据 event_id 查找 file_path。"""
        path = await store_with_events.get_event_file_path(event_id="ne-italy-src0000")
        assert path is not None
        assert "ne-italy-src0000" in path

    @pytest.mark.asyncio
    async def test_get_event_file_path_not_found(
        self,
        store_with_events: AsyncStore,
    ) -> None:
        """不存在的 event_id 返回 None。"""
        path = await store_with_events.get_event_file_path(event_id="ne-nonexistent")
        assert path is None


# ---------------------------------------------------------------------------
# TestEntityTracking
# ---------------------------------------------------------------------------


class TestEntityTracking:
    """entities 表 CRUD 与去重。"""

    @pytest.mark.asyncio
    async def test_entities_table_created(self, tmp_path: Path):
        """entities 表在 initialize() 后存在。"""
        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()
        async with store._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='entities'"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None
        await store.close()

    @pytest.mark.asyncio
    async def test_upsert_entity_inserts_new(self, store: AsyncStore):
        """首次 upsert 插入新实体。"""
        await store.upsert_entity("Meloni", "person", "italy", "2026-05-16T10:00:00+00:00")
        async with store._db.execute(
            "SELECT canonical_name, entity_type, mention_count, target_ids FROM entities"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "Meloni"
        assert row[1] == "person"
        assert row[2] == 1
        assert row[3] == "italy"

    @pytest.mark.asyncio
    async def test_upsert_entity_increments_on_conflict(self, store: AsyncStore):
        """相同 canonical_name+entity_type 时 mention_count 累加。"""
        await store.upsert_entity("Meloni", "person", "italy", "2026-05-16T10:00:00+00:00")
        await store.upsert_entity("Meloni", "person", "italy", "2026-05-17T10:00:00+00:00")
        async with store._db.execute(
            "SELECT mention_count, last_seen FROM entities WHERE canonical_name = 'Meloni'"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 2
        assert "2026-05-17" in row[1]

    @pytest.mark.asyncio
    async def test_upsert_entity_appends_target_id(self, store: AsyncStore):
        """不同 target_id 时追加到 target_ids。"""
        await store.upsert_entity("EU", "organization", "italy", "2026-05-16T10:00:00+00:00")
        await store.upsert_entity("EU", "organization", "germany", "2026-05-17T10:00:00+00:00")
        async with store._db.execute(
            "SELECT target_ids FROM entities WHERE canonical_name = 'EU'"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None
        assert "italy" in row[0]
        assert "germany" in row[0]

    @pytest.mark.asyncio
    async def test_upsert_entity_same_target_id_no_duplicate(self, store: AsyncStore):
        """相同 target_id 不重复追加。"""
        await store.upsert_entity("EU", "organization", "italy", "2026-05-16T10:00:00+00:00")
        await store.upsert_entity("EU", "organization", "italy", "2026-05-17T10:00:00+00:00")
        async with store._db.execute(
            "SELECT target_ids FROM entities WHERE canonical_name = 'EU'"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None
        parts = [p for p in row[0].split(",") if p]
        assert parts.count("italy") == 1

    @pytest.mark.asyncio
    async def test_query_entities_basic(self, store: AsyncStore):
        """基本实体列表查询。"""
        await store.upsert_entity("Meloni", "person", "italy", "2026-05-16T10:00:00+00:00")
        await store.upsert_entity("EU", "organization", "italy", "2026-05-16T10:00:00+00:00")
        await store.upsert_entity("Roma", "location", "italy", "2026-05-16T10:00:00+00:00")
        await store.upsert_entity("Meloni", "person", "italy", "2026-05-17T10:00:00+00:00")
        entities = await store.query_entities(limit=10)
        assert len(entities) == 3
        assert entities[0]["canonical_name"] == "Meloni"
        assert entities[0]["mention_count"] == 2

    @pytest.mark.asyncio
    async def test_query_entities_filter_by_type(self, store: AsyncStore):
        """按 entity_type 过滤实体。"""
        await store.upsert_entity("Meloni", "person", "italy", "2026-05-16T10:00:00+00:00")
        await store.upsert_entity("EU", "organization", "italy", "2026-05-16T10:00:00+00:00")
        entities = await store.query_entities(entity_type="person")
        assert len(entities) == 1
        assert entities[0]["canonical_name"] == "Meloni"

    @pytest.mark.asyncio
    async def test_query_entities_min_mentions(self, store: AsyncStore):
        """按最少提及次数过滤。"""
        await store.upsert_entity("Meloni", "person", "italy", "2026-05-16T10:00:00+00:00")
        await store.upsert_entity("Meloni", "person", "italy", "2026-05-17T10:00:00+00:00")
        await store.upsert_entity("EU", "organization", "italy", "2026-05-16T10:00:00+00:00")
        entities = await store.query_entities(min_mentions=2)
        assert len(entities) == 1
        assert entities[0]["canonical_name"] == "Meloni"

    @pytest.mark.asyncio
    async def test_query_entity_detail_found(self, store: AsyncStore):
        """查询实体详情返回实体信息。"""
        await store.upsert_entity("Meloni", "person", "italy", "2026-05-16T10:00:00+00:00")
        detail = await store.query_entity_detail(1)
        assert detail is not None
        assert detail["canonical_name"] == "Meloni"
        assert detail["entity_type"] == "person"
        assert "recent_events" in detail

    @pytest.mark.asyncio
    async def test_query_entity_detail_not_found(self, store: AsyncStore):
        """查询不存在的实体返回 None。"""
        detail = await store.query_entity_detail(999)
        assert detail is None


# ---------------------------------------------------------------------------
# TestEventLinks
# ---------------------------------------------------------------------------


class TestEventLinks:
    """Phase 35: event_links 表 + 关联查询方法。"""

    @pytest.fixture
    async def store_with_links(self, tmp_path: Path):
        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()
        yield store
        await store.close()

    @pytest.mark.asyncio
    async def test_event_links_table_created(self, store_with_links: AsyncStore):
        """event_links 表在 initialize 时自动创建。"""
        store = store_with_links
        async with store._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='event_links'"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None

    @pytest.mark.asyncio
    async def test_create_and_get_link(self, store_with_links: AsyncStore):
        """create_link 写入关联，get_event_links 读回。"""
        store = store_with_links
        await store._db.execute(
            "INSERT INTO event_index "
            "(event_id, target_id, stage, created_at, entity_names, "
            "topic_tags, title_original, published_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "evt-a",
                "italy",
                "drafts",
                "2026-05-16T10:00:00+00:00",
                "Meloni,EU",
                "politics,eu",
                "Meloni visits EU",
                "2026-05-16T10:00:00+00:00",
            ),
        )
        await store._db.execute(
            "INSERT INTO event_index "
            "(event_id, target_id, stage, created_at, entity_names, "
            "topic_tags, title_original, published_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "evt-b",
                "italy",
                "drafts",
                "2026-05-16T14:00:00+00:00",
                "Meloni,EU",
                "politics",
                "EU responds to Meloni",
                "2026-05-16T14:00:00+00:00",
            ),
        )
        await store._db.commit()

        await store.create_link(
            source_event_id="evt-a",
            target_event_id="evt-b",
            link_type="followup",
            strength=0.82,
            signals={"entity_overlap": 0.8, "topic_match": 0.5, "time_proximity": 1.0},
            target_id="italy",
        )
        links = await store.get_event_links("evt-a")
        assert len(links) == 1
        assert links[0]["linked_event_id"] == "evt-b"
        assert links[0]["link_type"] == "followup"
        assert links[0]["strength"] == pytest.approx(0.82)

    @pytest.mark.asyncio
    async def test_create_link_unique_constraint(self, store_with_links: AsyncStore):
        """重复写入相同关联会被忽略。"""
        store = store_with_links
        await store._db.execute(
            "INSERT INTO event_index (event_id, target_id, stage, created_at) VALUES (?, ?, ?, ?)",
            ("evt-a", "italy", "drafts", "2026-05-16T10:00:00+00:00"),
        )
        await store._db.execute(
            "INSERT INTO event_index (event_id, target_id, stage, created_at) VALUES (?, ?, ?, ?)",
            ("evt-b", "italy", "drafts", "2026-05-16T14:00:00+00:00"),
        )
        await store._db.commit()

        await store.create_link("evt-a", "evt-b", "followup", 0.8, {}, "italy")
        await store.create_link("evt-a", "evt-b", "followup", 0.9, {}, "italy")  # 重复
        links = await store.get_event_links("evt-a")
        assert len(links) == 1

    @pytest.mark.asyncio
    async def test_find_candidates(self, store_with_links: AsyncStore):
        """find_candidates 返回同一 target 最近 N 天的事件（排除自身）。"""
        store = store_with_links
        now = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        await store._db.execute(
            "INSERT INTO event_index "
            "(event_id, target_id, stage, created_at, published_at, "
            "entity_names, topic_tags) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("evt-old", "italy", "drafts", now, now, "Meloni", "politics"),
        )
        await store._db.execute(
            "INSERT INTO event_index "
            "(event_id, target_id, stage, created_at, published_at, "
            "entity_names, topic_tags) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("evt-new", "italy", "drafts", now, now, "Meloni,EU", "politics,eu"),
        )
        await store._db.commit()

        candidates = await store.find_candidates("italy", "evt-new", days=7)
        assert len(candidates) == 1
        assert candidates[0]["event_id"] == "evt-old"

    @pytest.mark.asyncio
    async def test_find_candidates_respects_limit(self, store_with_links: AsyncStore):
        """候选关联事件必须有上限，避免单次 run 全量扫描历史。"""
        store = store_with_links
        now = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        for idx in range(5):
            await store._db.execute(
                "INSERT INTO event_index "
                "(event_id, target_id, stage, created_at, published_at, "
                "entity_names, topic_tags) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    f"evt-old-{idx}",
                    "italy",
                    "drafts",
                    now,
                    now,
                    "Meloni,EU",
                    "politics,eu",
                ),
            )
        await store._db.execute(
            "INSERT INTO event_index "
            "(event_id, target_id, stage, created_at, published_at, "
            "entity_names, topic_tags) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("evt-new", "italy", "drafts", now, now, "Meloni,EU", "politics,eu"),
        )
        await store._db.commit()

        candidates = await store.find_candidates("italy", "evt-new", days=7, limit=2)
        assert len(candidates) == 2

    @pytest.mark.asyncio
    async def test_get_event_chain(self, store_with_links: AsyncStore):
        """get_event_chain 向前向后遍历关联链。"""
        store = store_with_links
        now = "2026-05-16T12:00:00+00:00"
        for eid in ("evt-1", "evt-2", "evt-3"):
            await store._db.execute(
                "INSERT INTO event_index "
                "(event_id, target_id, stage, created_at, "
                "published_at, title_original) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (eid, "italy", "drafts", now, now, f"Event {eid}"),
            )
        await store._db.commit()
        await store.create_link("evt-1", "evt-2", "followup", 0.8, {}, "italy")
        await store.create_link("evt-2", "evt-3", "followup", 0.7, {}, "italy")

        chain = await store.get_event_chain("evt-2", depth=5)
        event_ids = [e["event_id"] for e in chain]
        assert "evt-1" in event_ids
        assert "evt-2" in event_ids
        assert "evt-3" in event_ids

    @pytest.mark.asyncio
    async def test_get_active_chains(self, store_with_links: AsyncStore):
        """get_active_chains 返回有 >=2 事件的链。"""
        store = store_with_links
        now = "2026-05-16T12:00:00+00:00"
        for eid in ("evt-1", "evt-2"):
            await store._db.execute(
                "INSERT INTO event_index "
                "(event_id, target_id, stage, created_at, "
                "published_at, title_original) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (eid, "italy", "drafts", now, now, f"Event {eid}"),
            )
        await store._db.commit()
        await store.create_link("evt-1", "evt-2", "followup", 0.8, {}, "italy")

        chains = await store.get_active_chains("italy")
        assert len(chains) >= 1
        root_ids = [c["root_event_id"] for c in chains]
        assert "evt-1" in root_ids

    @pytest.mark.asyncio
    async def test_get_event_links_empty(self, store_with_links: AsyncStore):
        """无关联事件时返回空列表。"""
        store = store_with_links
        links = await store.get_event_links("nonexistent")
        assert links == []

    @pytest.mark.asyncio
    async def test_find_candidates_excludes_self(self, store_with_links: AsyncStore):
        """find_candidates 排除事件自身。"""
        store = store_with_links
        now = "2026-05-16T12:00:00+00:00"
        await store._db.execute(
            "INSERT INTO event_index (event_id, target_id, stage, created_at, published_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("evt-only", "italy", "drafts", now, now),
        )
        await store._db.commit()

        candidates = await store.find_candidates("italy", "evt-only", days=7)
        assert candidates == []


class TestChainNarratives:
    """Phase 36: chain_narratives 表 + 叙述方法。"""

    @pytest.fixture
    async def store_with_narratives(self, tmp_path):
        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()
        yield store
        await store.close()

    async def test_chain_narratives_table_created(self, store_with_narratives):
        store = store_with_narratives
        async with store._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='chain_narratives'"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None

    async def test_upsert_and_get_narrative(self, store_with_narratives):
        store = store_with_narratives
        await store.upsert_narrative(
            chain_root_id="evt-1",
            target_id="italy",
            narrative="意大利总理梅洛尼访问欧盟总部...",
            narrative_hash="abc123",
            event_count=3,
            model_used="gpt-4o-mini",
        )
        result = await store.get_narrative("evt-1")
        assert result is not None
        assert result["narrative"] == "意大利总理梅洛尼访问欧盟总部..."
        assert result["model_used"] == "gpt-4o-mini"
        assert result["event_count"] == 3

    async def test_upsert_narrative_updates_existing(self, store_with_narratives):
        store = store_with_narratives
        await store.upsert_narrative("evt-1", "italy", "叙述v1", "hash1", 3, "model-a")
        await store.upsert_narrative("evt-1", "italy", "叙述v2", "hash2", 4, "model-b")
        result = await store.get_narrative("evt-1")
        assert result["narrative"] == "叙述v2"
        assert result["event_count"] == 4

    async def test_get_narrative_not_found(self, store_with_narratives):
        store = store_with_narratives
        result = await store.get_narrative("nonexistent")
        assert result is None

    async def test_get_event_chain_returns_extended_fields(self, store_with_narratives):
        """get_event_chain 返回 sentiment, entity_names, topic_tags, news_value_score。"""
        store = store_with_narratives
        now = "2026-05-16T12:00:00+00:00"
        await store._db.execute(
            "INSERT INTO event_index (event_id, target_id, stage, created_at, published_at, "
            "title_original, sentiment, entity_names, topic_tags, news_value_score) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "evt-1",
                "italy",
                "drafts",
                now,
                now,
                "Event One",
                "positive",
                "Meloni,EU",
                "politics",
                75,
            ),
        )
        await store._db.execute(
            "INSERT INTO event_index (event_id, target_id, stage, created_at, published_at, "
            "title_original, sentiment, entity_names, topic_tags, news_value_score) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("evt-2", "italy", "drafts", now, now, "Event Two", "negative", "Meloni", "eu", 60),
        )
        await store._db.commit()
        await store.create_link("evt-1", "evt-2", "followup", 0.8, {}, "italy")

        chain = await store.get_event_chain("evt-1", depth=5)
        assert len(chain) == 2
        first = chain[0]
        assert "sentiment" in first
        assert "entity_names" in first
        assert "topic_tags" in first
        assert "news_value_score" in first
        assert first["sentiment"] == "positive"


class TestTrendQueries:
    """Phase 37: 趋势聚合查询测试。"""

    @pytest.fixture
    async def store_with_trends(self, tmp_path: Path) -> AsyncStore:
        """创建包含趋势测试数据的 AsyncStore。"""
        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()

        base_date = "2026-05-01"
        events = [
            (
                "evt-1",
                "italy",
                "judged",
                "ansa",
                80,
                50,
                "politics",
                f"{base_date}T10:00:00",
                "positive",
                "immigration,elections",
            ),
            (
                "evt-2",
                "italy",
                "judged",
                "ansa",
                75,
                45,
                "politics",
                f"{base_date}T12:00:00",
                "negative",
                "immigration,economy",
            ),
            (
                "evt-3",
                "italy",
                "judged",
                "repubblica",
                60,
                30,
                "economy",
                f"{base_date}T14:00:00",
                "neutral",
                "economy,EU",
            ),
            (
                "evt-4",
                "italy",
                "judged",
                "ansa",
                70,
                40,
                "international",
                "2026-05-05T10:00:00",
                "positive",
                "EU,immigration",
            ),
            (
                "evt-5",
                "italy",
                "judged",
                "ansa",
                85,
                55,
                "politics",
                "2026-05-05T12:00:00",
                "negative",
                "elections,immigration",
            ),
        ]
        now = datetime.now(UTC).isoformat()
        for eid, tid, stage, src, score, rel, cls, pub, sent, tags in events:
            await store._db.execute(  # noqa: SLF001
                "INSERT OR REPLACE INTO event_index "
                "(event_id, target_id, stage, source_id, news_value_score, "
                "china_relevance, classification_l0, published_at, "
                "sentiment, topic_tags, file_path, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    eid,
                    tid,
                    stage,
                    src,
                    score,
                    rel,
                    cls,
                    pub,
                    sent,
                    tags,
                    f"data/{tid}/drafts/{eid}.md",
                    now,
                ),
            )
        await store._db.commit()  # noqa: SLF001
        return store

    @pytest.mark.asyncio
    async def test_get_sentiment_daily_counts(self, store_with_trends: AsyncStore) -> None:
        """按天统计情感分布。"""
        result = await store_with_trends.get_sentiment_daily_counts("italy", days=30)
        assert isinstance(result, list)
        assert len(result) > 0
        for entry in result:
            assert "day" in entry
            assert "sentiment" in entry
            assert "count" in entry
        # 5月1日应有 1 positive, 1 negative, 1 neutral
        may1 = [e for e in result if e["day"] == "2026-05-01"]
        sentiments = {e["sentiment"]: e["count"] for e in may1}
        assert sentiments.get("positive", 0) == 1
        assert sentiments.get("negative", 0) == 1
        assert sentiments.get("neutral", 0) == 1

    @pytest.mark.asyncio
    async def test_get_topic_daily_counts(self, store_with_trends: AsyncStore) -> None:
        """按天统计 topic 出现次数。"""
        result = await store_with_trends.get_topic_daily_counts("italy", days=30)
        assert isinstance(result, list)
        assert len(result) > 0
        # immigration 出现在 5月1日(2次) + 5月5日(2次)
        imm_counts = [e for e in result if e["topic"] == "immigration"]
        total_imm = sum(e["count"] for e in imm_counts)
        assert total_imm == 4

    @pytest.mark.asyncio
    async def test_get_top_topics(self, store_with_trends: AsyncStore) -> None:
        """获取最热主题排名。"""
        result = await store_with_trends.get_top_topics("italy", days=30, limit=5)
        assert isinstance(result, list)
        assert len(result) > 0
        # immigration 应排第一（4次）
        assert result[0]["topic"] == "immigration"
        assert result[0]["count"] == 4
        # 结果按 count 降序
        for i in range(len(result) - 1):
            assert result[i]["count"] >= result[i + 1]["count"]

    @pytest.mark.asyncio
    async def test_get_sentiment_daily_counts_empty(self, tmp_path: Path) -> None:
        """空数据库返回空列表。"""
        store = AsyncStore(tmp_path / "state.db")
        await store.initialize()
        result = await store.get_sentiment_daily_counts("nonexistent", days=7)
        assert result == []
        await store.close()


class TestSmartAlertQueries:
    """Phase 38: 智能告警查询测试。"""

    @pytest.fixture
    async def store_with_alerts(self, tmp_path: Path) -> AsyncStore:
        """创建包含告警测试数据的 AsyncStore。"""
        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()

        now = datetime.now(UTC).isoformat()
        for eid, ents in [
            ("a-evt-1", "Meloni,EU"),
            ("a-evt-2", "Meloni,China"),
            ("a-evt-3", "EU,China"),
            ("a-evt-4", "Meloni,EU"),
            ("a-evt-5", "Meloni"),
        ]:
            await store._db.execute(  # noqa: SLF001
                "INSERT OR REPLACE INTO event_index "
                "(event_id, target_id, stage, source_id, news_value_score, "
                "china_relevance, published_at, created_at, entity_names) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (eid, "italy", "judged", "ansa", 80, 50, now, now, ents),
            )
        await store._db.commit()

        await store.create_link("a-evt-1", "a-evt-2", "followup", 0.85, {}, "italy")
        await store.create_link("a-evt-3", "a-evt-4", "related", 0.5, {}, "italy")

        yield store
        await store.close()

    @pytest.mark.asyncio
    async def test_get_recent_links(self, store_with_alerts: AsyncStore) -> None:
        """获取近期新增 links。"""
        result = await store_with_alerts.get_recent_links("italy", hours=24)
        assert isinstance(result, list)
        assert len(result) == 2
        followup = [r for r in result if r["link_type"] == "followup"]
        assert len(followup) == 1
        assert followup[0]["strength"] == 0.85

    @pytest.mark.asyncio
    async def test_get_recent_links_respects_since_and_limit(
        self, store_with_alerts: AsyncStore
    ) -> None:
        """智能告警只消费 run 边界之后、且有限数量的 event links。"""
        now = datetime.now(UTC).replace(microsecond=0)
        old_at = (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
        since = (now - timedelta(minutes=30)).isoformat()
        recent_at = (now - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")

        await store_with_alerts._db.execute(
            "UPDATE event_links SET created_at = ? WHERE source_event_id = ?",
            (old_at, "a-evt-1"),
        )
        await store_with_alerts._db.execute(
            "UPDATE event_links SET created_at = ? WHERE source_event_id = ?",
            (recent_at, "a-evt-3"),
        )
        await store_with_alerts._db.commit()

        result = await store_with_alerts.get_recent_links(
            "italy",
            hours=24,
            limit=1,
            since_run_started_at=since,
        )

        assert len(result) == 1
        assert result[0]["source_event_id"] == "a-evt-3"

    @pytest.mark.asyncio
    async def test_get_entity_daily_mentions(self, store_with_alerts: AsyncStore) -> None:
        """获取实体每日提及量。"""
        result = await store_with_alerts.get_entity_daily_mentions("Meloni", "italy", days=7)
        assert isinstance(result, list)
        assert len(result) > 0
        total = sum(r["count"] for r in result)
        assert total == 4

    @pytest.mark.asyncio
    async def test_new_indexes_created(self, tmp_path: Path) -> None:
        """验证 6 个新索引正确创建。"""
        store = AsyncStore(tmp_path / "state.db")
        await store.initialize()
        async with store._db.execute(  # noqa: SLF001
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
        ) as cursor:
            indexes = {r[0] for r in await cursor.fetchall()}
        expected = {
            "idx_event_classification",
            "idx_event_source",
            "idx_event_score",
            "idx_narrative_target",
            "idx_event_links_type",
            "idx_event_created",
        }
        assert expected.issubset(indexes)
        await store.close()


class TestDashboardQueries:
    """Phase 39: Dashboard 查询测试。"""

    @pytest.mark.asyncio
    async def test_get_today_stats(self, tmp_path: Path) -> None:
        """今日 vs 昨日对比统计。"""
        store = AsyncStore(tmp_path / "state.db")
        await store.initialize()

        now = datetime.now(UTC).isoformat()
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        yesterday_date = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")

        # 今日 2 事件
        for i, score in enumerate([80, 90]):
            await store._db.execute(  # noqa: SLF001
                "INSERT OR REPLACE INTO event_index "
                "(event_id, target_id, stage, news_value_score, published_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (f"d-evt-t{i}", "italy", "judged", score, f"{today}T10:00:00", now),
            )
        # 昨日 1 事件
        await store._db.execute(  # noqa: SLF001
            "INSERT OR REPLACE INTO event_index "
            "(event_id, target_id, stage, news_value_score, published_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("d-evt-y1", "italy", "judged", 70, f"{yesterday_date}T10:00:00", now),
        )
        await store._db.commit()

        stats = await store.get_today_stats("italy")
        assert stats["today_count"] == 2
        assert stats["today_avg_score"] == 85.0
        assert stats["today_max_score"] == 90
        assert stats["yesterday_count"] == 1
        assert stats["yesterday_avg_score"] == 70.0
        await store.close()

    @pytest.mark.asyncio
    async def test_get_top_events(self, tmp_path: Path) -> None:
        """获取 Top 事件。"""
        store = AsyncStore(tmp_path / "state.db")
        await store.initialize()

        now = datetime.now(UTC).isoformat()
        for i, score in enumerate([60, 95, 70, 85, 50]):
            await store._db.execute(  # noqa: SLF001
                "INSERT OR REPLACE INTO event_index "
                "(event_id, target_id, stage, news_value_score, published_at, "
                "created_at, title_original) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    f"d-top-{i}",
                    "italy",
                    "judged",
                    score,
                    now,
                    now,
                    f"Event {i}",
                ),
            )
        await store._db.commit()

        result = await store.get_top_events("italy", days=7, limit=3)
        assert len(result) == 3
        assert result[0]["news_value_score"] == 95
        assert result[1]["news_value_score"] == 85
        assert result[2]["news_value_score"] == 70
        await store.close()


class TestGovernance:
    """Phase 40: 治理清理测试。"""

    @pytest.mark.asyncio
    async def test_prune_old_data(self, tmp_path: Path) -> None:
        """清理过期数据。"""
        store = AsyncStore(tmp_path / "state.db")
        await store.initialize()

        now = datetime.now(UTC).isoformat()
        old_date = (datetime.now(UTC) - timedelta(days=60)).isoformat()

        # 插入旧事件和新事件
        await store._db.execute(  # noqa: SLF001
            "INSERT OR REPLACE INTO event_index "
            "(event_id, target_id, stage, news_value_score, published_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("old-evt-1", "italy", "judged", 80, old_date, old_date),
        )
        await store._db.execute(  # noqa: SLF001
            "INSERT OR REPLACE INTO event_index "
            "(event_id, target_id, stage, news_value_score, published_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("new-evt-1", "italy", "judged", 90, now, now),
        )
        await store._db.commit()

        result = await store.prune_old_data("italy", max_age_days=30)
        assert result["deleted_events"] == 1

        # 新事件应保留
        remaining = await store.get_event_count("italy", "judged")
        assert remaining == 1
        await store.close()

    @pytest.mark.asyncio
    async def test_backup_db(self, tmp_path: Path) -> None:
        """数据库备份。"""
        store = AsyncStore(tmp_path / "state.db")
        await store.initialize()

        backup_dir = tmp_path / "backups"
        backup_path = await store.backup_db(backup_dir)

        assert backup_path.exists()
        assert backup_path.stat().st_size > 0
        assert backup_dir.exists()
        await store.close()

    @pytest.mark.asyncio
    async def test_prune_empty_db(self, tmp_path: Path) -> None:
        """空数据库清理不报错。"""
        store = AsyncStore(tmp_path / "state.db")
        await store.initialize()
        result = await store.prune_old_data("nonexistent", max_age_days=30)
        assert result["deleted_events"] == 0
        assert result["deleted_links"] == 0
        await store.close()


class TestFeedbackAndAlertHistory:
    """Phase 41: feedback + alert_history 表和方法。"""

    @pytest.mark.asyncio
    async def test_save_and_get_feedback(self, store: AsyncStore) -> None:
        """反馈保存和查询。"""
        rid = await store.save_feedback(
            target_id="test-target",
            event_id="evt-1",
            verdict_type="publish_override",
            comment="应推送",
            original_recommendation="archive",
            source_id="ansa",
        )
        assert rid > 0

        items = await store.get_feedback("test-target")
        assert len(items) == 1
        assert items[0]["event_id"] == "evt-1"
        assert items[0]["verdict_type"] == "publish_override"

        stats = await store.get_feedback_stats("test-target")
        assert stats["total"] == 1
        assert stats["publish_override"] == 1

    @pytest.mark.asyncio
    async def test_alert_history(self, store: AsyncStore) -> None:
        """告警历史持久化。"""
        alerts = [
            {
                "type": "chain_update",
                "severity": "high",
                "message": "链更新",
                "details": {"k": "v"},
            },
            {"type": "trend_rising", "severity": "medium", "message": "趋势上升"},
        ]
        saved = await store.save_alert_history("test-target", alerts)
        assert saved == 2

        history = await store.get_alert_history("test-target")
        assert len(history) == 2
        types = {h["alert_type"] for h in history}
        assert types == {"chain_update", "trend_rising"}

    @pytest.mark.asyncio
    async def test_save_alert_history_is_idempotent_by_alert_key(self, store: AsyncStore) -> None:
        """相同告警身份重复保存时只插入一次。"""
        alerts = [
            {
                "type": "chain_update",
                "severity": "high",
                "message": "same",
                "details": {"chain_root_id": "a", "linked_event_id": "b"},
                "triggered_at": "2026-05-29T00:00:00+00:00",
            }
        ]

        assert await store.save_alert_history("italy", alerts) == 1
        assert await store.save_alert_history("italy", alerts) == 0
        history = await store.get_alert_history("italy", limit=10)
        assert len(history) == 1

    @pytest.mark.asyncio
    async def test_save_feedback_empty_comment(self, store: AsyncStore) -> None:
        """空 comment 保存为 None。"""
        rid = await store.save_feedback(
            target_id="t1",
            event_id="e1",
            verdict_type="comment",
        )
        assert rid > 0
        items = await store.get_feedback("t1")
        assert items[0]["comment"] is None

    @pytest.mark.asyncio
    async def test_get_feedback_stats_empty(self, store: AsyncStore) -> None:
        """无反馈时统计全零。"""
        stats = await store.get_feedback_stats("no-data")
        assert stats["total"] == 0
        assert stats["publish_override"] == 0

    @pytest.mark.asyncio
    async def test_save_alert_history_empty(self, store: AsyncStore) -> None:
        """空告警列表不插入。"""
        saved = await store.save_alert_history("t1", [])
        assert saved == 0

    @pytest.mark.asyncio
    async def test_get_event_by_id(self, store: AsyncStore) -> None:
        """根据 event_id 查找事件。"""
        now = datetime.now(UTC).isoformat()
        await store._db.execute(  # noqa: SLF001
            "INSERT OR REPLACE INTO event_index "
            "(event_id, target_id, stage, source_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("evt-x", "t1", "judged", "ansa", now),
        )
        await store._db.commit()

        result = await store.get_event_by_id("t1", "evt-x")
        assert result is not None
        assert result["event_id"] == "evt-x"
        assert result["source_id"] == "ansa"

        assert await store.get_event_by_id("t1", "nonexistent") is None


@pytest.mark.asyncio
async def test_canonical_shadow_tables_created(store: AsyncStore):
    async with store._connect() as conn:
        rows = await conn.execute_fetchall("SELECT name FROM sqlite_master WHERE type = 'table'")

    table_names = {row[0] for row in rows}
    assert {
        "canonical_events",
        "event_mentions",
        "canonical_event_relations",
        "canonical_graph_operations",
        "taxonomy_assignments",
        "canonical_entity_links",
        "research_artifacts",
        "projection_runs",
    }.issubset(table_names)


@pytest.mark.asyncio
async def test_migration_v7_research_artifacts_get_professional_workflow_defaults(
    tmp_path: Path,
):
    db_path = tmp_path / "state.db"
    with closing(sqlite3.connect(db_path)) as conn:
        conn.executescript(
            """
            CREATE TABLE schema_version (
                version INTEGER PRIMARY KEY,
                description TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            INSERT INTO schema_version (version, description) VALUES
                (1, 'v1'), (2, 'v2'), (3, 'v3'), (4, 'v4'),
                (5, 'v5'), (6, 'v6'), (7, 'v7');

            CREATE TABLE canonical_events (
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
            );
            CREATE TABLE event_mentions (
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
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE canonical_event_relations (
                relation_id TEXT PRIMARY KEY,
                source_canonical_event_id TEXT NOT NULL,
                target_canonical_event_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE taxonomy_assignments (
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
            );
            CREATE TABLE canonical_entity_links (
                link_id TEXT PRIMARY KEY,
                canonical_event_id TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                entity_name TEXT NOT NULL,
                entity_type TEXT,
                confidence REAL NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE research_artifacts (
                artifact_id TEXT PRIMARY KEY,
                target_id TEXT NOT NULL,
                artifact_type TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL DEFAULT '',
                canonical_event_ids_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE projection_runs (
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
            );

            INSERT INTO research_artifacts (
                artifact_id, target_id, artifact_type, title, body,
                canonical_event_ids_json, metadata_json, created_at, updated_at
            ) VALUES (
                'ra_v7_review', 'italy', 'review_state', 'Legacy review',
                'Legacy body', '["ce_legacy"]', '{"decision":"confirmed"}',
                '2026-05-30 10:00:00', '2026-05-30 10:00:00'
            );
            """
        )

    store = AsyncStore(db_path)
    await store.initialize()
    try:
        async with store._connect() as conn:
            info = await conn.execute_fetchall("PRAGMA table_info(research_artifacts)")
            versions = await conn.execute_fetchall("SELECT version FROM schema_version")

        columns = {row[1] for row in info}
        assert {
            "subject_type",
            "subject_id",
            "status",
            "visibility",
            "created_by",
        }.issubset(columns)
        assert max(row[0] for row in versions) == 9

        artifact = await store.get_research_artifact("ra_v7_review")
        assert artifact is not None
        assert artifact["subject_type"] == "canonical_event"
        assert artifact["subject_id"] == ""
        assert artifact["status"] == "open"
        assert artifact["visibility"] == "local_private"
        assert artifact["created_by"] == "local-user"
        assert artifact["canonical_event_ids"] == ["ce_legacy"]
        assert artifact["metadata"] == {"decision": "confirmed"}
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_list_event_index_rows_for_projection_filters_by_target(store: AsyncStore):
    async with store._connect() as conn:
        await conn.execute(
            """
            INSERT INTO event_index (
                event_id, target_id, source_id, title_original, url, published_at,
                stage, news_value_score, china_relevance, classification_l0,
                metadata_json, file_path, created_at
            ) VALUES
            (
                'it_1', 'italy', 'ansa', 'Italy story', 'https://example.com/it',
                '2026-05-30T08:00:00Z', 'judged', 82, 12, 'politics',
                '{"source_kind": "rss"}', 'drafts/it_1.md', '2026-05-30T08:00:00Z'
            ),
            (
                'de_1', 'germany', 'dpa', 'Germany story', 'https://example.com/de',
                '2026-05-30T08:00:00Z', 'judged', 80, 8, 'economics',
                '{"source_kind": "wire"}', 'drafts/de_1.md', '2026-05-30T08:00:00Z'
            )
            """
        )
        await conn.commit()

    rows = await store.list_event_index_rows_for_projection(target_id="italy", limit=20)

    assert [row["event_id"] for row in rows] == ["it_1"]
    assert rows[0]["target_id"] == "italy"
    assert rows[0]["title"] == "Italy story"
    assert rows[0]["url"] == "https://example.com/it"
    assert rows[0]["metadata"] == {"source_kind": "rss"}


@pytest.mark.asyncio
async def test_list_event_index_rows_for_projection_normalizes_since_and_limit(
    store: AsyncStore,
):
    async with store._connect() as conn:
        await conn.execute(
            """
            INSERT INTO event_index (
                event_id, target_id, source_id, title_original, url, published_at,
                stage, news_value_score, china_relevance, classification_l0,
                metadata_json, file_path, created_at
            ) VALUES
            (
                'it_space_time', 'italy', 'ansa', 'Space timestamp',
                'https://example.com/space', NULL, 'judged', 82, 12, 'politics',
                '{}', 'drafts/it_space_time.md', '2026-05-30 08:00:00'
            ),
            (
                'it_later', 'italy', 'ansa', 'Later timestamp',
                'https://example.com/later', NULL, 'judged', 81, 10, 'economics',
                '{}', 'drafts/it_later.md', '2026-05-30 09:00:00'
            ),
            (
                'it_old', 'italy', 'ansa', 'Old timestamp',
                'https://example.com/old', NULL, 'judged', 80, 8, 'economics',
                '{}', 'drafts/it_old.md', '2026-05-29 23:59:59'
            )
            """
        )
        await conn.commit()

    rows = await store.list_event_index_rows_for_projection(
        target_id="italy",
        since="2026-05-30T00:00:00Z",
        limit=20,
    )
    limited_rows = await store.list_event_index_rows_for_projection(
        target_id="italy",
        since="2026-05-30T00:00:00Z",
        limit=-1,
    )

    assert {row["event_id"] for row in rows} == {"it_later", "it_space_time"}
    assert len(limited_rows) == 1
    assert limited_rows[0]["event_id"] == "it_later"


@pytest.mark.asyncio
async def test_upsert_canonical_event_is_idempotent(store: AsyncStore):
    payload = {
        "canonical_event_id": "ce_italy_001",
        "target_id": "italy",
        "title": "Example event",
        "summary": "One canonical event.",
        "event_time": "2026-05-30T08:00:00Z",
        "status": "active",
        "confidence": 92.0,
        "metadata": {"source": "test"},
    }
    first = await store.upsert_canonical_event(payload)
    second = await store.upsert_canonical_event({**payload, "title": "Example event updated"})

    rows = await store.list_canonical_events(target_id="italy", limit=20)
    assert first == "ce_italy_001"
    assert second == "ce_italy_001"
    assert len(rows) == 1
    assert rows[0]["title"] == "Example event updated"


@pytest.mark.asyncio
async def test_canonical_graph_operation_record_and_list(store: AsyncStore):
    await store.upsert_canonical_event(
        {
            "canonical_event_id": "ce_italy_graph_source",
            "target_id": "italy",
            "title": "Source event",
            "summary": "",
            "event_time": "2026-05-30T10:00:00Z",
            "status": "active",
            "confidence": 90,
            "metadata": {},
        }
    )

    operation_id = await store.record_canonical_graph_operation(
        {
            "operation_id": "cgo-italy-merge-example",
            "target_id": "italy",
            "operation_type": "merge",
            "decision_artifact_id": "ra_italy_merge_example",
            "primary_canonical_event_id": "ce_italy_graph_source",
            "result_canonical_event_id": "ce_italy_graph_source",
            "status": "applied",
            "changes": [{"type": "mark_merged", "canonical_event_id": "ce_merged"}],
            "warnings": [],
            "metadata": {"idempotency_key": "merge-key"},
            "created_by": "local-user",
        }
    )

    assert operation_id == "cgo-italy-merge-example"
    listed = await store.list_canonical_graph_operations(target_id="italy", limit=10)
    assert [item["operation_id"] for item in listed] == ["cgo-italy-merge-example"]
    assert listed[0]["changes"][0]["type"] == "mark_merged"
    assert listed[0]["metadata"]["idempotency_key"] == "merge-key"

    by_artifact = await store.list_canonical_graph_operations(
        target_id="italy",
        decision_artifact_id="ra_italy_merge_example",
        limit=10,
    )
    assert [item["operation_id"] for item in by_artifact] == ["cgo-italy-merge-example"]

    missing = await store.list_canonical_graph_operations(target_id="france", limit=10)
    assert missing == []


@pytest.mark.asyncio
async def test_canonical_graph_operation_duplicate_artifact_returns_existing_id(
    store: AsyncStore,
):
    await store.upsert_canonical_event(
        {
            "canonical_event_id": "ce_italy_graph_duplicate",
            "target_id": "italy",
            "title": "Duplicate artifact event",
            "summary": "",
            "event_time": "2026-05-30T10:00:00Z",
            "status": "active",
            "confidence": 90,
            "metadata": {},
        }
    )

    base_operation = {
        "target_id": "italy",
        "operation_type": "merge",
        "decision_artifact_id": "ra_italy_duplicate_artifact",
        "primary_canonical_event_id": "ce_italy_graph_duplicate",
        "result_canonical_event_id": "ce_italy_graph_duplicate",
        "status": "applied",
        "changes": [],
        "warnings": [],
        "metadata": {},
        "created_by": "local-user",
    }
    first_operation_id = await store.record_canonical_graph_operation(
        {**base_operation, "operation_id": "cgo-italy-duplicate-first"}
    )
    second_operation_id = await store.record_canonical_graph_operation(
        {**base_operation, "operation_id": "cgo-italy-duplicate-second"}
    )

    listed = await store.list_canonical_graph_operations(target_id="italy", limit=10)
    assert first_operation_id == "cgo-italy-duplicate-first"
    assert second_operation_id == first_operation_id
    assert [item["operation_id"] for item in listed] == [first_operation_id]


@pytest.mark.asyncio
async def test_canonical_graph_operation_list_normalizes_pagination(store: AsyncStore):
    await store.upsert_canonical_event(
        {
            "canonical_event_id": "ce_italy_graph_pagination",
            "target_id": "italy",
            "title": "Pagination event",
            "summary": "",
            "event_time": "2026-05-30T10:00:00Z",
            "status": "active",
            "confidence": 90,
            "metadata": {},
        }
    )

    for operation_id in ("cgo-italy-pagination-a", "cgo-italy-pagination-b"):
        await store.record_canonical_graph_operation(
            {
                "operation_id": operation_id,
                "target_id": "italy",
                "operation_type": "merge",
                "primary_canonical_event_id": "ce_italy_graph_pagination",
                "result_canonical_event_id": "ce_italy_graph_pagination",
                "status": "applied",
                "changes": [],
                "warnings": [],
                "metadata": {},
                "created_by": "local-user",
            }
        )

    negative_limit = await store.list_canonical_graph_operations(target_id="italy", limit=-1)
    zero_offset = await store.list_canonical_graph_operations(
        target_id="italy",
        limit=1,
        offset=0,
    )
    negative_offset = await store.list_canonical_graph_operations(
        target_id="italy",
        limit=1,
        offset=-10,
    )

    assert len(negative_limit) == 1
    assert [item["operation_id"] for item in negative_offset] == [
        item["operation_id"] for item in zero_offset
    ]


@pytest.mark.asyncio
async def test_research_artifact_upsert_list_and_patch(store: AsyncStore):
    await store.upsert_canonical_event(
        {
            "canonical_event_id": "ce_italy_review_001",
            "target_id": "italy",
            "title": "Policy event",
            "summary": "A policy event",
            "event_time": "2026-05-30T10:00:00Z",
            "status": "needs_review",
            "confidence": 65,
            "metadata": {"mention_count": 2, "source_count": 2, "news_value_score": 82},
        }
    )

    artifact_id = await store.upsert_research_artifact(
        {
            "artifact_id": "ra_italy_review_001",
            "target_id": "italy",
            "artifact_type": "review_state",
            "title": "人工确认",
            "body": "多信源一致。",
            "subject_type": "canonical_event",
            "subject_id": "ce_italy_review_001",
            "canonical_event_ids": ["ce_italy_review_001"],
            "status": "open",
            "visibility": "local_private",
            "created_by": "local-user",
            "metadata": {"decision": "needs_more_evidence"},
        }
    )

    assert artifact_id == "ra_italy_review_001"
    listed = await store.list_research_artifacts(
        target_id="italy",
        subject_type="canonical_event",
        subject_id="ce_italy_review_001",
    )
    assert len(listed) == 1
    assert listed[0]["metadata"]["decision"] == "needs_more_evidence"

    patched = await store.update_research_artifact(
        "ra_italy_review_001",
        target_id="italy",
        patch={
            "status": "resolved",
            "body": "复核完成。",
            "metadata": {"decision": "confirmed", "reason": "sources agree"},
        },
    )
    assert patched is not None
    assert patched["status"] == "resolved"
    assert patched["metadata"]["decision"] == "confirmed"


@pytest.mark.asyncio
async def test_research_queue_hides_confirmed_items_by_default(store: AsyncStore):
    for idx, confidence in (("001", 65), ("002", 92)):
        await store.upsert_canonical_event(
            {
                "canonical_event_id": f"ce_italy_review_{idx}",
                "target_id": "italy",
                "title": f"Event {idx}",
                "summary": "",
                "event_time": f"2026-05-30T10:0{idx[-1]}:00Z",
                "status": "needs_review" if confidence < 80 else "active",
                "confidence": confidence,
                "metadata": {"mention_count": int(idx), "source_count": 1},
            }
        )

    await store.upsert_research_artifact(
        {
            "artifact_id": "ra_italy_review_done",
            "target_id": "italy",
            "artifact_type": "review_state",
            "title": "Confirmed",
            "body": "",
            "subject_type": "canonical_event",
            "subject_id": "ce_italy_review_001",
            "canonical_event_ids": ["ce_italy_review_001"],
            "status": "resolved",
            "metadata": {"decision": "confirmed"},
        }
    )
    await store.upsert_research_artifact(
        {
            "artifact_id": "ra_italy_merge_open",
            "target_id": "italy",
            "artifact_type": "merge_decision",
            "title": "Merge candidate",
            "body": "",
            "subject_type": "canonical_event",
            "subject_id": "ce_italy_review_002",
            "canonical_event_ids": ["ce_italy_review_002", "ce_other"],
            "status": "open",
            "metadata": {"candidate_canonical_event_ids": ["ce_other"], "decision": "proposed"},
        }
    )

    open_queue = await store.list_research_queue(target_id="italy", status="open", limit=10)
    assert [item["canonical_event_id"] for item in open_queue["items"]] == ["ce_italy_review_002"]
    assert open_queue["items"][0]["open_decisions"] == {"merge": 1, "split": 0}

    resolved_queue = await store.list_research_queue(target_id="italy", status="resolved", limit=10)
    assert [item["canonical_event_id"] for item in resolved_queue["items"]] == [
        "ce_italy_review_001"
    ]


@pytest.mark.asyncio
async def test_research_artifact_rejects_missing_or_cross_target_canonical_subject(
    store: AsyncStore,
):
    await store.upsert_canonical_event(
        {
            "canonical_event_id": "ce_italy_scope_001",
            "target_id": "italy",
            "title": "Scoped event",
            "summary": "",
            "event_time": "2026-05-30T10:00:00Z",
            "status": "active",
            "confidence": 90,
            "metadata": {},
        }
    )

    invalid_rows = [
        {
            "artifact_id": "ra_japan_cross_scope",
            "target_id": "japan",
            "subject_id": "ce_italy_scope_001",
        },
        {
            "artifact_id": "ra_italy_missing_scope",
            "target_id": "italy",
            "subject_id": "ce_missing_scope_001",
        },
    ]
    for invalid in invalid_rows:
        with pytest.raises(ValueError, match="canonical_event"):
            await store.upsert_research_artifact(
                {
                    "artifact_type": "review_state",
                    "title": "Invalid subject",
                    "body": "",
                    "subject_type": "canonical_event",
                    "canonical_event_ids": [invalid["subject_id"]],
                    "status": "open",
                    "metadata": {"decision": "needs_more_evidence"},
                    **invalid,
                }
            )
        assert await store.get_research_artifact(invalid["artifact_id"]) is None


@pytest.mark.asyncio
async def test_research_artifact_rejects_non_canonical_subject_type(store: AsyncStore):
    with pytest.raises(ValueError, match="canonical_event"):
        await store.upsert_research_artifact(
            {
                "artifact_id": "ra_italy_external_subject",
                "target_id": "italy",
                "artifact_type": "review_state",
                "title": "Invalid subject type",
                "body": "",
                "subject_type": "event",
                "subject_id": "evt_italy_001",
                "canonical_event_ids": [],
                "status": "open",
                "metadata": {"decision": "needs_more_evidence"},
            }
        )

    assert await store.get_research_artifact("ra_italy_external_subject") is None


@pytest.mark.asyncio
async def test_research_artifact_upsert_rejects_identity_boundary_changes(
    store: AsyncStore,
):
    for canonical_event_id, target_id in (
        ("ce_italy_boundary_001", "italy"),
        ("ce_italy_boundary_002", "italy"),
        ("ce_japan_boundary_001", "japan"),
    ):
        await store.upsert_canonical_event(
            {
                "canonical_event_id": canonical_event_id,
                "target_id": target_id,
                "title": canonical_event_id,
                "summary": "",
                "event_time": "2026-05-30T10:00:00Z",
                "status": "active",
                "confidence": 90,
                "metadata": {},
            }
        )

    original = {
        "artifact_id": "ra_italy_boundary_guard",
        "target_id": "italy",
        "artifact_type": "review_state",
        "title": "Boundary guard",
        "body": "",
        "subject_type": "canonical_event",
        "subject_id": "ce_italy_boundary_001",
        "canonical_event_ids": ["ce_italy_boundary_001"],
        "status": "open",
        "metadata": {"decision": "needs_more_evidence"},
    }
    await store.upsert_research_artifact(original)

    invalid_updates = [
        {
            **original,
            "target_id": "japan",
            "subject_id": "ce_japan_boundary_001",
            "canonical_event_ids": ["ce_japan_boundary_001"],
        },
        {
            **original,
            "subject_id": "ce_italy_boundary_002",
            "canonical_event_ids": ["ce_italy_boundary_002"],
        },
        {
            **original,
            "artifact_type": "annotation",
        },
    ]
    for invalid_update in invalid_updates:
        with pytest.raises(ValueError, match="artifact_id"):
            await store.upsert_research_artifact(invalid_update)

        stored = await store.get_research_artifact(original["artifact_id"])
        assert stored is not None
        assert stored["target_id"] == original["target_id"]
        assert stored["subject_id"] == original["subject_id"]
        assert stored["artifact_type"] == original["artifact_type"]


@pytest.mark.asyncio
async def test_research_queue_keeps_open_decisions_after_confirmed_review(
    store: AsyncStore,
):
    await store.upsert_canonical_event(
        {
            "canonical_event_id": "ce_italy_confirmed_with_merge",
            "target_id": "italy",
            "title": "Confirmed event with open merge work",
            "summary": "",
            "event_time": "2026-05-30T10:00:00Z",
            "status": "active",
            "confidence": 95,
            "metadata": {"mention_count": 2, "source_count": 2, "news_value_score": 70},
        }
    )
    await store.upsert_research_artifact(
        {
            "artifact_id": "ra_italy_confirmed_review",
            "target_id": "italy",
            "artifact_type": "review_state",
            "title": "Confirmed",
            "body": "",
            "subject_type": "canonical_event",
            "subject_id": "ce_italy_confirmed_with_merge",
            "canonical_event_ids": ["ce_italy_confirmed_with_merge"],
            "status": "resolved",
            "metadata": {"decision": "confirmed"},
        }
    )
    await store.upsert_research_artifact(
        {
            "artifact_id": "ra_italy_confirmed_merge_open",
            "target_id": "italy",
            "artifact_type": "merge_decision",
            "title": "Merge still open",
            "body": "",
            "subject_type": "canonical_event",
            "subject_id": "ce_italy_confirmed_with_merge",
            "canonical_event_ids": ["ce_italy_confirmed_with_merge"],
            "status": "open",
            "metadata": {"candidate_canonical_event_ids": [], "decision": "proposed"},
        }
    )

    open_queue = await store.list_research_queue(target_id="italy", status="open", limit=10)

    assert [item["canonical_event_id"] for item in open_queue["items"]] == [
        "ce_italy_confirmed_with_merge"
    ]
    assert open_queue["items"][0]["latest_review"]["status"] == "resolved"
    assert open_queue["items"][0]["open_decisions"] == {"merge": 1, "split": 0}


@pytest.mark.asyncio
async def test_research_queue_selects_latest_review_state_with_tied_timestamps(
    store: AsyncStore,
):
    await store.upsert_canonical_event(
        {
            "canonical_event_id": "ce_italy_tied_review",
            "target_id": "italy",
            "title": "Tied review timestamps",
            "summary": "",
            "event_time": "2026-05-30T10:00:00Z",
            "status": "needs_review",
            "confidence": 65,
            "metadata": {"mention_count": 2, "source_count": 2, "news_value_score": 70},
        }
    )
    await store.upsert_research_artifact(
        {
            "artifact_id": "ra_italy_review_tie_001",
            "target_id": "italy",
            "artifact_type": "review_state",
            "title": "Confirmed first",
            "body": "",
            "subject_type": "canonical_event",
            "subject_id": "ce_italy_tied_review",
            "canonical_event_ids": ["ce_italy_tied_review"],
            "status": "resolved",
            "metadata": {"decision": "confirmed"},
        }
    )
    await store.upsert_research_artifact(
        {
            "artifact_id": "ra_italy_review_tie_002",
            "target_id": "italy",
            "artifact_type": "review_state",
            "title": "Needs evidence second",
            "body": "",
            "subject_type": "canonical_event",
            "subject_id": "ce_italy_tied_review",
            "canonical_event_ids": ["ce_italy_tied_review"],
            "status": "open",
            "metadata": {"decision": "needs_more_evidence"},
        }
    )
    async with store._connect() as conn:
        await conn.execute(
            """UPDATE research_artifacts
               SET created_at = ?, updated_at = ?
               WHERE artifact_id IN (?, ?)""",
            (
                "2026-05-30 10:00:00",
                "2026-05-30 10:00:00",
                "ra_italy_review_tie_001",
                "ra_italy_review_tie_002",
            ),
        )
        await conn.commit()

    open_queue = await store.list_research_queue(target_id="italy", status="open", limit=10)
    resolved_queue = await store.list_research_queue(
        target_id="italy",
        status="resolved",
        limit=10,
    )

    assert [item["canonical_event_id"] for item in open_queue["items"]] == ["ce_italy_tied_review"]
    assert open_queue["items"][0]["latest_review"]["artifact_id"] == "ra_italy_review_tie_002"
    assert resolved_queue["items"] == []


@pytest.mark.asyncio
async def test_upsert_event_mention_is_idempotent(store: AsyncStore):
    await store.upsert_canonical_event(
        {
            "canonical_event_id": "ce_italy_001",
            "target_id": "italy",
            "title": "Example event",
            "summary": "",
            "event_time": "2026-05-30T08:00:00Z",
            "status": "active",
            "confidence": 90,
            "metadata": {},
        }
    )
    payload = {
        "mention_id": "em_italy_event_001",
        "canonical_event_id": "ce_italy_001",
        "event_id": "event_001",
        "target_id": "italy",
        "source_id": "ansa",
        "url": "https://example.com/news/1",
        "title": "Example event",
        "published_at": "2026-05-30T08:00:00Z",
        "metadata": {"score": 82},
    }
    first = await store.upsert_event_mention(payload)
    second = await store.upsert_event_mention({**payload, "title": "Example event revised"})

    mentions = await store.list_event_mentions("ce_italy_001")
    assert first == "em_italy_event_001"
    assert second == "em_italy_event_001"
    assert len(mentions) == 1
    assert mentions[0]["title"] == "Example event revised"


@pytest.mark.asyncio
async def test_upsert_canonical_relation_is_idempotent(store: AsyncStore):
    for canonical_event_id in ("ce_source", "ce_target"):
        await store.upsert_canonical_event(
            {
                "canonical_event_id": canonical_event_id,
                "target_id": "italy",
                "title": canonical_event_id,
                "summary": "",
                "event_time": "2026-05-30T08:00:00Z",
                "status": "active",
                "confidence": 80,
                "metadata": {},
            }
        )

    payload = {
        "relation_id": "rel_source_target_followup",
        "source_canonical_event_id": "ce_source",
        "target_canonical_event_id": "ce_target",
        "relation_type": "follow_up",
        "confidence": 70.0,
        "metadata": {"reason": "same story"},
    }
    await store.upsert_canonical_relation(payload)
    await store.upsert_canonical_relation({**payload, "confidence": 75.0})

    relations = await store.list_canonical_relations("ce_source")
    assert len(relations) == 1
    assert relations[0]["confidence"] == 75.0
