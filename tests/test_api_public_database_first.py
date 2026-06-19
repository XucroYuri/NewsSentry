from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from news_sentry.core import api_server
from news_sentry.core.api_server import create_app


def _ready_translation(
    title: str = "投影标题",
    summary: str = "这是一条中文摘要。",
    one_line: str = "一句话概括这条中文新闻。",
    reason: str = "AI 推荐理由指出这条新闻对跨境观察具有具体影响。",
) -> dict[str, Any]:
    return {
        "translation": {"title_pre": title, "summary_pre": summary},
        "publication": {
            "one_line_summary": one_line,
            "recommendation_reason": reason,
        },
    }


def _merge_metadata(base: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    if not override:
        return base
    merged = {**base, **override}
    if isinstance(base.get("translation"), dict) or isinstance(override.get("translation"), dict):
        merged["translation"] = {
            **(base.get("translation") if isinstance(base.get("translation"), dict) else {}),
            **(
                override.get("translation")
                if isinstance(override.get("translation"), dict)
                else {}
            ),
        }
    if isinstance(base.get("publication"), dict) or isinstance(override.get("publication"), dict):
        merged["publication"] = {
            **(base.get("publication") if isinstance(base.get("publication"), dict) else {}),
            **(
                override.get("publication")
                if isinstance(override.get("publication"), dict)
                else {}
            ),
        }
    return merged


class ProjectionOnlyStore:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def get_target_event_count(self, target_id: str) -> int:
        return sum(1 for row in self._rows if row.get("target_id") == target_id)

    async def query_events_paginated(self, **_: Any) -> dict[str, Any]:
        return {"rows": [], "total": 0}

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
    base_metadata = _ready_translation(
        title=f"中文：{title_original}",
        summary="这是一条已完成中文摘要的投影新闻。",
    )
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
        "metadata": _merge_metadata(base_metadata, metadata),
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
                    "translation": {
                        "title_pre": "投影列表标题",
                        "summary_pre": "投影列表中文摘要",
                    },
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
    assert item["summary"] == "投影列表中文摘要"
    assert item["originalUrl"] == "https://example.com/story"
    assert item["tags"][0] == "international-relations"
    assert item["entities"][0]["name"] == "Meloni"


def test_public_news_list_normalizes_common_gdelt_title_mojibake(
    tmp_path: Path,
    monkeypatch,
) -> None:
    raw_title = (
        "litalia sarÀ sempre al fianco dellucraina - lo ha detto sergio mattarella "
        "a zelensky affinchÉ ..."
    )
    expected_title = (
        "litalia sarà sempre al fianco dellucraina - lo ha detto sergio mattarella "
        "a zelensky affinché ..."
    )
    store = ProjectionOnlyStore(
        [
            _projection_row(
                event_id="ne-italy-projection-list-002",
                source_id="gdelt-italy",
                title_original=raw_title,
                metadata=_ready_translation(
                    title="意大利继续站在乌克兰一边",
                    summary="这条新闻已完成中文摘要。",
                ),
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
    assert item["title"] == "意大利继续站在乌克兰一边"
    assert item["originalTitle"] == expected_title


def test_public_news_list_keeps_indexed_filtered_path_for_selective_reads(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = FilterAwareProjectionStore(
        [
            _projection_row(
                event_id="ne-italy-projection-filter-wrong",
                source_id="wrong-source",
                metadata=_ready_translation(title="不该命中的投影标题"),
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
                    "metadata": _ready_translation(
                        title="索引筛选命中标题",
                        summary="索引筛选命中中文摘要。",
                    ),
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
    assert item["title"] == "索引筛选命中标题"
    assert store.projection_calls == 0


def test_featured_public_news_requires_publication_quality(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = ProjectionOnlyStore([_projection_row(event_id="ne-featured-store-sentinel")])
    app = create_app(data_dir=tmp_path, store=store, auto_store=False, skip_lifespan=True)
    client = TestClient(app)

    async def _fake_visible_index_events_page(*args, **kwargs):
        return {
            "events": [
                {
                    "event_id": "ne-featured-empty-copy",
                    "source_id": "ansa",
                    "title_original": "High score but no public summary",
                    "url": "https://example.com/empty-copy",
                    "published_at": "2026-06-13T12:00:00+00:00",
                    "news_value_score": 99,
                    "china_relevance": 80,
                    "classification": {"l0": "international-relations"},
                },
                {
                    "event_id": "ne-featured-uncategorized",
                    "source_id": "ansa",
                    "title_original": "High score but uncategorized",
                    "judge_result": {"rationale": "A valid reason is also present."},
                    "url": "https://example.com/uncategorized",
                    "published_at": "2026-06-13T11:00:00+00:00",
                    "news_value_score": 95,
                    "china_relevance": 70,
                    "classification": {"l0": "uncategorized"},
                    "metadata": _ready_translation(
                        title="高分但未分类标题",
                        summary="高分但未分类中文摘要。",
                    ),
                },
                {
                    "event_id": "ne-featured-no-reason",
                    "source_id": "ansa",
                    "title_original": "High score but no recommendation reason",
                    "url": "https://example.com/no-reason",
                    "published_at": "2026-06-13T10:00:00+00:00",
                    "news_value_score": 92,
                    "china_relevance": 68,
                    "classification": {"l0": "economy"},
                    "metadata": _ready_translation(
                        title="高分但缺少推荐理由标题",
                        summary="高分但缺少推荐理由中文摘要。",
                        one_line="",
                        reason="",
                    ),
                },
                {
                    "event_id": "ne-featured-qualified",
                    "source_id": "ansa",
                    "title_original": "Qualified cross-border signal",
                    "judge_result": {
                        "rationale": (
                            "The update has a clear operating impact for Chinese exporters."
                        )
                    },
                    "url": "https://example.com/qualified",
                    "published_at": "2026-06-13T09:00:00+00:00",
                    "news_value_score": 88,
                    "china_relevance": 75,
                    "classification": {"l0": "economy"},
                    "metadata": _ready_translation(
                        title="合格的跨境信号",
                        summary="政策变化正在影响跨境经营者。",
                    ),
                },
            ],
            "total": 4,
        }

    monkeypatch.setattr(api_server, "_visible_index_events_page", _fake_visible_index_events_page)
    monkeypatch.setattr(
        api_server,
        "_load_all_events",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not scan files")),
    )

    response = client.get(
        "/api/v1/public/news",
        params={"target_id": "italy", "featured": True, "page_size": 10},
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["id"] for item in items] == ["ne-featured-qualified"]
    assert items[0]["summary"]
    assert items[0]["recommendationReason"]
    assert "uncategorized" not in items[0]["tags"]


def test_public_news_hides_items_without_ai_publication_reason(
    tmp_path: Path,
) -> None:
    store = ProjectionOnlyStore(
        [
            _projection_row(
                event_id="ne-all-news-without-ai-reason",
                title_original="Italian port operators face new customs checks",
                news_value_score=74,
                china_relevance=46,
                classification_l0="economy",
                metadata={
                    "translation": {
                        "title_pre": "意大利港口运营商面临新的海关检查",
                        "summary_pre": "新的海关检查可能拖慢多个港口的跨境货运。",
                    },
                    "publication": {
                        "one_line_summary": "",
                        "recommendation_reason": "",
                    },
                    "source_display_name": "ANSA",
                },
            )
        ]
    )
    app = create_app(data_dir=tmp_path, store=store, auto_store=False, skip_lifespan=True)
    client = TestClient(app)

    response = client.get("/api/v1/public/news", params={"target_id": "italy"})

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_public_news_list_keeps_indexed_path_for_keyword_queries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = FilterAwareProjectionStore(
        [
            _projection_row(
                event_id="ne-italy-projection-q-wrong",
                metadata=_ready_translation(title="不该命中的投影标题"),
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
                    "metadata": _ready_translation(
                        title="关键词查询命中",
                        summary="关键词查询命中的中文摘要。",
                    ),
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
        params={"target_id": "italy", "q": "关键词"},
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["id"] == "ne-italy-index-q-hit"
    assert item["title"] == "关键词查询命中"
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
                    "translation": {
                        "title_pre": "投影详情标题",
                        "summary_pre": "投影详情中文摘要",
                    },
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
    assert item["summary"] == "投影详情中文摘要"
    assert item["originalUrl"] == "https://example.com/story"
    assert item["source"]["id"] == "ansa"
    assert store.direct_row_reads == 1
    assert store.projection_scan_attempted is False
