from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from news_sentry.core import api_server
from news_sentry.core.api_server import create_app


class ProjectionOnlyStore:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def get_target_event_count(self, target_id: str) -> int:
        return sum(1 for row in self._rows if row.get("target_id") == target_id)

    async def query_public_projection_rows(
        self,
        *,
        target_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = self._rows
        if target_id is not None:
            rows = [row for row in rows if row.get("target_id") == target_id]
        return rows[offset : offset + limit]


class DirectRowProjectionDetailStore(ProjectionOnlyStore):
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        super().__init__(rows)
        self.direct_row_reads = 0
        self.projection_scan_attempted = False

    async def get_event_index_row(self, target_id: str, event_id: str) -> dict[str, Any] | None:
        self.direct_row_reads += 1
        for row in self._rows:
            if row.get("target_id") == target_id and row.get("event_id") == event_id:
                return {
                    **row,
                    "stage": "drafts",
                }
        return None

    async def query_public_projection_rows(
        self,
        *,
        target_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        self.projection_scan_attempted = True
        raise AssertionError("should not page-scan projection rows on detail hot path")


class FilterAwareProjectionStore(ProjectionOnlyStore):
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        super().__init__(rows)
        self.projection_calls = 0

    async def query_public_projection_rows(
        self,
        *,
        target_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        self.projection_calls += 1
        return await super().query_public_projection_rows(
            target_id=target_id,
            limit=limit,
            offset=offset,
        )


def _projection_row(
    *,
    event_id: str,
    target_id: str = "italy",
    source_id: str = "ansa",
    title_original: str = "Store title",
    published_at: str = "2026-06-13T09:00:00+00:00",
    news_value_score: int = 83,
    china_relevance: int = 72,
    classification_l0: str = "international-relations",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "target_id": target_id,
        "source_id": source_id,
        "title_original": title_original,
        "url": "https://example.com/story",
        "published_at": published_at,
        "created_at": published_at,
        "news_value_score": news_value_score,
        "china_relevance": china_relevance,
        "classification_l0": classification_l0,
        "metadata": metadata or {},
    }


def test_public_news_list_prefers_projection_rows_over_file_scan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = ProjectionOnlyStore(
        [
            _projection_row(
                event_id="ne-italy-projection-list-001",
                metadata={
                    "summary": "Store-backed list summary",
                    "translation": {"title_pre": "投影列表标题"},
                    "topic_tags": ["europe"],
                    "nlp_entities": [{"name": "Meloni", "type": "person"}],
                    "source_display_name": "ANSA",
                },
            )
        ]
    )
    app = create_app(data_dir=tmp_path, store=store, auto_store=False, skip_lifespan=True)
    client = TestClient(app)
    monkeypatch.setattr(
        api_server,
        "_visible_index_events_page",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not read index page")),
    )
    monkeypatch.setattr(
        api_server,
        "_load_all_events",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not scan files")),
    )

    response = client.get("/api/v1/public/news", params={"target_id": "italy"})

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["id"] == "ne-italy-projection-list-001"
    assert item["title"] == "投影列表标题"
    assert item["summary"] == "Store-backed list summary"
    assert item["originalUrl"] == "https://example.com/story"
    assert item["tags"][0] == "international-relations"
    assert item["entities"][0]["name"] == "Meloni"


def test_public_news_list_keeps_indexed_filtered_path_for_selective_reads(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = FilterAwareProjectionStore(
        [
            _projection_row(
                event_id="ne-italy-projection-filter-wrong",
                source_id="wrong-source",
                metadata={"translation": {"title_pre": "不该命中的投影标题"}},
            )
        ]
    )
    app = create_app(data_dir=tmp_path, store=store, auto_store=False, skip_lifespan=True)
    client = TestClient(app)

    async def _fake_visible_index_events_page(*args, **kwargs):
        return {
            "events": [
                {
                    "event_id": "ne-italy-index-filter-hit",
                    "source_id": "ansa",
                    "title_original": "Indexed filtered title",
                    "url": "https://example.com/indexed-story",
                    "published_at": "2026-06-13T10:00:00+00:00",
                    "news_value_score": 80,
                    "china_relevance": 60,
                    "classification": {"l0": "international-relations"},
                }
            ]
        }

    monkeypatch.setattr(api_server, "_visible_index_events_page", _fake_visible_index_events_page)
    monkeypatch.setattr(
        api_server,
        "_load_all_events",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not scan files")),
    )

    response = client.get(
        "/api/v1/public/news",
        params={"target_id": "italy", "source_id": "ansa"},
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["id"] == "ne-italy-index-filter-hit"
    assert item["title"] == "Indexed filtered title"
    assert store.projection_calls == 0


def test_public_news_list_keeps_indexed_path_for_keyword_queries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = FilterAwareProjectionStore(
        [
            _projection_row(
                event_id="ne-italy-projection-q-wrong",
                metadata={"translation": {"title_pre": "不该命中的投影标题"}},
            )
        ]
    )
    app = create_app(data_dir=tmp_path, store=store, auto_store=False, skip_lifespan=True)
    client = TestClient(app)

    async def _fake_visible_index_events_page(*args, **kwargs):
        return {
            "events": [
                {
                    "event_id": "ne-italy-index-q-hit",
                    "source_id": "ansa",
                    "title_original": "Keyword query match",
                    "url": "https://example.com/indexed-query-story",
                    "published_at": "2026-06-13T10:00:00+00:00",
                    "news_value_score": 80,
                    "china_relevance": 60,
                    "classification": {"l0": "international-relations"},
                }
            ]
        }

    monkeypatch.setattr(api_server, "_visible_index_events_page", _fake_visible_index_events_page)
    monkeypatch.setattr(
        api_server,
        "_load_all_events",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not scan files")),
    )

    response = client.get(
        "/api/v1/public/news",
        params={"target_id": "italy", "q": "keyword"},
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["id"] == "ne-italy-index-q-hit"
    assert item["title"] == "Keyword query match"
    assert store.projection_calls == 0


def test_public_news_detail_prefers_direct_store_row_without_projection_scan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    event_id = "ne-italy-projection-detail-001"
    store = DirectRowProjectionDetailStore(
        [
            _projection_row(
                event_id=event_id,
                metadata={
                    "summary": "Store-backed detail summary",
                    "translation": {"title_pre": "投影详情标题"},
                    "source_display_name": "ANSA",
                },
            )
        ]
    )
    app = create_app(data_dir=tmp_path, store=store, auto_store=False, skip_lifespan=True)
    client = TestClient(app)
    monkeypatch.setattr(
        api_server,
        "_load_single_event",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not read markdown")),
    )

    response = client.get(f"/api/v1/public/news/{event_id}", params={"target_id": "italy"})

    assert response.status_code == 200
    item = response.json()
    assert item["id"] == event_id
    assert item["title"] == "投影详情标题"
    assert item["summary"] == "Store-backed detail summary"
    assert item["originalUrl"] == "https://example.com/story"
    assert item["source"]["id"] == "ansa"
    assert store.direct_row_reads == 1
    assert store.projection_scan_attempted is False
