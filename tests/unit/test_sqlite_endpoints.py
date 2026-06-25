"""SQLite store 端点测试 — 从 test_api_server.py 分离 (M-52 第一批)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import MagicMock, patch

import pytest
import yaml
from fastapi.testclient import TestClient

from news_sentry.core import api_server as api_server_module
from news_sentry.core.api_server import create_app
from news_sentry.core.async_store import AsyncStore


def _close_test_store(store: Any) -> None:
    if isinstance(store, AsyncStore) and store._db is not None:  # noqa: SLF001
        asyncio.run(store.close())


@pytest.fixture(autouse=True)
def _reset_api_server_store_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("NEWSSENTRY_DEPLOYMENT_ENV", "local")
    monkeypatch.setattr(api_server_module, "_deployment_env", "")
    yield
    _close_test_store(api_server_module._store)
    api_server_module._store = None
    stores = list(api_server_module._target_stores.values())
    api_server_module._target_stores.clear()
    for store in stores:
        _close_test_store(store)
    getattr(api_server_module, "_source_inventory_cache", {}).clear()
    getattr(api_server_module, "_target_validation_cache", {}).clear()
    getattr(api_server_module, "_collector_diagnostics_cache", {}).clear()
    from news_sentry.core import _state as _state_mod
    for attr in ["_public_source_configs_cache", "_source_inventory_cache",
                  "_target_validation_cache", "_collector_diagnostics_cache",
                  "_admin_overview_cache", "_admin_targets_cache",
                  "_public_news_feed_cache", "_public_facets_cache",
                  "_public_regions_cache", "_public_bootstrap_cache"]:
        getattr(_state_mod, attr, {}).clear()


class TestAPIServerSQLite:
    """使用 AsyncStore（SQLite）的 API Server 端点测试。"""

    @pytest.fixture
    async def client_with_store(self, tmp_path: Path):
        """创建包含测试数据的 AsyncStore + AsyncClient。"""
        from httpx import ASGITransport, AsyncClient

        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()

        now = datetime.now(UTC).isoformat()
        events_data = [
            {
                "event_id": "ne-italy-ansa-20260512-aaa11111",
                "source_id": "ansa",
                "news_value_score": 80,
                "china_relevance": 20,
                "classification_l0": "international",
                "title_original": "Pace in Medio Oriente",
                "sentiment": "positive",
                "entity_names": "Roma,Medio Oriente",
                "topic_tags": "international,peace",
            },
            {
                "event_id": "ne-italy-repubblica-20260512-bbb22222",
                "source_id": "repubblica",
                "news_value_score": 60,
                "china_relevance": 40,
                "classification_l0": "politics",
                "title_original": "Elezioni politiche",
                "sentiment": "negative",
                "entity_names": "Meloni",
                "topic_tags": "politics,elections",
            },
            {
                "event_id": "ne-italy-ansa-20260512-ccc33333",
                "source_id": "ansa",
                "news_value_score": 90,
                "china_relevance": 10,
                "classification_l0": "international",
                "title_original": "Accordo commerciale",
                "sentiment": "neutral",
                "entity_names": None,
                "topic_tags": "economy",
            },
        ]

        # 创建对应的 drafts 文件
        drafts_dir = tmp_path / "italy" / "drafts"
        drafts_dir.mkdir(parents=True, exist_ok=True)

        for ev in events_data:
            file_name = f"outputted_{ev['source_id']}_{ev['event_id']}.md"
            file_path = drafts_dir / file_name
            fm_data = {
                "id": ev["event_id"],
                "source_id": ev["source_id"],
                "url": "https://example.com",
                "title_original": ev["title_original"],
                "news_value_score": ev["news_value_score"],
                "china_relevance": ev["china_relevance"],
                "classification": {"l0": ev["classification_l0"]},
                "pipeline_stage": "outputted",
            }
            fm = yaml.dump(fm_data, allow_unicode=True, default_flow_style=False, sort_keys=False)
            file_path.write_text(
                f"---\n{fm}---\n\n# {ev['title_original']}\n\nBody\n",
                encoding="utf-8",
            )

            await store._db.execute(  # noqa: SLF001
                "INSERT OR REPLACE INTO event_index "
                "(event_id, target_id, stage, source_id, news_value_score, "
                "china_relevance, classification_l0, title_original, "
                "published_at, file_path, created_at, "
                "sentiment, entity_names, topic_tags) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ev["event_id"],
                    "italy",
                    "drafts",
                    ev["source_id"],
                    ev["news_value_score"],
                    ev["china_relevance"],
                    ev["classification_l0"],
                    ev["title_original"],
                    now,
                    str(file_path),
                    now,
                    ev.get("sentiment"),
                    ev.get("entity_names"),
                    ev.get("topic_tags"),
                ),
            )
        await store._db.commit()  # noqa: SLF001

        app = create_app(data_dir=tmp_path, store=store, skip_lifespan=True)
        transport = ASGITransport(app=app)
        client = AsyncClient(transport=transport, base_url="http://test")
        # 获取 dev mode token
        token_resp = await client.post("/api/v1/auth/token", json={"api_key": ""})
        assert token_resp.status_code == 200
        token = token_resp.json()["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"
        yield client, store
        await client.aclose()
        await store.close()

    async def _authorize_dev_client(self, client) -> None:
        """给手工创建的 AsyncClient 设置 dev mode Bearer token。"""
        token_resp = await client.post("/api/v1/auth/token", json={"api_key": ""})
        assert token_resp.status_code == 200
        client.headers["Authorization"] = f"Bearer {token_resp.json()['access_token']}"

    async def test_stats_with_sqlite(
        self,
        client_with_store,
    ) -> None:
        client, _ = client_with_store
        resp = await client.get("/api/v1/stats", params={"target_id": "italy"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_events"] == 3
        assert data["avg_news_value_score"] is not None
        assert data["by_classification"]["international-relations"] == 2
        assert data["by_classification"]["politics"] == 1
        assert data["by_source"]["ansa"] == 2

    async def test_list_events_with_sqlite(
        self,
        client_with_store,
    ) -> None:
        client, _ = client_with_store
        resp = await client.get("/api/v1/events", params={"target_id": "italy"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["events"]) == 3

    async def test_events_feed_recovers_frontmatter_when_index_path_is_stale(
        self,
        tmp_path: Path,
    ) -> None:
        """SQLite file_path 失效时，公开 feed 应从 drafts 文件恢复展示字段。"""
        from httpx import ASGITransport, AsyncClient

        store = AsyncStore(tmp_path / "state.db")
        await store.initialize()
        drafts_dir = tmp_path / "italy" / "drafts"
        drafts_dir.mkdir(parents=True, exist_ok=True)
        event_id = "ne-italy-repubblica-20260528-51db8e48"
        actual_path = drafts_dir / "2026-05-28-repubblica-ne-italy-rep.md"
        stale_path = drafts_dir / "outputted_repubblica_ne-italy-repubblica-20260528-51db8e48.md"
        fm = yaml.dump(
            {
                "id": event_id,
                "source_id": "repubblica",
                "url": "https://example.com/news",
                "title_original": "Guerra in Iran",
                "published_at": "2026-05-28T00:18:47+00:00",
                "news_value_score": 100,
                "classification": {"l0": "international"},
                "pipeline_stage": "outputted",
            },
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
        actual_path.write_text(f"---\n{fm}---\n\n# Guerra in Iran\n", encoding="utf-8")
        now = datetime.now(UTC).isoformat()
        try:
            await store._db.execute(  # noqa: SLF001
                "INSERT OR REPLACE INTO event_index "
                "(event_id, target_id, stage, source_id, news_value_score, "
                "china_relevance, classification_l0, title_original, "
                "published_at, file_path, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id,
                    "italy",
                    "drafts",
                    "repubblica",
                    100,
                    None,
                    None,
                    "Guerra in Iran",
                    "2026-05-28T00:18:47+00:00",
                    str(stale_path),
                    now,
                ),
            )
            await store._db.commit()  # noqa: SLF001

            app = create_app(data_dir=tmp_path, store=store, skip_lifespan=True)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/v1/events/feed", params={"target_id": "italy"})

            assert resp.status_code == 200
            item = resp.json()["groups"][0]["events"][0]
            assert item["event_id"] == event_id
            assert item["flat_tags"] == ["international-relations"]
        finally:
            await store.close()

    async def test_events_feed_recovers_evaluated_frontmatter_when_index_has_no_file_path(
        self,
        tmp_path: Path,
    ) -> None:
        """markdown_auto_drafts=false 时，feed 仍应从 evaluated 恢复 story/cluster 元数据。"""
        from httpx import ASGITransport, AsyncClient

        store = AsyncStore(tmp_path / "state.db")
        await store.initialize()
        evaluated_dir = tmp_path / "italy" / "evaluated"
        evaluated_dir.mkdir(parents=True, exist_ok=True)
        event_id = "ne-italy-gdelt-italy-20260531-cluster01"
        fm = yaml.dump(
            {
                "id": event_id,
                "source_id": "gdelt-italy",
                "url": "https://example.com/sports",
                "title_original": "Le volte che lItalia non è andata ai Mondiali di calcio",
                "published_at": "2026-05-31T07:08:08+00:00",
                "news_value_score": 70,
                "classification": {"l0": "sports", "l1": [{"code": "football"}]},
                "cluster_id": "cluster-italy-sports-001",
                "story_id": "story-italy-sports-001",
                "metadata": {
                    "classification": {"l0": "sports", "l1": [{"code": "football"}]},
                    "clustering": {"cluster_type": "same_event", "cluster_size": 3},
                },
                "pipeline_stage": "judged",
            },
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
        (evaluated_dir / f"judged_gdelt-italy_{event_id}.md").write_text(
            f"---\n{fm}---\n\n# Sports\n",
            encoding="utf-8",
        )
        now = datetime.now(UTC).isoformat()
        try:
            await store._db.execute(  # noqa: SLF001
                "INSERT OR REPLACE INTO event_index "
                "(event_id, target_id, stage, source_id, news_value_score, "
                "china_relevance, classification_l0, title_original, "
                "published_at, file_path, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id,
                    "italy",
                    "drafts",
                    "gdelt-italy",
                    70,
                    None,
                    "tech",
                    "Le volte che lItalia non è andata ai Mondiali di calcio",
                    "2026-05-31T07:08:08+00:00",
                    None,
                    now,
                ),
            )
            await store._db.commit()  # noqa: SLF001

            app = create_app(data_dir=tmp_path, store=store, skip_lifespan=True)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/v1/events/feed", params={"target_id": "italy"})

            assert resp.status_code == 200
            item = resp.json()["groups"][0]["events"][0]
            assert item["cluster_id"] == "cluster-italy-sports-001"
            assert item["story_id"] == "story-italy-sports-001"
            assert item["classification"]["l0"] == "sports"
            assert item["clustering"] == {"cluster_type": "same_event", "cluster_size": 3}
        finally:
            await store.close()

    async def test_events_feed_collapses_duplicate_story_events(
        self,
        tmp_path: Path,
    ) -> None:
        """同一 story 的多条 mention 在公开 feed 中折叠为一条。"""
        from httpx import ASGITransport, AsyncClient

        store = AsyncStore(tmp_path / "state.db")
        await store.initialize()
        evaluated_dir = tmp_path / "italy" / "evaluated"
        evaluated_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(UTC).isoformat()
        rows = [
            (
                "ne-italy-gdelt-italy-20260531-story01a",
                "Latest duplicate mention",
                "2026-05-31T07:10:00+00:00",
            ),
            (
                "ne-italy-gdelt-italy-20260531-story01b",
                "Earlier duplicate mention",
                "2026-05-31T07:05:00+00:00",
            ),
        ]
        try:
            for event_id, title, published_at in rows:
                fm = yaml.dump(
                    {
                        "id": event_id,
                        "source_id": "gdelt-italy",
                        "url": f"https://example.com/{event_id}",
                        "title_original": title,
                        "published_at": published_at,
                        "news_value_score": 80,
                        "classification": {"l0": "international-relations"},
                        "cluster_id": "cluster-italy-story-001",
                        "story_id": "story-italy-story-001",
                        "metadata": {
                            "classification": {"l0": "international-relations"},
                            "clustering": {"cluster_type": "same_event"},
                        },
                        "pipeline_stage": "judged",
                    },
                    allow_unicode=True,
                    default_flow_style=False,
                    sort_keys=False,
                )
                (evaluated_dir / f"judged_gdelt-italy_{event_id}.md").write_text(
                    f"---\n{fm}---\n\n# {title}\n",
                    encoding="utf-8",
                )
                await store._db.execute(  # noqa: SLF001
                    "INSERT OR REPLACE INTO event_index "
                    "(event_id, target_id, stage, source_id, news_value_score, "
                    "china_relevance, classification_l0, title_original, "
                    "published_at, file_path, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        event_id,
                        "italy",
                        "drafts",
                        "gdelt-italy",
                        80,
                        None,
                        "international-relations",
                        title,
                        published_at,
                        None,
                        now,
                    ),
                )
            await store._db.commit()  # noqa: SLF001

            app = create_app(data_dir=tmp_path, store=store, skip_lifespan=True)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/v1/events/feed", params={"target_id": "italy"})

            assert resp.status_code == 200
            events = resp.json()["groups"][0]["events"]
            assert len(events) == 1
            assert events[0]["event_id"] == "ne-italy-gdelt-italy-20260531-story01a"
            assert events[0]["related_count"] == 1
        finally:
            await store.close()

    async def test_events_feed_does_not_reuse_collided_file_path_frontmatter(
        self,
        tmp_path: Path,
    ) -> None:
        """SQLite 行的 file_path 指向其他事件时，feed 不应重复展示该文件内容。"""
        from httpx import ASGITransport, AsyncClient

        store = AsyncStore(tmp_path / "state.db")
        await store.initialize()
        drafts_dir = tmp_path / "italy" / "drafts"
        drafts_dir.mkdir(parents=True, exist_ok=True)
        event_one = "ne-italy-ansa-20260528-aaa11111"
        event_two = "ne-italy-ansa-20260528-bbb22222"
        collided_path = drafts_dir / "2026-05-28-ansa-ne-italy-ans.md"
        fm = yaml.dump(
            {
                "id": event_two,
                "source_id": "ansa",
                "url": "https://example.com/two",
                "title_original": "Secondo evento reale",
                "published_at": "2026-05-28T09:00:00+00:00",
                "news_value_score": 80,
                "classification": {"l0": "politics"},
                "pipeline_stage": "outputted",
            },
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
        collided_path.write_text(f"---\n{fm}---\n\n# Secondo evento reale\n", encoding="utf-8")
        now = datetime.now(UTC).isoformat()
        try:
            rows = [
                (
                    event_one,
                    "Primo evento solo in indice",
                    "2026-05-28T10:00:00+00:00",
                    70,
                ),
                (
                    event_two,
                    "Secondo evento reale",
                    "2026-05-28T09:00:00+00:00",
                    80,
                ),
            ]
            for event_id, title, published_at, score in rows:
                await store._db.execute(  # noqa: SLF001
                    "INSERT OR REPLACE INTO event_index "
                    "(event_id, target_id, stage, source_id, news_value_score, "
                    "china_relevance, classification_l0, title_original, "
                    "published_at, file_path, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        event_id,
                        "italy",
                        "drafts",
                        "ansa",
                        score,
                        None,
                        "politics",
                        title,
                        published_at,
                        str(collided_path),
                        now,
                    ),
                )
            await store._db.commit()  # noqa: SLF001

            app = create_app(data_dir=tmp_path, store=store, skip_lifespan=True)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/v1/events/feed", params={"target_id": "italy"})

            assert resp.status_code == 200
            events = resp.json()["groups"][0]["events"]
            assert [item["event_id"] for item in events] == [event_one, event_two]
            assert events[0]["title_original"] == "Primo evento solo in indice"
            assert events[1]["title_original"] == "Secondo evento reale"
        finally:
            await store.close()

    async def test_events_feed_skips_draft_index_rows_that_point_to_archive(
        self,
        tmp_path: Path,
    ) -> None:
        """公开 feed 不应展示已移入 archive 但仍残留为 drafts 索引的事件。"""
        from httpx import ASGITransport, AsyncClient

        store = AsyncStore(tmp_path / "state.db")
        await store.initialize()
        drafts_dir = tmp_path / "italy" / "drafts"
        archive_dir = tmp_path / "italy" / "archive"
        drafts_dir.mkdir(parents=True, exist_ok=True)
        archive_dir.mkdir(parents=True, exist_ok=True)
        draft_event = "ne-italy-ansa-20260528-draft001"
        archived_event = "ne-italy-ansa-20260528-arch0001"

        draft_path = drafts_dir / f"{draft_event}.md"
        archive_path = archive_dir / f"rejected_ansa_{archived_event}.md"
        for path, event_id, title in (
            (draft_path, draft_event, "Evento ancora in bozza"),
            (archive_path, archived_event, "Evento archiviato"),
        ):
            fm = yaml.dump(
                {
                    "id": event_id,
                    "source_id": "ansa",
                    "url": f"https://example.com/{event_id}",
                    "title_original": title,
                    "published_at": "2026-05-28T09:00:00+00:00",
                    "news_value_score": 80,
                    "classification": {"l0": "politics"},
                    "pipeline_stage": "outputted",
                },
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )
            path.write_text(f"---\n{fm}---\n\n# {title}\n", encoding="utf-8")

        now = datetime.now(UTC).isoformat()
        try:
            for event_id, title, file_path in (
                (draft_event, "Evento ancora in bozza", draft_path),
                (archived_event, "Evento archiviato", archive_path),
            ):
                await store._db.execute(  # noqa: SLF001
                    "INSERT OR REPLACE INTO event_index "
                    "(event_id, target_id, stage, source_id, news_value_score, "
                    "china_relevance, classification_l0, title_original, "
                    "published_at, file_path, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        event_id,
                        "italy",
                        "drafts",
                        "ansa",
                        80,
                        None,
                        "politics",
                        title,
                        "2026-05-28T09:00:00+00:00",
                        str(file_path),
                        now,
                    ),
                )
            await store._db.commit()  # noqa: SLF001

            app = create_app(data_dir=tmp_path, store=store, skip_lifespan=True)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/v1/events/feed", params={"target_id": "italy"})

            assert resp.status_code == 200
            events = resp.json()["groups"][0]["events"]
            assert [item["event_id"] for item in events] == [draft_event]
        finally:
            await store.close()

    async def test_events_feed_backfills_page_after_skipping_stale_archive_rows(
        self,
        tmp_path: Path,
    ) -> None:
        """分页前应过滤不可见索引，避免 page 1 被 stale archive 行占满。"""
        from httpx import ASGITransport, AsyncClient

        store = AsyncStore(tmp_path / "state.db")
        await store.initialize()
        drafts_dir = tmp_path / "italy" / "drafts"
        archive_dir = tmp_path / "italy" / "archive"
        drafts_dir.mkdir(parents=True, exist_ok=True)
        archive_dir.mkdir(parents=True, exist_ok=True)
        archived_event = "ne-italy-ansa-20260528-arch0001"
        draft_event = "ne-italy-ansa-20260528-draft001"
        archive_path = archive_dir / f"rejected_ansa_{archived_event}.md"
        draft_path = drafts_dir / f"{draft_event}.md"

        for path, event_id, title, published_at in (
            (
                archive_path,
                archived_event,
                "Evento archiviato piu recente",
                "2026-05-28T10:00:00+00:00",
            ),
            (draft_path, draft_event, "Evento visibile", "2026-05-28T09:00:00+00:00"),
        ):
            fm = yaml.dump(
                {
                    "id": event_id,
                    "source_id": "ansa",
                    "url": f"https://example.com/{event_id}",
                    "title_original": title,
                    "published_at": published_at,
                    "news_value_score": 80,
                    "classification": {"l0": "politics"},
                    "pipeline_stage": "outputted",
                },
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )
            path.write_text(f"---\n{fm}---\n\n# {title}\n", encoding="utf-8")

        now = datetime.now(UTC).isoformat()
        try:
            for event_id, title, published_at, file_path in (
                (
                    archived_event,
                    "Evento archiviato piu recente",
                    "2026-05-28T10:00:00+00:00",
                    archive_path,
                ),
                (draft_event, "Evento visibile", "2026-05-28T09:00:00+00:00", draft_path),
            ):
                await store._db.execute(  # noqa: SLF001
                    "INSERT OR REPLACE INTO event_index "
                    "(event_id, target_id, stage, source_id, news_value_score, "
                    "china_relevance, classification_l0, title_original, "
                    "published_at, file_path, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        event_id,
                        "italy",
                        "drafts",
                        "ansa",
                        80,
                        None,
                        "politics",
                        title,
                        published_at,
                        str(file_path),
                        now,
                    ),
                )
            await store._db.commit()  # noqa: SLF001

            app = create_app(data_dir=tmp_path, store=store, skip_lifespan=True)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/api/v1/events/feed",
                    params={"target_id": "italy", "page": 1, "page_size": 1},
                )

            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 1
            events = data["groups"][0]["events"]
            assert [item["event_id"] for item in events] == [draft_event]
        finally:
            await store.close()

    async def test_events_feed_backfills_across_index_batches(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """可见分页必须跨批次查找，不能被单批候选行上限截断。"""
        from httpx import ASGITransport, AsyncClient

        store = AsyncStore(tmp_path / "state.db")
        await store.initialize()
        original_query = store.query_events_paginated

        async def capped_query_events_paginated(*args, **kwargs):
            kwargs["limit"] = 1
            return await original_query(*args, **kwargs)

        monkeypatch.setattr(store, "query_events_paginated", capped_query_events_paginated)
        drafts_dir = tmp_path / "italy" / "drafts"
        archive_dir = tmp_path / "italy" / "archive"
        drafts_dir.mkdir(parents=True, exist_ok=True)
        archive_dir.mkdir(parents=True, exist_ok=True)
        archived_event = "ne-italy-ansa-20260528-arch0001"
        draft_event = "ne-italy-ansa-20260528-draft001"
        archive_path = archive_dir / f"rejected_ansa_{archived_event}.md"
        draft_path = drafts_dir / f"{draft_event}.md"

        for path, event_id, title, published_at in (
            (
                archive_path,
                archived_event,
                "Evento archiviato piu recente",
                "2026-05-28T10:00:00+00:00",
            ),
            (draft_path, draft_event, "Evento visibile", "2026-05-28T09:00:00+00:00"),
        ):
            fm = yaml.dump(
                {
                    "id": event_id,
                    "source_id": "ansa",
                    "url": f"https://example.com/{event_id}",
                    "title_original": title,
                    "published_at": published_at,
                    "news_value_score": 80,
                    "classification": {"l0": "politics"},
                    "pipeline_stage": "outputted",
                },
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )
            path.write_text(f"---\n{fm}---\n\n# {title}\n", encoding="utf-8")

        now = datetime.now(UTC).isoformat()
        try:
            for event_id, title, published_at, file_path in (
                (
                    archived_event,
                    "Evento archiviato piu recente",
                    "2026-05-28T10:00:00+00:00",
                    archive_path,
                ),
                (draft_event, "Evento visibile", "2026-05-28T09:00:00+00:00", draft_path),
            ):
                await store._db.execute(  # noqa: SLF001
                    "INSERT OR REPLACE INTO event_index "
                    "(event_id, target_id, stage, source_id, news_value_score, "
                    "china_relevance, classification_l0, title_original, "
                    "published_at, file_path, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        event_id,
                        "italy",
                        "drafts",
                        "ansa",
                        80,
                        None,
                        "politics",
                        title,
                        published_at,
                        str(file_path),
                        now,
                    ),
                )
            await store._db.commit()  # noqa: SLF001

            app = create_app(data_dir=tmp_path, store=store, skip_lifespan=True)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/api/v1/events/feed",
                    params={"target_id": "italy", "page": 1, "page_size": 1},
                )

            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 1
            assert data["groups"][0]["events"][0]["event_id"] == draft_event
        finally:
            await store.close()

    async def test_visible_index_page_can_skip_exact_total_for_public_feed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """公开新闻流首屏不应为计算总数而扫描全部历史索引行。"""

        class CountingStore:
            def __init__(self) -> None:
                self.calls: list[tuple[int, int]] = []

            async def query_events_paginated(self, **kwargs: Any) -> dict[str, Any]:
                limit = kwargs["limit"]
                offset = kwargs["offset"]
                self.calls.append((limit, offset))
                rows = [
                    {
                        "event_id": f"event-{idx}",
                        "source_id": "ansa",
                        "news_value_score": 80,
                        "china_relevance": 0,
                        "classification_l0": "politics",
                        "published_at": f"2026-05-28T10:{idx % 60:02d}:00+00:00",
                        "file_path": None,
                        "title_original": f"Evento {idx}",
                    }
                    for idx in range(offset, min(offset + limit, 2500))
                ]
                return {"total": 2500, "rows": rows}

        from news_sentry.core import target_store_utils

        materialized = 0
        original = target_store_utils._visible_index_event_from_row

        def count_materialized(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
            nonlocal materialized
            materialized += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(
            target_store_utils,
            "_visible_index_event_from_row",
            count_materialized,
        )

        store = CountingStore()
        result = await target_store_utils._visible_index_events_page(
            store,
            tmp_path,
            "italy",
            stage="drafts",
            page=1,
            page_size=30,
            exact_total=False,
        )

        assert result["total"] == 2500
        assert [item["event_id"] for item in result["events"]] == [
            f"event-{idx}" for idx in range(30)
        ]
        assert materialized == 30
        assert store.calls == [(30, 0)]

    async def test_visible_index_page_uses_index_row_when_file_path_missing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """无 Markdown 输出的索引事件不应反复扫描 drafts 目录找回文件。"""

        class IndexOnlyStore:
            async def query_events_paginated(self, **kwargs: Any) -> dict[str, Any]:
                return {
                    "total": 1,
                    "rows": [
                        {
                            "event_id": "evt-index-only",
                            "source_id": "ansa",
                            "news_value_score": 80,
                            "china_relevance": 0,
                            "classification_l0": "economy",
                            "published_at": "2026-05-31T00:00:00+00:00",
                            "file_path": None,
                            "title_original": "Index only event",
                        }
                    ],
                }

        def fail_stage_scan(*args: Any, **kwargs: Any) -> None:
            raise AssertionError("missing file_path rows should render from index")

        monkeypatch.setattr(
            api_server_module,
            "_load_event_by_id_from_stage",
            fail_stage_scan,
        )

        result = await api_server_module._visible_index_events_page(
            IndexOnlyStore(),
            tmp_path,
            "italy",
            stage="drafts",
            page=1,
            page_size=1,
            exact_total=False,
        )

        assert result["events"][0]["event_id"] == "evt-index-only"

    def test_target_info_from_config_does_not_scan_event_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Target 列表响应基础信息不应同步扫全量事件文件。"""

        def fail_load_all_events(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
            raise AssertionError("_load_all_events should not be used for target info")

        monkeypatch.setattr(api_server_module, "_load_all_events", fail_load_all_events)
        info = api_server_module._target_info_from_config(
            {
                "target_id": "italy",
                "display_name": "意大利新闻监控",
                "language_scope": {"primary": "it"},
                "source_channel_refs": ["rss/ansa.yaml"],
            },
            tmp_path,
        )

        assert info.target_id == "italy"
        assert info.source_count == 1
        assert info.event_count == 0

    async def test_event_detail_does_not_reuse_collided_file_path_frontmatter(
        self,
        tmp_path: Path,
    ) -> None:
        """详情接口遇到 file_path 碰撞时，应返回请求 event_id 的索引信息。"""
        from httpx import ASGITransport, AsyncClient

        store = AsyncStore(tmp_path / "state.db")
        await store.initialize()
        drafts_dir = tmp_path / "italy" / "drafts"
        drafts_dir.mkdir(parents=True, exist_ok=True)
        requested_event = "ne-italy-ansa-20260528-aaa11111"
        other_event = "ne-italy-ansa-20260528-bbb22222"
        collided_path = drafts_dir / "2026-05-28-ansa-ne-italy-ans.md"
        fm = yaml.dump(
            {
                "id": other_event,
                "source_id": "ansa",
                "url": "https://example.com/two",
                "title_original": "Secondo evento reale",
                "published_at": "2026-05-28T09:00:00+00:00",
                "news_value_score": 80,
                "classification": {"l0": "politics"},
                "pipeline_stage": "outputted",
            },
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
        collided_path.write_text(f"---\n{fm}---\n\n# Secondo evento reale\n", encoding="utf-8")
        now = datetime.now(UTC).isoformat()
        try:
            for event_id, title, published_at, score in (
                (requested_event, "Primo evento solo in indice", "2026-05-28T10:00:00+00:00", 70),
                (other_event, "Secondo evento reale", "2026-05-28T09:00:00+00:00", 80),
            ):
                await store._db.execute(  # noqa: SLF001
                    "INSERT OR REPLACE INTO event_index "
                    "(event_id, target_id, stage, source_id, news_value_score, "
                    "china_relevance, classification_l0, title_original, "
                    "published_at, file_path, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        event_id,
                        "italy",
                        "drafts",
                        "ansa",
                        score,
                        None,
                        "politics",
                        title,
                        published_at,
                        str(collided_path),
                        now,
                    ),
                )
            await store._db.commit()  # noqa: SLF001

            app = create_app(data_dir=tmp_path, store=store, skip_lifespan=True)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    f"/api/v1/events/{requested_event}",
                    params={"target_id": "italy"},
                )

            assert resp.status_code == 200
            data = resp.json()
            assert (data.get("event_id") or data.get("id")) == requested_event
            assert data["title_original"] == "Primo evento solo in indice"
        finally:
            await store.close()

    async def test_event_detail_rejects_non_draft_index_rows(
        self,
        tmp_path: Path,
    ) -> None:
        """公开详情不得从 raw/archive 索引行返回事件。"""
        from httpx import ASGITransport, AsyncClient

        store = AsyncStore(tmp_path / "state.db")
        await store.initialize()
        archive_dir = tmp_path / "italy" / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        event_id = "ne-italy-ansa-20260528-arch0001"
        archive_path = archive_dir / f"rejected_ansa_{event_id}.md"
        fm = yaml.dump(
            {
                "id": event_id,
                "source_id": "ansa",
                "url": "https://example.com/archive",
                "title_original": "Evento archiviato",
                "published_at": "2026-05-28T09:00:00+00:00",
                "pipeline_stage": "outputted",
            },
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
        archive_path.write_text(f"---\n{fm}---\n\n# Evento archiviato\n", encoding="utf-8")
        now = datetime.now(UTC).isoformat()
        try:
            await store._db.execute(  # noqa: SLF001
                "INSERT OR REPLACE INTO event_index "
                "(event_id, target_id, stage, source_id, title_original, "
                "published_at, file_path, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id,
                    "italy",
                    "archive",
                    "ansa",
                    "Evento archiviato",
                    "2026-05-28T09:00:00+00:00",
                    str(archive_path),
                    now,
                ),
            )
            await store._db.commit()  # noqa: SLF001

            app = create_app(data_dir=tmp_path, store=store, skip_lifespan=True)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    f"/api/v1/events/{event_id}",
                    params={"target_id": "italy"},
                )

            assert resp.status_code == 404
        finally:
            await store.close()

    async def test_event_detail_rejects_stale_draft_row_pointing_to_archive(
        self,
        tmp_path: Path,
    ) -> None:
        """drafts 残留索引若指向 archive 文件，详情也不可公开返回。"""
        from httpx import ASGITransport, AsyncClient

        store = AsyncStore(tmp_path / "state.db")
        await store.initialize()
        archive_dir = tmp_path / "italy" / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        event_id = "ne-italy-ansa-20260528-arch0001"
        archive_path = archive_dir / f"rejected_ansa_{event_id}.md"
        fm = yaml.dump(
            {
                "id": event_id,
                "source_id": "ansa",
                "url": "https://example.com/archive",
                "title_original": "Evento archiviato",
                "published_at": "2026-05-28T09:00:00+00:00",
                "pipeline_stage": "outputted",
            },
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
        archive_path.write_text(f"---\n{fm}---\n\n# Evento archiviato\n", encoding="utf-8")
        now = datetime.now(UTC).isoformat()
        try:
            await store._db.execute(  # noqa: SLF001
                "INSERT OR REPLACE INTO event_index "
                "(event_id, target_id, stage, source_id, title_original, "
                "published_at, file_path, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id,
                    "italy",
                    "drafts",
                    "ansa",
                    "Evento archiviato",
                    "2026-05-28T09:00:00+00:00",
                    str(archive_path),
                    now,
                ),
            )
            await store._db.commit()  # noqa: SLF001

            app = create_app(data_dir=tmp_path, store=store, skip_lifespan=True)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    f"/api/v1/events/{event_id}",
                    params={"target_id": "italy"},
                )

            assert resp.status_code == 404
        finally:
            await store.close()

    async def test_event_detail_rejects_missing_archive_path_index_row(
        self,
        tmp_path: Path,
    ) -> None:
        """即便 archive 文件已被清理，file_path 字符串仍不可作为公开详情兜底。"""
        from httpx import ASGITransport, AsyncClient

        store = AsyncStore(tmp_path / "state.db")
        await store.initialize()
        drafts_dir = tmp_path / "italy" / "drafts"
        archive_dir = tmp_path / "italy" / "archive"
        drafts_dir.mkdir(parents=True, exist_ok=True)
        archive_dir.mkdir(parents=True, exist_ok=True)
        event_id = "ne-italy-ansa-20260528-arch0001"
        draft_path = drafts_dir / f"{event_id}.md"
        archive_path = archive_dir / f"rejected_ansa_{event_id}.md"
        fm = yaml.dump(
            {
                "id": event_id,
                "source_id": "ansa",
                "url": "https://example.com/archive",
                "title_original": "Residuo in drafts da non usare",
                "published_at": "2026-05-28T09:00:00+00:00",
                "pipeline_stage": "outputted",
            },
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
        draft_path.write_text(
            f"---\n{fm}---\n\n# Residuo in drafts da non usare\n",
            encoding="utf-8",
        )
        now = datetime.now(UTC).isoformat()
        try:
            await store._db.execute(  # noqa: SLF001
                "INSERT OR REPLACE INTO event_index "
                "(event_id, target_id, stage, source_id, title_original, "
                "published_at, file_path, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id,
                    "italy",
                    "drafts",
                    "ansa",
                    "Evento archiviato",
                    "2026-05-28T09:00:00+00:00",
                    str(archive_path),
                    now,
                ),
            )
            await store._db.commit()  # noqa: SLF001

            app = create_app(data_dir=tmp_path, store=store, skip_lifespan=True)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    f"/api/v1/events/{event_id}",
                    params={"target_id": "italy"},
                )

            assert resp.status_code == 404
        finally:
            await store.close()

    async def test_event_detail_does_not_fallback_when_non_draft_index_row_exists(
        self,
        tmp_path: Path,
    ) -> None:
        """非 drafts 索引命中时禁止继续扫描 drafts 残留文件。"""
        from httpx import ASGITransport, AsyncClient

        store = AsyncStore(tmp_path / "state.db")
        await store.initialize()
        drafts_dir = tmp_path / "italy" / "drafts"
        archive_dir = tmp_path / "italy" / "archive"
        drafts_dir.mkdir(parents=True, exist_ok=True)
        archive_dir.mkdir(parents=True, exist_ok=True)
        event_id = "ne-italy-ansa-20260528-arch0001"
        draft_path = drafts_dir / f"{event_id}.md"
        archive_path = archive_dir / f"rejected_ansa_{event_id}.md"
        fm = yaml.dump(
            {
                "id": event_id,
                "source_id": "ansa",
                "url": "https://example.com/archive",
                "title_original": "Residuo in drafts da non usare",
                "published_at": "2026-05-28T09:00:00+00:00",
                "pipeline_stage": "outputted",
            },
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
        draft_path.write_text(
            f"---\n{fm}---\n\n# Residuo in drafts da non usare\n",
            encoding="utf-8",
        )
        archive_path.write_text(f"---\n{fm}---\n\n# Archive\n", encoding="utf-8")
        now = datetime.now(UTC).isoformat()
        try:
            await store._db.execute(  # noqa: SLF001
                "INSERT OR REPLACE INTO event_index "
                "(event_id, target_id, stage, source_id, title_original, "
                "published_at, file_path, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id,
                    "italy",
                    "archive",
                    "ansa",
                    "Evento archiviato",
                    "2026-05-28T09:00:00+00:00",
                    str(archive_path),
                    now,
                ),
            )
            await store._db.commit()  # noqa: SLF001

            app = create_app(data_dir=tmp_path, store=store, skip_lifespan=True)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    f"/api/v1/events/{event_id}",
                    params={"target_id": "italy"},
                )

            assert resp.status_code == 404
        finally:
            await store.close()

    async def test_event_detail_does_not_fallback_for_unindexed_stale_draft(
        self,
        tmp_path: Path,
    ) -> None:
        """target 有任意索引后，详情不可返回未入索引的 drafts 残留文件。"""
        from httpx import ASGITransport, AsyncClient

        store = AsyncStore(tmp_path / "state.db")
        await store.initialize()
        drafts_dir = tmp_path / "italy" / "drafts"
        drafts_dir.mkdir(parents=True, exist_ok=True)
        indexed_event = "ne-italy-ansa-20260528-indexed01"
        stale_event = "ne-italy-ansa-20260528-stale001"
        stale_path = drafts_dir / f"{stale_event}.md"
        fm = yaml.dump(
            {
                "id": stale_event,
                "source_id": "ansa",
                "url": "https://example.com/stale",
                "title_original": "Residuo non indicizzato",
                "published_at": "2026-05-28T09:00:00+00:00",
                "pipeline_stage": "outputted",
            },
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
        stale_path.write_text(
            f"---\n{fm}---\n\n# Residuo non indicizzato\n",
            encoding="utf-8",
        )
        now = datetime.now(UTC).isoformat()
        try:
            await store._db.execute(  # noqa: SLF001
                "INSERT OR REPLACE INTO event_index "
                "(event_id, target_id, stage, source_id, title_original, "
                "published_at, file_path, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    indexed_event,
                    "italy",
                    "drafts",
                    "ansa",
                    "Evento indicizzato",
                    "2026-05-28T10:00:00+00:00",
                    str(drafts_dir / f"{indexed_event}.md"),
                    now,
                ),
            )
            await store._db.commit()  # noqa: SLF001

            app = create_app(data_dir=tmp_path, store=store, skip_lifespan=True)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    f"/api/v1/events/{stale_event}",
                    params={"target_id": "italy"},
                )

            assert resp.status_code == 404
        finally:
            await store.close()

    async def test_list_events_does_not_fallback_to_drafts_when_only_archive_index_exists(
        self,
        tmp_path: Path,
    ) -> None:
        """target 有非 drafts 索引时，列表不可回退扫描 drafts 残留文件。"""
        from httpx import ASGITransport, AsyncClient

        store = AsyncStore(tmp_path / "state.db")
        await store.initialize()
        drafts_dir = tmp_path / "italy" / "drafts"
        archive_dir = tmp_path / "italy" / "archive"
        drafts_dir.mkdir(parents=True, exist_ok=True)
        archive_dir.mkdir(parents=True, exist_ok=True)
        event_id = "ne-italy-ansa-20260528-arch0001"
        draft_path = drafts_dir / f"{event_id}.md"
        archive_path = archive_dir / f"rejected_ansa_{event_id}.md"
        fm = yaml.dump(
            {
                "id": event_id,
                "source_id": "ansa",
                "url": "https://example.com/archive",
                "title_original": "Residuo in drafts da non usare",
                "published_at": "2026-05-28T09:00:00+00:00",
                "pipeline_stage": "outputted",
            },
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
        draft_path.write_text(
            f"---\n{fm}---\n\n# Residuo in drafts da non usare\n",
            encoding="utf-8",
        )
        now = datetime.now(UTC).isoformat()
        try:
            await store._db.execute(  # noqa: SLF001
                "INSERT OR REPLACE INTO event_index "
                "(event_id, target_id, stage, source_id, title_original, "
                "published_at, file_path, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id,
                    "italy",
                    "archive",
                    "ansa",
                    "Evento archiviato",
                    "2026-05-28T09:00:00+00:00",
                    str(archive_path),
                    now,
                ),
            )
            await store._db.commit()  # noqa: SLF001

            app = create_app(data_dir=tmp_path, store=store, skip_lifespan=True)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/v1/events", params={"target_id": "italy"})

            assert resp.status_code == 200
            assert resp.json()["total"] == 0
        finally:
            await store.close()

    async def test_feed_does_not_fallback_to_drafts_when_only_archive_index_exists(
        self,
        tmp_path: Path,
    ) -> None:
        """target 有非 drafts 索引时，feed 不可回退扫描 drafts 残留文件。"""
        from httpx import ASGITransport, AsyncClient

        store = AsyncStore(tmp_path / "state.db")
        await store.initialize()
        drafts_dir = tmp_path / "italy" / "drafts"
        archive_dir = tmp_path / "italy" / "archive"
        drafts_dir.mkdir(parents=True, exist_ok=True)
        archive_dir.mkdir(parents=True, exist_ok=True)
        event_id = "ne-italy-ansa-20260528-arch0001"
        draft_path = drafts_dir / f"{event_id}.md"
        archive_path = archive_dir / f"rejected_ansa_{event_id}.md"
        fm = yaml.dump(
            {
                "id": event_id,
                "source_id": "ansa",
                "url": "https://example.com/archive",
                "title_original": "Residuo in drafts da non usare",
                "published_at": "2026-05-28T09:00:00+00:00",
                "pipeline_stage": "outputted",
            },
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
        draft_path.write_text(
            f"---\n{fm}---\n\n# Residuo in drafts da non usare\n",
            encoding="utf-8",
        )
        now = datetime.now(UTC).isoformat()
        try:
            await store._db.execute(  # noqa: SLF001
                "INSERT OR REPLACE INTO event_index "
                "(event_id, target_id, stage, source_id, title_original, "
                "published_at, file_path, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id,
                    "italy",
                    "archive",
                    "ansa",
                    "Evento archiviato",
                    "2026-05-28T09:00:00+00:00",
                    str(archive_path),
                    now,
                ),
            )
            await store._db.commit()  # noqa: SLF001

            app = create_app(data_dir=tmp_path, store=store, skip_lifespan=True)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/v1/events/feed", params={"target_id": "italy"})

            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 0
            assert data["groups"] == []
        finally:
            await store.close()

    async def test_list_events_pagination_with_sqlite(
        self,
        client_with_store,
    ) -> None:
        client, _ = client_with_store
        resp = await client.get(
            "/api/v1/events",
            params={"target_id": "italy", "page": 1, "page_size": 2},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["events"]) == 2
        assert data["page"] == 1

    async def test_list_events_filter_source_with_sqlite(
        self,
        client_with_store,
    ) -> None:
        client, _ = client_with_store
        resp = await client.get(
            "/api/v1/events",
            params={"target_id": "italy", "source_id": "ansa"},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    async def test_list_events_filter_classification_with_sqlite(
        self,
        client_with_store,
    ) -> None:
        client, _ = client_with_store
        resp = await client.get(
            "/api/v1/events",
            params={"target_id": "italy", "classification": "politics"},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    async def test_list_events_filter_min_score_with_sqlite(
        self,
        client_with_store,
    ) -> None:
        client, _ = client_with_store
        resp = await client.get(
            "/api/v1/events",
            params={"target_id": "italy", "min_score": 70},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    async def test_list_events_search_with_sqlite(
        self,
        client_with_store,
    ) -> None:
        client, _ = client_with_store
        resp = await client.get(
            "/api/v1/events",
            params={"target_id": "italy", "search": "pace"},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    async def test_get_single_event_with_sqlite(
        self,
        client_with_store,
    ) -> None:
        client, _ = client_with_store
        resp = await client.get(
            "/api/v1/events/ne-italy-ansa-20260512-aaa11111",
            params={"target_id": "italy"},
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == "ne-italy-ansa-20260512-aaa11111"

    async def test_get_single_event_not_found_with_sqlite(
        self,
        client_with_store,
    ) -> None:
        client, _ = client_with_store
        resp = await client.get(
            "/api/v1/events/nonexistent",
            params={"target_id": "italy"},
        )
        assert resp.status_code == 404

    async def test_events_filter_by_sentiment_with_sqlite(
        self,
        client_with_store,
    ) -> None:
        """按 sentiment 过滤事件。"""
        client, _ = client_with_store
        resp = await client.get(
            "/api/v1/events",
            params={
                "target_id": "italy",
                "sentiment": "negative",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert "Elezioni" in data["events"][0]["title_original"]

    async def test_events_filter_by_entity_with_sqlite(
        self,
        client_with_store,
    ) -> None:
        """按 entity 过滤事件。"""
        client, _ = client_with_store
        resp = await client.get(
            "/api/v1/events",
            params={
                "target_id": "italy",
                "entity": "Meloni",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1

    async def test_events_filter_by_topic_tag_with_sqlite(
        self,
        client_with_store,
    ) -> None:
        """按 topic_tag 过滤事件。"""
        client, _ = client_with_store
        resp = await client.get(
            "/api/v1/events",
            params={
                "target_id": "italy",
                "topic_tag": "peace",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert "Pace" in data["events"][0]["title_original"]

    async def test_stats_sentiment_breakdown_with_sqlite(
        self,
        client_with_store,
    ) -> None:
        """stats 端点返回 sentiment_breakdown。"""
        client, _ = client_with_store
        resp = await client.get(
            "/api/v1/stats",
            params={"target_id": "italy"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "sentiment_breakdown" in data
        sb = data["sentiment_breakdown"]
        assert sb.get("positive") == 1
        assert sb.get("negative") == 1
        assert sb.get("neutral") == 1

    async def test_list_entities_with_sqlite(
        self,
        client_with_store,
    ) -> None:
        """GET /entities 返回实体列表。"""
        client, store = client_with_store
        await store.upsert_entity("Meloni", "person", "italy", "2026-05-16T10:00:00+00:00")
        await store.upsert_entity("EU", "organization", "italy", "2026-05-16T10:00:00+00:00")
        resp = await client.get("/api/v1/entities")
        assert resp.status_code == 200
        data = resp.json()
        assert "entities" in data
        assert data["total"] == 2

    async def test_list_entities_filter_by_type(
        self,
        client_with_store,
    ) -> None:
        """GET /entities?entity_type=person 过滤。"""
        client, store = client_with_store
        await store.upsert_entity("Meloni", "person", "italy", "2026-05-16T10:00:00+00:00")
        await store.upsert_entity("EU", "organization", "italy", "2026-05-16T10:00:00+00:00")
        client, _ = client_with_store
        resp = await client.get("/api/v1/entities", params={"entity_type": "person"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["entities"][0]["canonical_name"] == "Meloni"

    async def test_list_entities_min_mentions(
        self,
        client_with_store,
    ) -> None:
        """GET /entities?min_mentions=2 过滤低频实体。"""
        client, store = client_with_store
        await store.upsert_entity("Meloni", "person", "italy", "2026-05-16T10:00:00+00:00")
        await store.upsert_entity("Meloni", "person", "italy", "2026-05-17T10:00:00+00:00")
        await store.upsert_entity("EU", "organization", "italy", "2026-05-16T10:00:00+00:00")
        client, _ = client_with_store
        resp = await client.get("/api/v1/entities", params={"min_mentions": 2})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["entities"][0]["canonical_name"] == "Meloni"

    async def test_get_entity_detail_with_sqlite(
        self,
        client_with_store,
    ) -> None:
        """GET /entities/{id} 返回实体详情。"""
        client, store = client_with_store
        await store.upsert_entity("Meloni", "person", "italy", "2026-05-16T10:00:00+00:00")
        client, _ = client_with_store
        resp = await client.get("/api/v1/entities/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["entity"]["canonical_name"] == "Meloni"
        assert "recent_events" in data

    async def test_stats_top_entities_with_sqlite(
        self,
        client_with_store,
    ) -> None:
        """stats 端点返回 top_entities。"""
        client, store = client_with_store
        await store.upsert_entity("Meloni", "person", "italy", "2026-05-16T10:00:00+00:00")
        client, _ = client_with_store
        resp = await client.get("/api/v1/stats", params={"target_id": "italy"})
        assert resp.status_code == 200
        data = resp.json()
        assert "top_entities" in data
        assert len(data["top_entities"]) >= 1
        assert data["top_entities"][0]["name"] == "Meloni"
