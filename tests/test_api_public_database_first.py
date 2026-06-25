from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from news_sentry.core import api_server, event_io_utils, target_config_utils
from news_sentry.core.api_server import create_app
from news_sentry.core.public_translation import public_translation_field_hash


def _ready_translation(
    title: str = "投影标题",
    summary: str = "这是一条中文摘要。",
    one_line: str = "一句话概括这条中文新闻。",
    reason: str = "AI 推荐理由指出这条新闻对跨境观察具有具体影响。",
    issue_tags: list[str] | None = None,
    related_tags: list[str] | None = None,
    region_tags: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "translation": {"title_pre": title, "summary_pre": summary},
        "publication": {
            "one_line_summary": one_line,
            "recommendation_reason": reason,
            "issue_tags": issue_tags if issue_tags is not None else ["国际关系"],
            "related_tags": related_tags if related_tags is not None else ["涉欧"],
            "region_tags": region_tags if region_tags is not None else ["意大利"],
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


class EmptyGlobalPublicStore(ProjectionOnlyStore):
    async def query_public_news_rows(self, **_: Any) -> dict[str, Any]:
        return {"rows": [], "total": 0}

    async def get_public_event_counts_by_target(self, stage: str = "drafts") -> dict[str, int]:
        return {}


class TargetReadyProjectionStore(ProjectionOnlyStore):
    async def get_public_event_count(self, target_id: str, stage: str = "drafts") -> int:
        return sum(
            1
            for row in self._rows
            if row.get("target_id") == target_id and api_server._row_publication_ready(row)
        )


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
    # 在 create_app 之前 patch，确保 create_app 内部将 mock 赋给 public_news_utils 延迟绑定变量
    monkeypatch.setattr(
        api_server, "_visible_index_events_page",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not read index page")),
    )
    # 源模块: public_news_utils 内懒加载从 event_io_utils 导入 _load_all_events
    monkeypatch.setattr(
        event_io_utils, "_load_all_events",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not scan files")),
    )

    app = create_app(data_dir=tmp_path, store=store, auto_store=False, skip_lifespan=True)
    client = TestClient(app)

    response = client.get("/api/v1/public/news", params={"target_id": "italy"})

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["id"] == "ne-italy-projection-list-001"
    assert item["title"] == "投影列表标题"
    assert item["summary"] == "投影列表中文摘要"
    assert item["originalUrl"] == "https://example.com/story"
    assert item["tags"][0] == "国际关系"
    assert item["entities"][0]["name"] == "Meloni"


def test_public_bootstrap_returns_cached_reader_payload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = ProjectionOnlyStore(
        [
            _projection_row(
                event_id="ne-italy-bootstrap-001",
                metadata=_ready_translation(
                    title="意大利公共首屏标题",
                    summary="这是一条用于首屏启动的中文摘要。",
                    issue_tags=["外交"],
                    related_tags=["涉欧"],
                    region_tags=["意大利"],
                ),
            )
        ]
    )
    test_config = [
        {
            "target_id": "italy",
            "display_name": "意大利新闻监控",
            "region_type": "country",
            "language_scope": {"primary": "it"},
            "source_channel_refs": ["ansa"],
        }
    ]
    monkeypatch.setattr(api_server, "_load_target_configs", lambda: test_config)
    # 源模块: public_news_utils 内懒加载从 target_config_utils 导入 _load_target_configs
    monkeypatch.setattr(target_config_utils, "_load_target_configs", lambda: test_config)

    app = create_app(data_dir=tmp_path, store=store, auto_store=False, skip_lifespan=True)
    client = TestClient(app)

    response = client.get("/api/v1/public/bootstrap")

    assert response.status_code == 200
    assert "public" in response.headers["cache-control"]
    assert "stale-while-revalidate" in response.headers["cache-control"]
    assert response.headers["etag"].startswith('"public-bootstrap-')
    assert "public-bootstrap" in response.headers["server-timing"]
    payload = response.json()
    assert payload["news"]["items"][0]["title"] == "意大利公共首屏标题"
    assert payload["regions"]["regions"][0]["region_id"] == "italy"
    assert payload["facets"]["issues"] == [{"id": "外交", "label": "外交", "count": 1}]
    assert payload["generatedAt"].endswith("Z")


def test_public_regions_can_include_empty_source_backed_regions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def _fake_public_target_event_counts(_data_dir: Path) -> dict[str, int]:
        return {"italy": 2}

    monkeypatch.setattr(api_server, "_public_target_event_counts", _fake_public_target_event_counts)
    monkeypatch.setattr(
        api_server,
        "_load_target_configs",
        lambda: [
            {
                "target_id": "italy",
                "display_name": "意大利新闻监控",
                "region_type": "country",
                "language_scope": {"primary": "it"},
                "source_channel_refs": ["gdelt-italy"],
            },
            {
                "target_id": "france",
                "display_name": "法国新闻监控",
                "region_type": "country",
                "language_scope": {"primary": "fr"},
                "source_channel_refs": ["gdelt-france"],
            },
            {
                "target_id": "china-watch-en",
                "display_name": "涉中话题监控",
                "monitoring_type": "topic",
                "language_scope": {"primary": "en"},
                "source_channel_refs": ["china-pool"],
            },
        ],
    )
    app = create_app(
        data_dir=tmp_path,
        store=ProjectionOnlyStore([]),
        auto_store=False,
        skip_lifespan=True,
    )
    client = TestClient(app)

    default_regions = client.get("/api/v1/regions")
    expanded_regions = client.get("/api/v1/regions", params={"include_empty": "true"})
    expanded_targets = client.get("/api/v1/targets", params={"include_empty": "true"})

    assert default_regions.status_code == 200
    assert expanded_regions.status_code == 200
    assert expanded_targets.status_code == 200
    assert [item["region_id"] for item in default_regions.json()["regions"]] == ["italy"]
    assert [item["region_id"] for item in expanded_regions.json()["regions"]] == [
        "italy",
        "france",
    ]
    assert [item["target_id"] for item in expanded_targets.json()["targets"]] == [
        "italy",
        "france",
    ]


def test_public_projection_event_preserves_ready_hash_for_fresh_index_row() -> None:
    row = _projection_row(
        event_id="ne-italy-projection-hashed-ready",
        title_original="Fresh source title",
        metadata=_ready_translation(
            title="已加工中文标题",
            summary="已加工中文摘要。",
            one_line="这是一句中文概括。",
            reason="这条新闻的推荐理由来自具体内容判断。",
        ),
    )
    row["metadata"]["publication"]["field_hash"] = public_translation_field_hash(row)

    assert api_server._row_publication_ready(row) is True

    event = api_server._public_projection_event(row)

    assert api_server._row_publication_ready(event) is True


def test_public_news_list_returns_fresh_hashed_projection_rows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    row = _projection_row(
        event_id="ne-italy-projection-list-hashed-ready",
        title_original="Fresh source title",
        metadata=_ready_translation(
            title="已加工中文标题",
            summary="已加工中文摘要。",
            one_line="这是一句中文概括。",
            reason="这条新闻的推荐理由来自具体内容判断。",
        ),
    )
    row["metadata"]["publication"]["field_hash"] = public_translation_field_hash(row)
    store = ProjectionOnlyStore([row])
    # 在 create_app 之前 patch，确保 create_app 内部将 mock 赋给 public_news_utils 延迟绑定变量
    monkeypatch.setattr(
        api_server, "_visible_index_events_page",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not read index page")),
    )
    # 源模块: public_news_utils 内懒加载从 event_io_utils 导入 _load_all_events
    monkeypatch.setattr(
        event_io_utils, "_load_all_events",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not scan files")),
    )

    app = create_app(data_dir=tmp_path, store=store, auto_store=False, skip_lifespan=True)
    client = TestClient(app)

    response = client.get("/api/v1/public/news", params={"target_id": "italy"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [item["id"] for item in body["items"]] == ["ne-italy-projection-list-hashed-ready"]


def test_public_news_all_targets_falls_back_to_target_stores_when_global_store_is_empty(
    tmp_path: Path,
    monkeypatch,
) -> None:
    global_store = EmptyGlobalPublicStore([])
    target_store = TargetReadyProjectionStore(
        [
            _projection_row(
                event_id="ne-canada-ready-target-store-001",
                target_id="canada",
                source_id="globalnews-canada",
                title_original="Ready Canada title",
                metadata=_ready_translation(
                    title="加拿大已公开标题",
                    summary="加拿大已公开摘要。",
                    region_tags=["加拿大", "北美"],
                ),
            )
        ]
    )

    test_config = [
        {
            "target_id": "canada",
            "display_name": "加拿大",
            "language_scope": {"primary": "en"},
            "monitoring_type": "country",
            "source_channel_refs": ["rss:globalnews-canada"],
        }
    ]

    monkeypatch.setattr(api_server, "_load_target_configs", lambda: test_config)
    # 源模块: public_news_utils 内懒加载从 target_config_utils 导入 _load_target_configs
    monkeypatch.setattr(target_config_utils, "_load_target_configs", lambda: test_config)

    async def _fake_target_store(target_id: str):
        assert target_id == "canada"
        return target_store

    monkeypatch.setattr(api_server, "_get_target_store", _fake_target_store)
    app = create_app(data_dir=tmp_path, store=global_store, auto_store=False, skip_lifespan=True)
    client = TestClient(app)

    response = client.get("/api/v1/public/news", params={"page_size": 5})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [item["id"] for item in body["items"]] == ["ne-canada-ready-target-store-001"]
    assert body["items"][0]["title"] == "加拿大已公开标题"


def test_public_targets_and_regions_fall_back_to_target_stores_when_global_store_is_empty(
    tmp_path: Path,
    monkeypatch,
) -> None:
    global_store = EmptyGlobalPublicStore([])
    target_store = TargetReadyProjectionStore(
        [
            _projection_row(
                event_id="ne-canada-ready-region-001",
                target_id="canada",
                source_id="globalnews-canada",
                title_original="Ready Canada title",
                metadata=_ready_translation(
                    title="加拿大地区公开标题",
                    summary="加拿大地区公开摘要。",
                    region_tags=["加拿大", "北美"],
                ),
            )
        ]
    )

    test_config = [
        {
            "target_id": "canada",
            "display_name": "加拿大",
            "language_scope": {"primary": "en"},
            "monitoring_type": "country",
            "source_channel_refs": ["rss:globalnews-canada"],
        }
    ]
    monkeypatch.setattr(
        api_server,
        "_load_target_configs",
        lambda: test_config,
    )
    # 源模块: public_news_utils 内懒加载从 target_config_utils 导入 _load_target_configs
    monkeypatch.setattr(
        target_config_utils, "_load_target_configs", lambda: test_config,
    )

    # _public_target_event_counts 是 async 函数,必须用 async mock
    async def _fake_public_target_event_counts(data_dir):
        return {"canada": 1}

    monkeypatch.setattr(
        api_server, "_public_target_event_counts", _fake_public_target_event_counts,
    )

    async def _fake_target_store(target_id: str):
        assert target_id == "canada"
        return target_store

    monkeypatch.setattr(api_server, "_get_target_store", _fake_target_store)
    app = create_app(data_dir=tmp_path, store=global_store, auto_store=False, skip_lifespan=True)
    client = TestClient(app)

    targets_response = client.get("/api/v1/targets")
    regions_response = client.get("/api/v1/regions")

    assert targets_response.status_code == 200
    assert regions_response.status_code == 200
    assert [item["target_id"] for item in targets_response.json()["targets"]] == ["canada"]
    assert targets_response.json()["targets"][0]["event_count"] == 1
    assert [item["region_id"] for item in regions_response.json()["regions"]] == ["canada"]
    assert regions_response.json()["regions"][0]["event_count"] == 1


def test_public_regions_and_targets_hide_topic_targets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    test_config = [
        {
            "target_id": "italy",
            "display_name": "意大利新闻监控",
            "region_type": "country",
            "language_scope": {"primary": "it"},
            "source_channel_refs": ["ansa"],
        },
        {
            "target_id": "energy-transition",
            "display_name": "能源转型观察",
            "monitoring_type": "topic",
            "language_scope": {"primary": "en"},
            "source_channel_refs": ["api/gdelt-topic"],
        },
    ]
    monkeypatch.setattr(api_server, "_load_target_configs", lambda: test_config)
    # 源模块: public_news_utils 内懒加载从 target_config_utils 导入 _load_target_configs
    monkeypatch.setattr(target_config_utils, "_load_target_configs", lambda: test_config)

    async def _fake_counts(_data_dir: Path) -> dict[str, int]:
        return {"italy": 3, "energy-transition": 7}

    monkeypatch.setattr(api_server, "_public_target_event_counts", _fake_counts)
    app = create_app(
        data_dir=tmp_path,
        store=EmptyGlobalPublicStore([]),
        auto_store=False,
        skip_lifespan=True,
    )
    client = TestClient(app)

    regions_response = client.get("/api/v1/regions")
    targets_response = client.get("/api/v1/targets")

    assert regions_response.status_code == 200
    assert targets_response.status_code == 200
    assert [item["region_id"] for item in regions_response.json()["regions"]] == ["italy"]
    assert regions_response.json()["regions"][0]["region_type"] == "country"
    assert [item["target_id"] for item in targets_response.json()["targets"]] == ["italy"]


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
    # 在 create_app 之前 patch，确保 create_app 内部将 mock 赋给 public_news_utils 延迟绑定变量
    monkeypatch.setattr(
        api_server, "_visible_index_events_page",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not read index page")),
    )
    # 源模块: public_news_utils 内懒加载从 event_io_utils 导入 _load_all_events
    monkeypatch.setattr(
        event_io_utils, "_load_all_events",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not scan files")),
    )

    app = create_app(data_dir=tmp_path, store=store, auto_store=False, skip_lifespan=True)
    client = TestClient(app)

    response = client.get("/api/v1/public/news", params={"target_id": "italy"})

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["title"] == "意大利继续站在乌克兰一边"
    assert item["originalTitle"] == expected_title


def test_public_facets_and_news_filter_use_publication_tags(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = ProjectionOnlyStore(
        [
            _projection_row(
                event_id="ne-italy-tech-china",
                target_id="italy",
                metadata=_ready_translation(
                    title="意大利科技政策更新",
                    summary="这条新闻涉及意大利科技政策与中国企业。",
                    issue_tags=["科技"],
                    related_tags=["涉中"],
                    region_tags=["意大利", "欧洲"],
                ),
            ),
            _projection_row(
                event_id="ne-france-energy-eu",
                target_id="france",
                metadata=_ready_translation(
                    title="法国能源政策更新",
                    summary="这条新闻涉及法国能源政策与欧盟规则。",
                    issue_tags=["能源"],
                    related_tags=["涉欧"],
                    region_tags=["法国", "欧洲"],
                ),
            ),
        ]
    )
    test_config = [
        {
            "target_id": "italy",
            "display_name": "意大利新闻监控",
            "region_type": "country",
            "language_scope": {"primary": "it"},
            "source_channel_refs": ["ansa"],
        },
        {
            "target_id": "france",
            "display_name": "法国新闻监控",
            "region_type": "country",
            "language_scope": {"primary": "fr"},
            "source_channel_refs": ["lemonde"],
        },
    ]
    monkeypatch.setattr(api_server, "_load_target_configs", lambda: test_config)
    # 源模块: public_news_utils 内懒加载从 target_config_utils 导入 _load_target_configs
    monkeypatch.setattr(target_config_utils, "_load_target_configs", lambda: test_config)

    app = create_app(data_dir=tmp_path, store=store, auto_store=False, skip_lifespan=True)
    client = TestClient(app)

    facets_response = client.get("/api/v1/public/facets")
    issue_response = client.get("/api/v1/public/news", params={"issue": "科技"})
    related_response = client.get("/api/v1/public/news", params={"related": "涉欧"})
    region_response = client.get("/api/v1/public/news", params={"region_id": "italy"})

    assert facets_response.status_code == 200
    facets = facets_response.json()
    assert facets["issues"][0] == {"id": "科技", "label": "科技", "count": 1}
    assert {"id": "涉中", "label": "涉中", "count": 1} in facets["related"]
    assert {"id": "italy", "label": "意大利", "count": 1} in facets["regions"]
    assert [item["id"] for item in issue_response.json()["items"]] == ["ne-italy-tech-china"]
    assert [item["id"] for item in related_response.json()["items"]] == ["ne-france-energy-eu"]
    assert [item["id"] for item in region_response.json()["items"]] == ["ne-italy-tech-china"]
    assert issue_response.json()["items"][0]["issueTags"] == ["科技"]
    assert issue_response.json()["items"][0]["relatedTags"] == ["涉中"]
    assert issue_response.json()["items"][0]["regionTags"] == ["意大利", "欧洲"]


def test_public_facets_reuses_short_cache_for_same_query(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = FilterAwareProjectionStore(
        [
            _projection_row(
                event_id="ne-italy-facet-cache",
                metadata=_ready_translation(
                    issue_tags=["科技"],
                    related_tags=["涉中"],
                    region_tags=["意大利"],
                ),
            )
        ]
    )
    test_target_config = {
        "target_id": "italy",
        "display_name": "意大利新闻监控",
        "region_type": "country",
        "language_scope": {"primary": "it"},
        "source_channel_refs": ["ansa"],
    }
    # 源模块: public_news_utils 内懒加载从 target_config_utils 导入 _load_target_configs
    monkeypatch.setattr(
        target_config_utils, "_load_target_configs", lambda: [test_target_config]
    )
    # api_server 闭包: _load_target_configs 已在模块级从 target_config_utils import
    monkeypatch.setattr(
        api_server, "_load_target_configs", lambda: [test_target_config]
    )
    monkeypatch.setattr(
        api_server, "_public_target_event_counts",
        lambda data_dir: {"italy": 1},
    )

    app = create_app(data_dir=tmp_path, store=store, auto_store=False, skip_lifespan=True)
    client = TestClient(app)

    first = client.get("/api/v1/public/facets")
    second = client.get("/api/v1/public/facets")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.headers["x-news-sentry-facets-cache"] == "miss"
    assert second.headers["x-news-sentry-facets-cache"] == "hit"
    assert store.projection_calls == 1


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

    # 在 create_app 之前 patch，确保 create_app 内部将该 mock 赋给 public_news_utils
    monkeypatch.setattr(api_server, "_visible_index_events_page", _fake_visible_index_events_page)
    # 源模块: public_news_utils 内懒加载从 event_io_utils 导入 _load_all_events
    monkeypatch.setattr(
        event_io_utils, "_load_all_events",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not scan files")),
    )

    app = create_app(data_dir=tmp_path, store=store, auto_store=False, skip_lifespan=True)
    client = TestClient(app)

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

    # 在 create_app 之前 patch，确保 create_app 内部将该 mock 赋给 public_news_utils
    monkeypatch.setattr(api_server, "_visible_index_events_page", _fake_visible_index_events_page)
    # 源模块: public_news_utils 内懒加载从 event_io_utils 导入 _load_all_events
    monkeypatch.setattr(
        event_io_utils, "_load_all_events",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not scan files")),
    )

    app = create_app(data_dir=tmp_path, store=store, auto_store=False, skip_lifespan=True)
    client = TestClient(app)

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

    # 在 create_app 之前 patch，确保 create_app 内部将该 mock 赋给 public_news_utils
    monkeypatch.setattr(api_server, "_visible_index_events_page", _fake_visible_index_events_page)
    # 源模块: public_news_utils 内懒加载从 event_io_utils 导入 _load_all_events
    monkeypatch.setattr(
        event_io_utils, "_load_all_events",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not scan files")),
    )

    app = create_app(data_dir=tmp_path, store=store, auto_store=False, skip_lifespan=True)
    client = TestClient(app)

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
                    "article": {
                        "status": "fetched",
                        "full_text": "这是一段已提取的站内阅读全文正文。",
                        "image_urls": ["https://example.com/body-image.jpg"],
                        "lead_image_url": "https://example.com/lead-image.jpg",
                    },
                    "source_display_name": "ANSA",
                },
            )
        ]
    )
    # _load_single_event 已在 api_server 模块级 import，闭包直接引用
    monkeypatch.setattr(
        api_server, "_load_single_event",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not read markdown")),
    )

    app = create_app(data_dir=tmp_path, store=store, auto_store=False, skip_lifespan=True)
    client = TestClient(app)

    response = client.get(f"/api/v1/public/news/{event_id}", params={"target_id": "italy"})

    assert response.status_code == 200
    item = response.json()
    assert item["id"] == event_id
    assert item["title"] == "投影详情标题"
    assert item["summary"] == "投影详情中文摘要"
    assert item["fullContent"] == "这是一段已提取的站内阅读全文正文。"
    assert item["imageUrls"] == [
        "https://example.com/lead-image.jpg",
        "https://example.com/body-image.jpg",
    ]
    assert item["originalUrl"] == "https://example.com/story"
    assert item["source"]["id"] == "ansa"
    assert store.direct_row_reads == 1
    assert store.projection_scan_attempted is False


def test_public_news_detail_hides_stale_publication_hash(
    tmp_path: Path,
    monkeypatch,
) -> None:
    event_id = "ne-italy-stale-publication-001"
    metadata = _ready_translation(
        title="旧标题对应的中文标题",
        summary="旧标题对应的中文摘要。",
        one_line="旧标题对应的一句话概括。",
        reason="旧标题对应的推荐理由，已经不应继续公开。",
    )
    metadata["publication"]["field_hash"] = public_translation_field_hash(
        {
            "event_id": event_id,
            "target_id": "italy",
            "title_original": "Old source title",
            "metadata": metadata,
        }
    )
    store = DirectRowProjectionDetailStore(
        [
            _projection_row(
                event_id=event_id,
                title_original="Changed source title",
                metadata=metadata,
            )
        ]
    )
    # _load_single_event 已在 api_server 模块级 import，闭包直接引用
    monkeypatch.setattr(
        api_server, "_load_single_event",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not read markdown")),
    )

    app = create_app(data_dir=tmp_path, store=store, auto_store=False, skip_lifespan=True)
    client = TestClient(app)

    response = client.get(f"/api/v1/public/news/{event_id}", params={"target_id": "italy"})

    assert response.status_code == 404
    assert store.direct_row_reads == 1
    assert store.projection_scan_attempted is False
