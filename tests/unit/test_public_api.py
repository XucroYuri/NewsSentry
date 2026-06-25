"""Tests for public API endpoints — separated from test_api_server.py (M-51)."""

from __future__ import annotations

import asyncio
import json
import re
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml
from fastapi.testclient import TestClient

from news_sentry.core import api_server as api_server_module
from news_sentry.core import event_io_utils
from news_sentry.core.api_server import (
    _get_valid_api_keys,
    create_app,
)
from news_sentry.core.async_store import AsyncStore
from news_sentry.core.public_news_utils import _public_analysis_from_store
from news_sentry.core.public_translation import public_translation_ready


def _ready_public_title(title: str = "公开新闻") -> str:
    if re.search(r"[\u4e00-\u9fff]", title):
        return title
    return f"中文测试新闻{len(title)}"


def _ready_public_metadata(title: str = "公开新闻") -> dict[str, Any]:
    return {
        "translation": {
            "title_pre": _ready_public_title(title),
            "summary_pre": "这是一条已经完成中文摘要的公开新闻。",
        },
        "publication": {
            "one_line_summary": "一句话概括这条公开新闻。",
            "recommendation_reason": "AI 推荐理由指出这条新闻对跨境观察具有具体影响。",
            "issue_tags": ["政治"],
            "related_tags": ["涉欧"],
            "region_tags": ["意大利"],
        },
    }


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
    # 清除 _state 模块中的缓存（utility 模块实际使用这些缓存而非 api_server 本地副本）
    from news_sentry.core import _state as _state_mod

    _state_mod._public_source_configs_cache.clear()
    _state_mod._source_inventory_cache.clear()
    _state_mod._target_validation_cache.clear()
    _state_mod._collector_diagnostics_cache.clear()
    _state_mod._admin_overview_cache.clear()
    _state_mod._admin_targets_cache.clear()
    _state_mod._public_news_feed_cache.clear()
    _state_mod._public_facets_cache.clear()
    _state_mod._public_regions_cache.clear()
    _state_mod._public_bootstrap_cache.clear()


def _force_deployment_env(monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    monkeypatch.setenv("NEWSSENTRY_DEPLOYMENT_ENV", env)
    monkeypatch.setattr(api_server_module, "_deployment_env", "")


def _write_draft(
    data_dir: Path,
    target_id: str,
    event_id: str,
    title: str = "Test",
    source_id: str = "test-src",
    news_value_score: int | None = None,
    china_relevance: int | None = None,
    classification_l0: str | None = None,
    published_at: str | None = None,
) -> Path:
    """辅助：写入一个 draft 事件文件。"""
    drafts = data_dir / target_id / "drafts"
    drafts.mkdir(parents=True, exist_ok=True)
    data: dict = {
        "id": event_id,
        "source_id": source_id,
        "url": "https://example.com",
        "title_original": title,
        "pipeline_stage": "outputted",
        "metadata": _ready_public_metadata(title),
    }
    if news_value_score is not None:
        data["news_value_score"] = news_value_score
    if china_relevance is not None:
        data["china_relevance"] = china_relevance
    if classification_l0 is not None:
        data["classification"] = {"l0": classification_l0}
    if published_at is not None:
        data["published_at"] = published_at
    fm = yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False)
    filepath = drafts / f"2026-05-12-{source_id}-{event_id}.md"
    filepath.write_text(f"---\n{fm}---\n\n# {title}\n\nBody\n", encoding="utf-8")
    return filepath


def _write_target_config(
    config_dir: Path,
    target_id: str,
    display_name: str,
    primary: str = "it",
    source_count: int = 3,
    monitoring_type: str | None = None,
    topic_label: str | None = None,
) -> Path:
    """辅助：写入一个 target 配置文件。"""
    config_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "target_id": target_id,
        "display_name": display_name,
        "language_scope": {"primary": primary, "secondary": ["en"], "output": "zh"},
        "source_channel_refs": [f"src-{i}" for i in range(source_count)],
    }
    if monitoring_type:
        data["monitoring_type"] = monitoring_type
    if topic_label:
        data["topic_label"] = topic_label
    filepath = config_dir / f"{target_id}.yaml"
    content = yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False)
    filepath.write_text(content, encoding="utf-8")
    return filepath


async def _insert_index_event(
    store: AsyncStore,
    *,
    event_id: str,
    target_id: str = "italy",
    stage: str = "drafts",
    source_id: str = "ansa",
    news_value_score: int | None = 80,
    china_relevance: int | None = 50,
    classification_l0: str | None = "politics",
    title_original: str = "Store event",
    published_at: str | None = None,
    file_path: str | None = None,
    sentiment: str | None = None,
    entity_names: str | None = None,
    topic_tags: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """辅助：写入 event_index 行。"""
    assert store._db is not None  # noqa: SLF001
    now = datetime.now(UTC).isoformat()
    if metadata is None:
        metadata = _ready_public_metadata(title_original)
    ready = 1 if public_translation_ready(metadata) else 0
    await store._db.execute(  # noqa: SLF001
        "INSERT OR REPLACE INTO event_index "
        "(event_id, target_id, stage, source_id, news_value_score, "
        "china_relevance, classification_l0, title_original, "
        "published_at, file_path, created_at, sentiment, entity_names, topic_tags, "
        "metadata_json, public_translation_ready) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            event_id,
            target_id,
            stage,
            source_id,
            news_value_score,
            china_relevance,
            classification_l0,
            title_original,
            published_at or now,
            file_path,
            now,
            sentiment,
            entity_names,
            topic_tags,
            json.dumps(metadata, ensure_ascii=False),
            ready,
        ),
    )
    await store._db.commit()  # noqa: SLF001


class TestPublicAPI:
    """Public API endpoint tests extracted from TestAPIServer (M-51)."""

    def _make_client(self, tmp_path: Path) -> TestClient:
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)
        # 获取 dev mode token 并设为默认 headers
        resp = client.post("/api/v1/auth/token", json={"api_key": ""})
        assert resp.status_code == 200, f"Auth token failed: {resp.text}"
        token = resp.json()["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"
        return client

    def test_public_app_entry_and_root_use_same_reader_shell(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        static_dir = tmp_path / "static"
        public_app_dir = static_dir / "public_app"
        public_app_dir.mkdir(parents=True)
        (static_dir / "index.html").write_text(
            '<html><body id="legacy-shell">Legacy __CSP_NONCE__</body></html>',
            encoding="utf-8",
        )
        (public_app_dir / "index.html").write_text(
            '<html><body><div id="root"></div><script>window.__vite=1</script>'
            '<script type="module" src="/public-app/assets/index-abc123.js"></script>'
            "</body></html>",
            encoding="utf-8",
        )
        monkeypatch.setattr(api_server_module, "_static_dir", lambda: static_dir)
        app = create_app(data_dir=tmp_path / "data", auto_store=False)
        client = TestClient(app)

        public_resp = client.get("/public-app/")
        homepage_resp = client.get("/")

        assert public_resp.status_code == 200
        assert '<div id="root"></div>' in public_resp.text
        assert public_resp.headers["cache-control"] == (
            "public, max-age=300, s-maxage=300, stale-while-revalidate=600"
        )
        csp = public_resp.headers["content-security-policy"]
        assert "'nonce-" in csp
        nonce = csp.split("'nonce-", maxsplit=1)[1].split("'", maxsplit=1)[0]
        assert f'<script nonce="{nonce}">window.__vite=1</script>' in public_resp.text
        expected_module_script = (
            f'<script nonce="{nonce}" type="module" '
            'src="/public-app/assets/index-abc123.js"></script>'
        )
        assert expected_module_script in public_resp.text
        assert homepage_resp.status_code == 200
        assert '<div id="root"></div>' in homepage_resp.text
        assert '<link rel="canonical" href="https://news-sentry.com/" />' in homepage_resp.text
        assert "跨境新闻信号过滤器" not in homepage_resp.text
        assert "legacy-shell" not in homepage_resp.text

    def test_public_app_entry_supports_head(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        static_dir = tmp_path / "static"
        public_app_dir = static_dir / "public_app"
        public_app_dir.mkdir(parents=True)
        (static_dir / "index.html").write_text("<html>legacy</html>", encoding="utf-8")
        (public_app_dir / "index.html").write_text(
            '<html><body><div id="root"></div></body></html>',
            encoding="utf-8",
        )
        monkeypatch.setattr(api_server_module, "_static_dir", lambda: static_dir)
        app = create_app(data_dir=tmp_path / "data", auto_store=False)
        client = TestClient(app)

        resp = client.head("/public-app/")

        assert resp.status_code == 200
        assert resp.headers["cache-control"] == (
            "public, max-age=300, s-maxage=300, stale-while-revalidate=600"
        )

    def test_public_app_assets_use_fingerprinted_cache_policy(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        static_dir = tmp_path / "static"
        asset_dir = static_dir / "public_app" / "assets"
        asset_dir.mkdir(parents=True)
        (static_dir / "index.html").write_text("<html>legacy</html>", encoding="utf-8")
        (static_dir / "public_app" / "index.html").write_text(
            '<html><body><div id="root"></div></body></html>',
            encoding="utf-8",
        )
        (asset_dir / "index-abc123.js").write_text(
            "console.log('public app');",
            encoding="utf-8",
        )
        monkeypatch.setattr(api_server_module, "_static_dir", lambda: static_dir)
        app = create_app(data_dir=tmp_path / "data", auto_store=False)
        client = TestClient(app)

        resp = client.get("/public-app/assets/index-abc123.js")

        assert resp.status_code == 200
        assert "public app" in resp.text
        assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"

    def test_public_news_feed_without_auth(self, tmp_path: Path) -> None:
        """新闻工作台只读入口不要求登录。"""
        _write_draft(
            tmp_path,
            "italy",
            "ne-italy-src-20260526-public01",
            title="Public feed story",
            news_value_score=75,
        )
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)

        resp = client.get("/api/v1/events/feed", params={"target_id": "italy"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["groups"][0]["events"][0]["display_title"] == "Public feed story"

    def test_public_news_target_ids_skip_templates_and_runtime_dirs(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """默认公开 feed 只信任地区配置，不从运行目录补公共地区。"""
        monkeypatch.setattr(
            "news_sentry.core.target_config_utils._load_target_configs",
            lambda: [
                {"target_id": "example-target"},
                {"target_id": "italy"},
            ],
        )
        (tmp_path / "locks").mkdir()
        (tmp_path / "logs").mkdir()
        (tmp_path / "eval").mkdir()
        (tmp_path / "japan").mkdir()
        (tmp_path / "japan" / "state.db").write_text("", encoding="utf-8")
        (tmp_path / "germany" / "drafts").mkdir(parents=True)

        target_ids = api_server_module._public_news_target_ids(tmp_path, None)  # noqa: SLF001

        assert target_ids == ["italy"]

    def test_public_news_api_returns_reader_shape_without_auth(self, tmp_path: Path) -> None:
        """公共新闻 API 返回读者侧字段，不暴露 pipeline 参数作为主响应。"""
        _write_draft(
            tmp_path,
            "italy",
            "ne-italy-src-20260609-public-news01",
            title="Italy public news story",
            source_id="ansa",
            news_value_score=82,
            china_relevance=74,
            classification_l0="international-relations",
            published_at="2026-06-09T09:30:00+00:00",
        )
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)

        resp = client.get("/api/v1/public/news", params={"target_id": "italy"})

        assert resp.status_code == 200
        assert resp.headers["etag"].startswith('"public-news-')
        assert int(resp.headers["x-poll-after-ms"]) >= 30_000
        data = resp.json()
        assert data["latestCursor"]
        item = data["items"][0]
        assert item["id"] == "ne-italy-src-20260609-public-news01"
        assert item["targetId"] == "italy"
        assert item["targetLabel"]
        assert item["title"] == _ready_public_title("Italy public news story")
        assert item["originalTitle"] == "Italy public news story"
        assert item["source"]["id"] == "ansa"
        assert item["source"]["name"]
        assert item["source"]["type"] in {"rss", "api", "web", "social", "official", "unknown"}
        assert "credibilityLabel" in item["source"]
        assert item["originalUrl"] == "https://example.com"
        assert (
            item["detailUrl"]
            == "/public-app/events/ne-italy-src-20260609-public-news01?target_id=italy"
        )
        assert item["tags"] == ["政治", "涉欧", "意大利"]
        assert item["issueTags"] == ["政治"]
        assert item["relatedTags"] == ["涉欧"]
        assert item["regionTags"] == ["意大利"]
        assert item["valueLabel"] == "精选"
        assert item["chinaRelevanceLabel"] == "高"
        assert "pipeline_stage" not in item
        assert "target_id" not in item

    def test_public_news_api_supports_before_and_since_cursors(self, tmp_path: Path) -> None:
        """公共新闻流支持向下加载旧新闻，以及低频检查新新闻。"""
        _write_draft(
            tmp_path,
            "italy",
            "ne-italy-src-20260609-old00001",
            title="Older public story",
            news_value_score=70,
            published_at="2026-06-09T08:00:00+00:00",
        )
        _write_draft(
            tmp_path,
            "italy",
            "ne-italy-src-20260609-top00001",
            title="Current public story",
            news_value_score=72,
            published_at="2026-06-09T09:00:00+00:00",
        )
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)

        first = client.get(
            "/api/v1/public/news",
            params={"target_id": "italy", "page_size": 1},
        )

        assert first.status_code == 200
        first_data = first.json()
        assert [item["title"] for item in first_data["items"]] == [
            _ready_public_title("Current public story")
        ]
        assert first_data["latestCursor"]
        assert first_data["nextCursor"]

        older = client.get(
            "/api/v1/public/news",
            params={
                "target_id": "italy",
                "page_size": 1,
                "before_cursor": first_data["nextCursor"],
            },
        )

        assert older.status_code == 200
        assert [item["title"] for item in older.json()["items"]] == [
            _ready_public_title("Older public story")
        ]

        empty_update = client.get(
            "/api/v1/public/news",
            params={"target_id": "italy", "since_cursor": first_data["latestCursor"]},
        )
        assert empty_update.status_code == 200
        assert empty_update.json()["items"] == []
        assert empty_update.json()["hasNewer"] is False

        _write_draft(
            tmp_path,
            "italy",
            "ne-italy-src-20260609-new00001",
            title="New automatic story",
            news_value_score=88,
            published_at="2026-06-09T10:00:00+00:00",
        )
        update = client.get(
            "/api/v1/public/news",
            params={"target_id": "italy", "since_cursor": first_data["latestCursor"]},
        )

        assert update.status_code == 200
        update_data = update.json()
        assert update_data["hasNewer"] is True
        assert [item["title"] for item in update_data["items"]] == [
            _ready_public_title("New automatic story")
        ]

    def test_public_news_api_returns_304_for_matching_etag(self, tmp_path: Path) -> None:
        """公共新闻流无变化时可用 ETag 轻响应，减少重复传输。"""
        _write_draft(
            tmp_path,
            "italy",
            "ne-italy-src-20260609-etag0001",
            title="ETag story",
            news_value_score=68,
            published_at="2026-06-09T09:00:00+00:00",
        )
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)
        first = client.get("/api/v1/public/news", params={"target_id": "italy"})
        assert first.status_code == 200

        second = client.get(
            "/api/v1/public/news",
            params={"target_id": "italy"},
            headers={"If-None-Match": first.headers["etag"]},
        )

        assert second.status_code == 304
        assert second.text == ""
        assert second.headers["etag"] == first.headers["etag"]
        assert int(second.headers["x-poll-after-ms"]) >= 30_000

    def test_public_news_api_uses_index_only_rows_without_frontmatter_scan(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """公开列表页应从 SQLite index 构造条目，不为首屏读取 Markdown frontmatter。"""
        store = AsyncStore(tmp_path / "state.db")
        asyncio.run(store.initialize())
        asyncio.run(
            _insert_index_event(
                store,
                event_id="ne-italy-index-only-001",
                title_original="Index only public story",
                published_at="2026-06-09T10:00:00+00:00",
                file_path=str(tmp_path / "italy" / "drafts" / "index-only.md"),
            )
        )

        def fail_frontmatter_read(*args: Any, **kwargs: Any) -> None:
            raise AssertionError("public list must not read frontmatter")

        monkeypatch.setattr(
            api_server_module,
            "_load_indexed_event_frontmatter",
            fail_frontmatter_read,
        )
        app = create_app(data_dir=tmp_path, store=store)
        client = TestClient(app)

        resp = client.get("/api/v1/public/news", params={"target_id": "italy"})

        assert resp.status_code == 200
        item = resp.json()["items"][0]
        assert item["id"] == "ne-italy-index-only-001"
        assert item["title"] == _ready_public_title("Index only public story")

    def test_public_news_api_page_size_one_does_not_scan_default_batch(
        self,
        tmp_path: Path,
    ) -> None:
        """page_size=1 不应再触发每 target 固定 80 条候选扫描。"""

        class CountingStore:
            def __init__(self) -> None:
                self.limits: list[int] = []

            async def get_target_event_count(self, target_id: str) -> int:
                return 1

            async def query_events_paginated(self, **kwargs: Any) -> dict[str, Any]:
                self.limits.append(int(kwargs["limit"]))
                return {
                    "total": 1,
                    "rows": [
                        {
                            "event_id": "ne-italy-small-page-001",
                            "source_id": "ansa",
                            "news_value_score": 75,
                            "china_relevance": 50,
                            "classification_l0": "politics",
                            "published_at": "2026-06-09T10:00:00+00:00",
                            "file_path": None,
                            "title_original": "Small page story",
                            "metadata": _ready_public_metadata("Small page story"),
                        }
                    ],
                }

        store = CountingStore()
        app = create_app(data_dir=tmp_path, store=store)  # type: ignore[arg-type]
        client = TestClient(app)

        resp = client.get(
            "/api/v1/public/news",
            params={"target_id": "italy", "page_size": 1},
        )

        assert resp.status_code == 200
        assert resp.json()["items"][0]["title"] == _ready_public_title("Small page story")
        assert store.limits
        assert max(store.limits) <= 2

    def test_public_news_api_caches_source_configs_during_projection(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """首屏 item projection 不能为每条新闻重复读取 source YAML。"""

        class CountingStore:
            async def get_target_event_count(self, target_id: str) -> int:
                return 20

            async def query_public_news_rows(self, **kwargs: Any) -> dict[str, Any]:
                return {
                    "total": 20,
                    "rows": [
                        {
                            "event_id": f"ne-italy-source-cache-{idx:03d}",
                            "source_id": "ansa",
                            "news_value_score": 82,
                            "china_relevance": 70,
                            "classification_l0": "politics",
                            "published_at": f"2026-06-09T10:{idx:02d}:00+00:00",
                            "file_path": None,
                            "title_original": f"Source cached story {idx}",
                            "metadata": _ready_public_metadata(f"Source cached story {idx}"),
                        }
                        for idx in range(20)
                    ],
                }

        calls = 0

        def fake_load_source_configs(target_id: str) -> list[dict[str, Any]]:
            nonlocal calls
            calls += 1
            return [
                {
                    "source_id": "ansa",
                    "display_name": "ANSA.it",
                    "type": "rss",
                    "credibility_base": 0.9,
                }
            ]

        monkeypatch.setattr(
            "news_sentry.core.target_config_utils._load_source_configs",
            fake_load_source_configs,
        )
        app = create_app(data_dir=tmp_path, store=CountingStore())  # type: ignore[arg-type]
        client = TestClient(app)

        resp = client.get(
            "/api/v1/public/news",
            params={"target_id": "italy", "page_size": 20},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 20
        assert {item["source"]["name"] for item in data["items"]} == {"ANSA.it"}
        assert calls == 1

    def test_public_news_api_uses_short_ttl_projection_cache(
        self,
        tmp_path: Path,
    ) -> None:
        """相同公开 feed 查询短时间内应命中进程内 projection cache。"""

        class CountingStore:
            def __init__(self) -> None:
                self.calls = 0

            async def get_target_event_count(self, target_id: str) -> int:
                return 1

            async def query_events_paginated(self, **kwargs: Any) -> dict[str, Any]:
                self.calls += 1
                return {
                    "total": 1,
                    "rows": [
                        {
                            "event_id": "ne-italy-cache-001",
                            "source_id": "ansa",
                            "news_value_score": 82,
                            "china_relevance": 75,
                            "classification_l0": "international-relations",
                            "published_at": "2026-06-09T10:00:00+00:00",
                            "file_path": None,
                            "title_original": "Cached public story",
                            "metadata": _ready_public_metadata("Cached public story"),
                        }
                    ],
                }

        store = CountingStore()
        app = create_app(data_dir=tmp_path, store=store)  # type: ignore[arg-type]
        client = TestClient(app)

        first = client.get("/api/v1/public/news", params={"target_id": "italy"})
        second = client.get("/api/v1/public/news", params={"target_id": "italy"})

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.headers["x-news-sentry-feed-cache"] == "miss"
        assert second.headers["x-news-sentry-feed-cache"] == "hit"
        assert first.headers["etag"] == second.headers["etag"]
        assert second.json() == first.json()
        assert store.calls == 1
        elapsed = second.headers["x-news-sentry-feed-elapsed-ms"]
        assert elapsed.isdigit()
        sensitive_header_material = " ".join(
            [
                second.headers["x-news-sentry-feed-cache"],
                second.headers["x-news-sentry-feed-elapsed-ms"],
            ]
        ).lower()
        assert "data_dir" not in sensitive_header_material
        assert "token" not in sensitive_header_material
        assert "secret" not in sensitive_header_material

    def test_public_news_api_returns_304_from_projection_cache(
        self,
        tmp_path: Path,
    ) -> None:
        """缓存命中且 ETag 匹配时仍返回轻量 304。"""

        class CountingStore:
            def __init__(self) -> None:
                self.calls = 0

            async def get_target_event_count(self, target_id: str) -> int:
                return 1

            async def query_events_paginated(self, **kwargs: Any) -> dict[str, Any]:
                self.calls += 1
                return {
                    "total": 1,
                    "rows": [
                        {
                            "event_id": "ne-italy-cache-304",
                            "source_id": "ansa",
                            "news_value_score": 70,
                            "china_relevance": 40,
                            "classification_l0": "politics",
                            "published_at": "2026-06-09T10:00:00+00:00",
                            "file_path": None,
                            "title_original": "Cached ETag story",
                            "metadata": _ready_public_metadata("Cached ETag story"),
                        }
                    ],
                }

        store = CountingStore()
        app = create_app(data_dir=tmp_path, store=store)  # type: ignore[arg-type]
        client = TestClient(app)

        first = client.get("/api/v1/public/news", params={"target_id": "italy"})
        second = client.get(
            "/api/v1/public/news",
            params={"target_id": "italy"},
            headers={"If-None-Match": first.headers["etag"]},
        )

        assert first.status_code == 200
        assert second.status_code == 304
        assert second.text == ""
        assert second.headers["x-news-sentry-feed-cache"] == "hit"
        assert second.headers["etag"] == first.headers["etag"]
        assert store.calls == 1

    def test_public_news_api_logs_slow_miss_without_sensitive_values(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """慢 public feed miss 需要可观测，但日志不能包含搜索词、路径或密钥形态字段。"""

        class SlowStore:
            async def get_target_event_count(self, target_id: str) -> int:
                return 1

            async def query_public_news_rows(self, **kwargs: Any) -> dict[str, Any]:
                return {
                    "total": 1,
                    "rows": [
                        {
                            "event_id": "ne-italy-slow-log-001",
                            "source_id": "ansa",
                            "news_value_score": 80,
                            "china_relevance": 60,
                            "classification_l0": "politics",
                            "published_at": "2026-06-09T10:00:00+00:00",
                            "file_path": None,
                            "title_original": "Slow log story",
                            "metadata": _ready_public_metadata("Slow log story"),
                        }
                    ],
                }

        monkeypatch.setattr(
            sys.modules["news_sentry.core._state"],
            "_PUBLIC_NEWS_SLOW_LOG_MS",
            0,
        )
        # public_news_utils imported the constant at module level; must also patch its copy
        monkeypatch.setattr(
            sys.modules.get("news_sentry.core.public_news_utils", api_server_module),
            "_PUBLIC_NEWS_SLOW_LOG_MS",
            0,
        )
        caplog.set_level("WARNING")
        app = create_app(data_dir=tmp_path, store=SlowStore())  # type: ignore[arg-type]
        client = TestClient(app)

        resp = client.get(
            "/api/v1/public/news",
            params={"target_id": "italy", "q": "secret-search-term"},
        )

        assert resp.status_code == 200
        log_text = "\n".join(record.getMessage() for record in caplog.records)
        assert "public news feed slow miss" in log_text
        assert "has_q=True" in log_text
        assert "secret-search-term" not in log_text
        assert "data_dir" not in log_text
        assert "token" not in log_text.lower()
        assert "secret" not in log_text.lower()

    def test_public_news_detail_returns_reader_shape_without_auth(self, tmp_path: Path) -> None:
        """公共新闻详情 API 使用读者字段，不需要后台认证。"""
        event_id = "ne-italy-src-20260609-detail01"
        _write_draft(
            tmp_path,
            "italy",
            event_id,
            title="Public detail presentation",
            news_value_score=64,
            published_at="2026-06-09T09:00:00+00:00",
        )
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)

        resp = client.get(f"/api/v1/public/news/{event_id}", params={"target_id": "italy"})

        assert resp.status_code == 200
        item = resp.json()
        assert item["id"] == event_id
        assert item["title"] == _ready_public_title("Public detail presentation")
        assert item["valueLabel"] == "关注"
        assert "pipeline_stage" not in item

    def test_public_event_detail_without_auth(self, tmp_path: Path) -> None:
        """匿名用户可以打开新闻流里的单篇只读详情。"""
        event_id = "ne-italy-src-20260526-public02"
        _write_draft(tmp_path, "italy", event_id, title="Public detail story")
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)

        resp = client.get(f"/api/v1/events/{event_id}", params={"target_id": "italy"})

        assert resp.status_code == 200
        assert resp.json()["id"] == event_id

    @pytest.mark.skip(reason="route /api/v1/news/target/... removed; migrated to canonical events")
    def test_public_event_markdown_export_without_auth(self, tmp_path: Path) -> None:
        """匿名用户可以下载单篇事件 Markdown 投影，不写入磁盘。"""
        event_id = "ne-italy-src-20260526-export01"
        _write_draft(tmp_path, "italy", event_id, title="Public export story")
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)

        resp = client.get(f"/api/v1/news/target/italy/events/{event_id}/export/markdown")

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/markdown")
        disposition = resp.headers["content-disposition"]
        assert "attachment" in disposition
        assert f"{event_id}.md" in disposition
        assert "Public export story" in resp.text

    @pytest.mark.skip(reason="route /api/v1/news/target/... removed; migrated to canonical events")
    def test_public_event_markdown_export_normalizes_legacy_frontmatter(
        self, tmp_path: Path
    ) -> None:
        """公开 Markdown 导出应容忍 legacy/脏 frontmatter 字段。"""
        event_id = "ne-italy-src-20260526-export-dirty"
        drafts = tmp_path / "italy" / "drafts"
        drafts.mkdir(parents=True, exist_ok=True)
        event = {
            "id": event_id,
            "language": "en-US",
            "title_original": "Dirty export story",
            "news_value_score": 75.5,
            "china_relevance": "42",
            "sentiment_score": "positive",
            "metadata": "legacy metadata blob",
            "pipeline_stage": "outputted",
        }
        fm = yaml.dump(event, allow_unicode=True, default_flow_style=False, sort_keys=False)
        (drafts / "dirty.md").write_text(
            f"---\n{fm}---\n\n# Dirty export story\n",
            encoding="utf-8",
        )
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)

        resp = client.get(f"/api/v1/news/target/italy/events/{event_id}/export/markdown")

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/markdown")
        assert "Dirty export story" in resp.text

    @pytest.mark.parametrize("language", ["EN", "fr", "de", "ja"])
    @pytest.mark.skip(reason="route /api/v1/news/target/... removed; migrated to canonical events")
    def test_public_event_markdown_export_accepts_legacy_language_values(
        self, tmp_path: Path, language: str
    ) -> None:
        """公开 Markdown 导出应容忍大小写和多 target 语言值。"""
        event_id = f"ne-italy-src-20260526-export-{language.lower()}"
        title = f"Language export story {language}"
        drafts = tmp_path / "italy" / "drafts"
        drafts.mkdir(parents=True, exist_ok=True)
        event = {
            "id": event_id,
            "source_id": "ansa",
            "url": "https://example.com/language-export",
            "language": language,
            "title_original": title,
            "published_at": "2026-05-26T10:00:00+00:00",
            "pipeline_stage": "outputted",
        }
        fm = yaml.dump(event, allow_unicode=True, default_flow_style=False, sort_keys=False)
        (drafts / f"{language.lower()}-language.md").write_text(
            f"---\n{fm}---\n\n# {title}\n",
            encoding="utf-8",
        )
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)

        resp = client.get(f"/api/v1/news/target/italy/events/{event_id}/export/markdown")

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/markdown")
        assert title in resp.text

    @pytest.mark.skip(reason="route /api/v1/news/target/... removed; migrated to canonical events")
    def test_public_event_markdown_export_uses_index_row_fallback(self, tmp_path: Path) -> None:
        """公开 Markdown 导出应覆盖 SQLite index row fallback，无文件也不 500。"""
        event_id = "ne-italy-ansa-20260526-indexrow"
        store = AsyncStore(tmp_path / "state.db")
        asyncio.run(store.initialize())
        try:
            asyncio.run(
                _insert_index_event(
                    store,
                    event_id=event_id,
                    title_original="Index row export story",
                    source_id="ansa",
                    news_value_score=75.5,
                    sentiment="positive",
                )
            )
            app = create_app(data_dir=tmp_path, store=store, auto_store=False)
            client = TestClient(app)

            resp = client.get(f"/api/v1/news/target/italy/events/{event_id}/export/markdown")

            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/markdown")
            assert "Index row export story" in resp.text
            assert event_id in resp.text
        finally:
            asyncio.run(store.close())

    @pytest.mark.skip(reason="route /api/v1/news/target/... removed; migrated to canonical events")
    def test_public_event_markdown_export_missing_event_returns_404(self, tmp_path: Path) -> None:
        """公开 Markdown 导出找不到事件时返回 404，而不是渲染异常。"""
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)

        resp = client.get("/api/v1/news/target/italy/events/missing-event/export/markdown")

        assert resp.status_code == 404

    def test_public_targets_without_auth(self, tmp_path: Path) -> None:
        """匿名用户可以读取 target 列表以初始化新闻工作台。"""
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)

        resp = client.get("/api/v1/targets")

        assert resp.status_code == 200
        assert "targets" in resp.json()

    def test_public_analysis_without_auth_uses_filesystem_fallback(self, tmp_path: Path) -> None:
        """公开分析快照匿名可读，并能从 draft frontmatter 降级聚合。"""
        _write_draft(
            tmp_path,
            "italy",
            "ne-italy-ansa-20260526-analysis01",
            title="Policy story",
            source_id="ansa",
            news_value_score=86,
            china_relevance=55,
            classification_l0="politics",
        )
        _write_draft(
            tmp_path,
            "italy",
            "ne-italy-reuters-20260526-analysis02",
            title="Market story",
            source_id="reuters",
            news_value_score=64,
            china_relevance=10,
            classification_l0="economy",
        )
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)

        resp = client.get("/api/v1/public/targets/italy/analysis", params={"days": 14})

        assert resp.status_code == 200
        data = resp.json()
        assert data["target_id"] == "italy"
        assert data["days"] == 14
        assert data["summary"]["total_events"] == 2
        assert data["summary"]["high_value_events"] == 1
        assert data["summary"]["avg_news_value_score"] == 75.0
        assert data["summary"]["avg_china_relevance"] == 32.5
        assert data["classification_distribution"] == [
            {"name": "economy", "count": 1},
            {"name": "politics", "count": 1},
        ]
        assert data["source_distribution"] == [
            {"source_id": "ansa", "display_name": "ansa", "count": 1},
            {"source_id": "reuters", "display_name": "reuters", "count": 1},
        ]
        assert data["top_entities"] == []
        assert data["topic_trends"] == []
        assert data["sentiment_trend"] == []
        assert data["active_chains"] == []

    def test_public_analysis_filesystem_fallback_honors_days_window(
        self,
        tmp_path: Path,
    ) -> None:
        """文件系统降级路径也按 days 过滤旧 draft。"""
        recent = datetime.now(UTC).isoformat()
        old = (datetime.now(UTC) - timedelta(days=45)).isoformat()
        _write_draft(
            tmp_path,
            "italy",
            "ne-italy-ansa-20260526-recent",
            title="Recent policy story",
            source_id="ansa",
            news_value_score=82,
            china_relevance=50,
            classification_l0="politics",
            published_at=recent,
        )
        _write_draft(
            tmp_path,
            "italy",
            "ne-italy-archive-20260401-old",
            title="Old archive story",
            source_id="archive",
            news_value_score=99,
            china_relevance=99,
            classification_l0="internal",
            published_at=old,
        )
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)

        resp = client.get("/api/v1/public/targets/italy/analysis", params={"days": 14})

        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["total_events"] == 1
        assert data["summary"]["avg_news_value_score"] == 82.0
        assert data["classification_distribution"] == [{"name": "politics", "count": 1}]
        assert data["source_distribution"] == [
            {"source_id": "ansa", "display_name": "ansa", "count": 1}
        ]

    def test_public_analysis_rejects_unsupported_days(self, tmp_path: Path) -> None:
        """公开分析第一版只允许 7 / 14 / 30 天。"""
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)

        resp = client.get("/api/v1/public/targets/italy/analysis", params={"days": 8})

        assert resp.status_code == 422

    def test_public_analysis_empty_target_without_auth(self, tmp_path: Path) -> None:
        """空 target 返回稳定空快照，不把公开页面卡在加载态。"""
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)

        resp = client.get("/api/v1/public/targets/empty/analysis")

        assert resp.status_code == 200
        data = resp.json()
        assert data["target_id"] == "empty"
        assert data["summary"]["total_events"] == 0
        assert data["classification_distribution"] == []
        assert data["source_distribution"] == []

    @pytest.mark.asyncio
    async def test_public_analysis_store_uses_only_public_draft_rows(
        self,
        tmp_path: Path,
    ) -> None:
        """SQLite 公开快照只聚合新闻流可见 drafts，并转换趋势模型。"""
        store = AsyncStore(tmp_path / "state.db")
        await store.initialize()
        now = datetime.now(UTC).isoformat()
        try:
            await _insert_index_event(
                store,
                event_id="public-policy",
                source_id="ansa",
                news_value_score=90,
                china_relevance=80,
                classification_l0="politics",
                title_original="Public policy",
                published_at=now,
                sentiment="positive",
                entity_names="Italy,China",
                topic_tags="policy,china",
            )
            await _insert_index_event(
                store,
                event_id="public-market",
                source_id="reuters",
                news_value_score=60,
                china_relevance=20,
                classification_l0="economy",
                title_original="Public market",
                published_at=now,
                sentiment="neutral",
                entity_names="Italy",
                topic_tags="economy",
            )
            await _insert_index_event(
                store,
                event_id="internal-raw",
                stage="raw",
                source_id="secret",
                news_value_score=100,
                china_relevance=100,
                classification_l0="internal",
                title_original="Internal raw",
                published_at=now,
                sentiment="negative",
                entity_names="Secret",
                topic_tags="secret",
            )

            data = await _public_analysis_from_store("italy", 14, store)

            assert data is not None
            assert data.summary.total_events == 2
            assert data.summary.high_value_events == 1
            assert data.summary.avg_news_value_score == 75.0
            assert [item.model_dump() for item in data.classification_distribution] == [
                {"name": "economy", "count": 1},
                {"name": "politics", "count": 1},
            ]
            assert [item.model_dump() for item in data.source_distribution] == [
                {"source_id": "ansa", "display_name": "ansa", "count": 1},
                {"source_id": "reuters", "display_name": "reuters", "count": 1},
            ]
            assert {entity.name: entity.mention_count for entity in data.top_entities} == {
                "Italy": 2,
                "China": 1,
            }
            assert "secret" not in {topic.topic for topic in data.topic_trends}
            assert all(isinstance(trend.daily_counts, list) for trend in data.topic_trends)
            assert data.sentiment_trend[0].positive == 1
            assert data.sentiment_trend[0].neutral == 1
            assert data.sentiment_trend[0].negative == 0
        finally:
            await store.close()

    @pytest.mark.asyncio
    async def test_public_analysis_store_limits_public_active_chains(
        self,
        tmp_path: Path,
    ) -> None:
        """匿名公开快照在 root 查询阶段限制追踪链数量。"""
        store = AsyncStore(tmp_path / "state.db")
        await store.initialize()
        now = datetime.now(UTC).isoformat()
        try:
            for index in range(12):
                root_id = f"public-root-{index:02d}"
                child_id = f"public-child-{index:02d}"
                await _insert_index_event(
                    store,
                    event_id=root_id,
                    title_original=f"Root {index}",
                    published_at=now,
                )
                await _insert_index_event(
                    store,
                    event_id=child_id,
                    title_original=f"Child {index}",
                    published_at=now,
                )
                await store.create_link(root_id, child_id, "followup", 0.8, {}, "italy")

            await _insert_index_event(
                store,
                event_id="internal-root",
                stage="raw",
                title_original="Internal root",
                published_at=now,
            )
            await _insert_index_event(
                store,
                event_id="internal-child",
                stage="raw",
                title_original="Internal child",
                published_at=now,
            )
            await store.create_link("internal-root", "internal-child", "followup", 0.8, {}, "italy")

            data = await _public_analysis_from_store("italy", 14, store)

            assert data is not None
            assert len(data.active_chains) == 10
            assert all(
                not chain.root_event_id.startswith("internal") for chain in data.active_chains
            )
        finally:
            await store.close()

    def test_public_news_global_feed_does_not_scan_file_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_dir = tmp_path / "config" / "targets"
        _write_target_config(config_dir, "italy", "意大利新闻监控", "it", 5)
        _write_draft(tmp_path, "italy", "orphan-1", title="Orphan file")
        monkeypatch.chdir(tmp_path)
        load_all_events = MagicMock(side_effect=AssertionError("global public feed scanned files"))
        monkeypatch.setattr(api_server_module, "_load_all_events", load_all_events)
        # 源模块: public_news_utils 内懒加载从 event_io_utils 导入 _load_all_events
        monkeypatch.setattr(event_io_utils, "_load_all_events", load_all_events)
        client = self._make_client(tmp_path)

        resp = client.get("/api/v1/public/news?featured=true&page_size=3")

        assert resp.status_code == 200
        assert resp.json()["items"] == []
        load_all_events.assert_not_called()

    def test_public_news_global_feed_queries_global_store_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_dir = tmp_path / "config" / "targets"
        _write_target_config(config_dir, "france", "法国新闻监控", "fr", 5)
        _write_draft(tmp_path, "france", "orphan-1", title="Orphan file")
        monkeypatch.chdir(tmp_path)
        load_all_events = MagicMock(side_effect=AssertionError("global public feed scanned files"))
        monkeypatch.setattr(api_server_module, "_load_all_events", load_all_events)
        monkeypatch.setattr(event_io_utils, "_load_all_events", load_all_events)
        store = AsyncStore(tmp_path / "state.db")

        async def seed() -> None:
            await store.initialize()
            await _insert_index_event(
                store,
                event_id="global-ready-1",
                target_id="france",
                title_original="法国全局索引公开新闻",
                news_value_score=90,
            )

        asyncio.run(seed())
        try:
            app = create_app(data_dir=tmp_path, store=store, auto_store=False, skip_lifespan=True)
            client = TestClient(app)

            resp = client.get("/api/v1/public/news?featured=true&page_size=3")

            assert resp.status_code == 200
            data = resp.json()
            assert [item["id"] for item in data["items"]] == ["global-ready-1"]
            assert data["items"][0]["targetId"] == "france"
            load_all_events.assert_not_called()
        finally:
            asyncio.run(store.close())
