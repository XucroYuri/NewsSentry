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
        assert stats["by_classification"]["international"] == 3
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
        now = "2026-05-16T12:00:00+00:00"
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

        return store

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
