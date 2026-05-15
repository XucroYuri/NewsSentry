"""Tests for API Server — Phase 22 API Gateway + Phase 24 Web UI."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from news_sentry.core.api_server import (
    _parse_frontmatter,
    _RateLimiter,
    _verify_api_key,
    create_app,
)
from news_sentry.core.async_store import AsyncStore


def _write_draft(
    data_dir: Path,
    target_id: str,
    event_id: str,
    title: str = "Test",
    source_id: str = "test-src",
    news_value_score: int | None = None,
    china_relevance: int | None = None,
    classification_l0: str | None = None,
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
    }
    if news_value_score is not None:
        data["news_value_score"] = news_value_score
    if china_relevance is not None:
        data["china_relevance"] = china_relevance
    if classification_l0 is not None:
        data["classification"] = {"l0": classification_l0}
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
) -> Path:
    """辅助：写入一个 target 配置文件。"""
    config_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "target_id": target_id,
        "display_name": display_name,
        "language_scope": {"primary": primary, "secondary": ["en"], "output": "zh"},
        "source_channel_refs": [f"src-{i}" for i in range(source_count)],
    }
    filepath = config_dir / f"{target_id}.yaml"
    content = yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False)
    filepath.write_text(content, encoding="utf-8")
    return filepath


class TestRateLimiter:
    """速率限制器测试。"""

    def test_allows_under_limit(self) -> None:
        limiter = _RateLimiter(max_requests=3, window=60)
        assert limiter.check("key1") is True
        assert limiter.check("key1") is True
        assert limiter.check("key1") is True

    def test_blocks_over_limit(self) -> None:
        limiter = _RateLimiter(max_requests=2, window=60)
        limiter.check("key1")
        limiter.check("key1")
        assert limiter.check("key1") is False

    def test_separate_keys_independent(self) -> None:
        limiter = _RateLimiter(max_requests=1, window=60)
        assert limiter.check("key1") is True
        assert limiter.check("key2") is True
        assert limiter.check("key1") is False


class TestVerifyApiKey:
    """API Key 认证测试。"""

    def test_no_config_keys_allows_all(self) -> None:
        # 无环境变量时开发模式
        os.environ.pop("NEWSSENTRY_API_KEY", None)
        result = _verify_api_key("any")
        assert result == "any"

    def test_valid_key_accepted(self) -> None:
        os.environ["NEWSSENTRY_API_KEY"] = "test-key-1,test-key-2"
        try:
            result = _verify_api_key("test-key-1")
            assert result == "test-key-1"
        finally:
            del os.environ["NEWSSENTRY_API_KEY"]

    def test_invalid_key_rejected(self) -> None:
        os.environ["NEWSSENTRY_API_KEY"] = "test-key-1"
        try:
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as exc_info:
                _verify_api_key("wrong-key")
            assert exc_info.value.status_code == 401
        finally:
            del os.environ["NEWSSENTRY_API_KEY"]


class TestParseFrontmatter:
    """Frontmatter 解析测试。"""

    def test_valid_frontmatter(self) -> None:
        text = "---\nid: ne-1\ntitle: Test\n---\n\nBody"
        result = _parse_frontmatter(text)
        assert result is not None
        assert result["id"] == "ne-1"

    def test_no_frontmatter(self) -> None:
        assert _parse_frontmatter("Just text") is None

    def test_unclosed_frontmatter(self) -> None:
        assert _parse_frontmatter("---\nid: ne-1") is None


class TestAPIServer:
    """FastAPI 端点集成测试。"""

    def _make_client(self, tmp_path: Path) -> TestClient:
        app = create_app(data_dir=tmp_path)
        return TestClient(app)

    def test_health_endpoint(self, tmp_path: Path) -> None:
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_list_events_empty(self, tmp_path: Path) -> None:
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/events", params={"target_id": "italy"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["events"] == []

    def test_list_events_with_data(self, tmp_path: Path) -> None:
        _write_draft(tmp_path, "italy", "ne-italy-src-20260512-abc12345")
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/events", params={"target_id": "italy"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1

    def test_list_events_pagination(self, tmp_path: Path) -> None:
        for i in range(5):
            eid = f"ne-italy-src-2026051{i}-unique{i:04d}"
            _write_draft(
                tmp_path,
                "italy",
                eid,
                title=f"Event {i}",
            )
        client = self._make_client(tmp_path)
        resp = client.get(
            "/api/v1/events",
            params={"target_id": "italy", "page": 1, "page_size": 2},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert len(data["events"]) == 2
        assert data["page"] == 1

    def test_get_event_found(self, tmp_path: Path) -> None:
        event_id = "ne-italy-src-20260512-abc12345"
        _write_draft(tmp_path, "italy", event_id)
        client = self._make_client(tmp_path)
        resp = client.get(f"/api/v1/events/{event_id}", params={"target_id": "italy"})
        assert resp.status_code == 200
        assert resp.json()["id"] == event_id

    def test_get_event_not_found(self, tmp_path: Path) -> None:
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/events/nonexistent", params={"target_id": "italy"})
        assert resp.status_code == 404

    def test_webhook_receive(self, tmp_path: Path) -> None:
        client = self._make_client(tmp_path)
        resp = client.post(
            "/api/v1/webhook",
            params={"target_id": "italy"},
            json={
                "source_id": "external-src",
                "url": "https://example.com/article",
                "title_original": "Breaking News",
                "content_original": "Content here",
                "language": "en",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "accepted"
        assert "ne-webhook-external-src" in data["event_id"]

        # 验证文件写入
        raw_dir = tmp_path / "italy" / "raw"
        assert raw_dir.is_dir()
        assert len(list(raw_dir.glob("*.md"))) == 1

    def test_webhook_minimal_payload(self, tmp_path: Path) -> None:
        client = self._make_client(tmp_path)
        resp = client.post(
            "/api/v1/webhook",
            params={"target_id": "italy"},
            json={
                "source_id": "minimal",
                "url": "https://example.com/min",
                "title_original": "Min",
            },
        )
        assert resp.status_code == 200

    def test_api_key_auth(self, tmp_path: Path) -> None:
        os.environ["NEWSSENTRY_API_KEY"] = "secret123"
        try:
            client = self._make_client(tmp_path)
            # 无 key
            resp = client.get("/api/v1/events", params={"target_id": "italy"})
            assert resp.status_code == 401
            # 错误 key
            resp = client.get(
                "/api/v1/events",
                params={"target_id": "italy"},
                headers={"X-API-Key": "wrong"},
            )
            assert resp.status_code == 401
            # 正确 key
            resp = client.get(
                "/api/v1/events",
                params={"target_id": "italy"},
                headers={"X-API-Key": "secret123"},
            )
            assert resp.status_code == 200
        finally:
            del os.environ["NEWSSENTRY_API_KEY"]

    def test_openapi_docs_available(self, tmp_path: Path) -> None:
        client = self._make_client(tmp_path)
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_openapi_json_available(self, tmp_path: Path) -> None:
        client = self._make_client(tmp_path)
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()
        assert "/api/v1/events" in schema.get("paths", {})
        assert "/api/v1/webhook" in schema.get("paths", {})

    def test_targets_endpoint(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_dir = tmp_path / "config" / "targets"
        _write_target_config(config_dir, "italy", "意大利新闻监控", "it", 5)
        _write_target_config(config_dir, "japan", "日本新闻监控", "ja", 3)
        monkeypatch.chdir(tmp_path)
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/targets")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["targets"]) == 2
        italy = next(t for t in data["targets"] if t["target_id"] == "italy")
        assert italy["display_name"] == "意大利新闻监控"
        assert italy["primary_language"] == "it"
        assert italy["source_count"] == 5

    def test_stats_endpoint(self, tmp_path: Path) -> None:
        _write_draft(
            tmp_path,
            "italy",
            "ne-1",
            title="A",
            source_id="ansa",
            news_value_score=80,
            china_relevance=20,
            classification_l0="international",
        )
        _write_draft(
            tmp_path,
            "italy",
            "ne-2",
            title="B",
            source_id="repubblica",
            news_value_score=60,
            china_relevance=40,
            classification_l0="politics",
        )
        _write_draft(
            tmp_path,
            "italy",
            "ne-3",
            title="C",
            source_id="ansa",
            news_value_score=90,
            china_relevance=10,
            classification_l0="international",
        )
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/stats", params={"target_id": "italy"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_events"] == 3
        assert data["avg_news_value_score"] == pytest.approx(76.67, rel=0.01)
        assert data["avg_china_relevance"] == pytest.approx(23.33, rel=0.01)
        assert data["by_classification"]["international"] == 2
        assert data["by_classification"]["politics"] == 1
        assert data["by_source"]["ansa"] == 2
        assert data["by_source"]["repubblica"] == 1

    def test_stats_empty_target(self, tmp_path: Path) -> None:
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/stats", params={"target_id": "empty"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_events"] == 0
        assert data["avg_news_value_score"] is None
        assert data["by_classification"] == {}

    def test_events_filter_by_classification(self, tmp_path: Path) -> None:
        _write_draft(tmp_path, "italy", "ne-1", classification_l0="international")
        _write_draft(tmp_path, "italy", "ne-2", classification_l0="politics")
        client = self._make_client(tmp_path)
        resp = client.get(
            "/api/v1/events",
            params={"target_id": "italy", "classification": "international"},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_events_filter_by_source(self, tmp_path: Path) -> None:
        _write_draft(tmp_path, "italy", "ne-1", source_id="ansa")
        _write_draft(tmp_path, "italy", "ne-2", source_id="repubblica")
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/events", params={"target_id": "italy", "source_id": "ansa"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_events_filter_by_min_score(self, tmp_path: Path) -> None:
        _write_draft(tmp_path, "italy", "ne-1", news_value_score=80)
        _write_draft(tmp_path, "italy", "ne-2", news_value_score=30)
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/events", params={"target_id": "italy", "min_score": 50})
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_events_filter_by_search(self, tmp_path: Path) -> None:
        _write_draft(tmp_path, "italy", "ne-1", title="Medio Oriente pace")
        _write_draft(tmp_path, "italy", "ne-2", title="Elezioni politiche")
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/events", params={"target_id": "italy", "search": "pace"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_events_combined_filters(self, tmp_path: Path) -> None:
        _write_draft(
            tmp_path,
            "italy",
            "ne-1",
            title="Pace in Medio Oriente",
            source_id="ansa",
            news_value_score=90,
            classification_l0="international",
        )
        _write_draft(
            tmp_path,
            "italy",
            "ne-2",
            title="Pace e guerra",
            source_id="ansa",
            news_value_score=50,
            classification_l0="politics",
        )
        _write_draft(
            tmp_path,
            "italy",
            "ne-3",
            title="Pace nel mondo",
            source_id="repubblica",
            news_value_score=80,
            classification_l0="international",
        )
        client = self._make_client(tmp_path)
        resp = client.get(
            "/api/v1/events",
            params={
                "target_id": "italy",
                "search": "pace",
                "source_id": "ansa",
                "classification": "international",
                "min_score": 80,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1


class TestConfigAPI:
    """配置读取 API 端点测试。"""

    def _make_client(self, tmp_path: Path) -> TestClient:
        app = create_app(data_dir=tmp_path)
        return TestClient(app)

    def _setup_config(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """创建标准配置目录结构并 chdir。"""
        monkeypatch.chdir(tmp_path)

    # ── Target 配置 ──

    def test_get_target_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._setup_config(tmp_path, monkeypatch)
        config_dir = tmp_path / "config" / "targets"
        _write_target_config(config_dir, "italy", "意大利新闻监控", "it", 5)
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/config/targets/italy")
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_id"] == "italy"
        assert data["display_name"] == "意大利新闻监控"
        assert data["language_scope"]["primary"] == "it"

    def test_get_target_config_not_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._setup_config(tmp_path, monkeypatch)
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/config/targets/nonexistent")
        assert resp.status_code == 404

    # ── Source 渠道 ──

    def test_list_sources(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._setup_config(tmp_path, monkeypatch)
        sources_dir = tmp_path / "config" / "sources" / "italy"
        sources_dir.mkdir(parents=True, exist_ok=True)
        # 写入 RSS 源
        src = {
            "source_id": "ansa",
            "display_name": "ANSA",
            "type": "rss",
            "enabled": True,
            "url": "https://www.ansa.it/rss",
            "credibility_base": 0.9,
        }
        (sources_dir / "ansa.yaml").write_text(
            yaml.dump(src, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/config/targets/italy/sources")
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_id"] == "italy"
        assert len(data["sources"]) == 1
        assert data["sources"][0]["source_id"] == "ansa"
        assert data["sources"][0]["type"] == "rss"
        assert data["sources"][0]["enabled"] is True

    def test_list_sources_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._setup_config(tmp_path, monkeypatch)
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/config/targets/nonexistent/sources")
        assert resp.status_code == 200
        assert resp.json()["sources"] == []

    def test_get_source_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._setup_config(tmp_path, monkeypatch)
        sources_dir = tmp_path / "config" / "sources" / "italy"
        sources_dir.mkdir(parents=True, exist_ok=True)
        src = {
            "source_id": "ansa",
            "display_name": "ANSA",
            "type": "rss",
            "url": "https://www.ansa.it/rss",
        }
        (sources_dir / "ansa.yaml").write_text(
            yaml.dump(src, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/config/targets/italy/sources/ansa")
        assert resp.status_code == 200
        assert resp.json()["source_id"] == "ansa"

    def test_get_source_config_not_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._setup_config(tmp_path, monkeypatch)
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/config/targets/italy/sources/nonexistent")
        assert resp.status_code == 404

    def test_get_source_subpath(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试子路径源渠道（如 api/gnews-italy）。"""
        self._setup_config(tmp_path, monkeypatch)
        api_dir = tmp_path / "config" / "sources" / "italy" / "api"
        api_dir.mkdir(parents=True, exist_ok=True)
        src = {"source_id": "gnews-italy", "type": "api", "enabled": True}
        (api_dir / "gnews-italy.yaml").write_text(
            yaml.dump(src, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/config/targets/italy/sources/api/gnews-italy")
        assert resp.status_code == 200
        assert resp.json()["source_id"] == "gnews-italy"

    # ── Filter 规则 ──

    def test_get_filter_rules(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._setup_config(tmp_path, monkeypatch)
        filters_dir = tmp_path / "config" / "filters" / "italy"
        filters_dir.mkdir(parents=True, exist_ok=True)
        rules = {
            "target_id": "italy",
            "score_threshold": 30,
            "max_age_hours": 48,
            "dedup_window_hours": 24,
            "keyword_rules": [
                {"keyword": "pace", "weight": 5.0, "language": "it"},
                {"keyword": "guerra", "weight": 3.0, "language": "it"},
            ],
        }
        (filters_dir / "default.yaml").write_text(
            yaml.dump(rules, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/config/targets/italy/filters")
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_id"] == "italy"
        assert data["score_threshold"] == 30
        assert data["max_age_hours"] == 48
        assert data["keyword_rules_count"] == 2
        assert len(data["keyword_rules"]) == 2

    def test_get_filter_rules_not_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._setup_config(tmp_path, monkeypatch)
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/config/targets/nonexistent/filters")
        assert resp.status_code == 404

    # ── 输出目的地 ──

    def test_list_destinations(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._setup_config(tmp_path, monkeypatch)
        output_dir = tmp_path / "config" / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        dests = {
            "destinations": [
                {
                    "destination_id": "obsidian-local",
                    "type": "obsidian_markdown",
                    "enabled": True,
                    "filter": {"min_news_value_score": 60},
                    "notes": "本地 Obsidian",
                },
                {
                    "destination_id": "feishu-alerts",
                    "type": "feishu_webhook",
                    "enabled": False,
                },
            ]
        }
        (output_dir / "destinations.yaml").write_text(
            yaml.dump(dests, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/config/output/destinations")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["destinations"]) == 2
        obs = data["destinations"][0]
        assert obs["destination_id"] == "obsidian-local"
        assert obs["enabled"] is True
        assert obs["filter_min_news_value_score"] == 60

    def test_list_destinations_empty_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._setup_config(tmp_path, monkeypatch)
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/config/output/destinations")
        assert resp.status_code == 200
        assert resp.json()["destinations"] == []

    # ── Provider 路由 ──

    def test_get_provider_routes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._setup_config(tmp_path, monkeypatch)
        provider_dir = tmp_path / "config" / "provider"
        provider_dir.mkdir(parents=True, exist_ok=True)
        routes = {
            "routes_version": "1.0",
            "routes": [
                {
                    "route_id": "translate-fast",
                    "task_type": "translate",
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                    "timeout_seconds": 15,
                    "max_cost_usd_per_call": 0.001,
                    "audit": False,
                    "fallback_route_ids": ["translate-local"],
                },
            ],
            "fallback_route_id": "rules-judge",
        }
        (provider_dir / "routes.yaml").write_text(
            yaml.dump(routes, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/config/provider/routes")
        assert resp.status_code == 200
        data = resp.json()
        assert data["routes_version"] == "1.0"
        assert len(data["routes"]) == 1
        assert data["routes"][0]["route_id"] == "translate-fast"
        assert data["routes"][0]["provider"] == "openai"
        assert data["fallback_route_id"] == "rules-judge"

    def test_get_provider_routes_not_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._setup_config(tmp_path, monkeypatch)
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/config/provider/routes")
        assert resp.status_code == 404


class TestAPIServerSQLite:
    """使用 AsyncStore（SQLite）的 API Server 端点测试。"""

    @pytest.fixture
    async def store_with_data(self, tmp_path: Path) -> AsyncStore:
        """创建包含测试数据的 AsyncStore。"""
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
            },
            {
                "event_id": "ne-italy-repubblica-20260512-bbb22222",
                "source_id": "repubblica",
                "news_value_score": 60,
                "china_relevance": 40,
                "classification_l0": "politics",
                "title_original": "Elezioni politiche",
            },
            {
                "event_id": "ne-italy-ansa-20260512-ccc33333",
                "source_id": "ansa",
                "news_value_score": 90,
                "china_relevance": 10,
                "classification_l0": "international",
                "title_original": "Accordo commerciale",
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
                "published_at, file_path, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                ),
            )
        await store._db.commit()  # noqa: SLF001
        return store

    def _make_client_with_store(self, tmp_path: Path, store: AsyncStore) -> TestClient:
        app = create_app(data_dir=tmp_path, store=store)
        return TestClient(app)

    def test_stats_with_sqlite(
        self,
        tmp_path: Path,
        store_with_data: AsyncStore,
    ) -> None:
        client = self._make_client_with_store(tmp_path, store_with_data)
        resp = client.get("/api/v1/stats", params={"target_id": "italy"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_events"] == 3
        assert data["avg_news_value_score"] is not None
        assert data["by_classification"]["international"] == 2
        assert data["by_classification"]["politics"] == 1
        assert data["by_source"]["ansa"] == 2

    def test_list_events_with_sqlite(
        self,
        tmp_path: Path,
        store_with_data: AsyncStore,
    ) -> None:
        client = self._make_client_with_store(tmp_path, store_with_data)
        resp = client.get("/api/v1/events", params={"target_id": "italy"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["events"]) == 3

    def test_list_events_pagination_with_sqlite(
        self,
        tmp_path: Path,
        store_with_data: AsyncStore,
    ) -> None:
        client = self._make_client_with_store(tmp_path, store_with_data)
        resp = client.get(
            "/api/v1/events",
            params={"target_id": "italy", "page": 1, "page_size": 2},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["events"]) == 2
        assert data["page"] == 1

    def test_list_events_filter_source_with_sqlite(
        self,
        tmp_path: Path,
        store_with_data: AsyncStore,
    ) -> None:
        client = self._make_client_with_store(tmp_path, store_with_data)
        resp = client.get(
            "/api/v1/events",
            params={"target_id": "italy", "source_id": "ansa"},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    def test_list_events_filter_classification_with_sqlite(
        self,
        tmp_path: Path,
        store_with_data: AsyncStore,
    ) -> None:
        client = self._make_client_with_store(tmp_path, store_with_data)
        resp = client.get(
            "/api/v1/events",
            params={"target_id": "italy", "classification": "politics"},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_list_events_filter_min_score_with_sqlite(
        self,
        tmp_path: Path,
        store_with_data: AsyncStore,
    ) -> None:
        client = self._make_client_with_store(tmp_path, store_with_data)
        resp = client.get(
            "/api/v1/events",
            params={"target_id": "italy", "min_score": 70},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    def test_list_events_search_with_sqlite(
        self,
        tmp_path: Path,
        store_with_data: AsyncStore,
    ) -> None:
        client = self._make_client_with_store(tmp_path, store_with_data)
        resp = client.get(
            "/api/v1/events",
            params={"target_id": "italy", "search": "pace"},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_get_single_event_with_sqlite(
        self,
        tmp_path: Path,
        store_with_data: AsyncStore,
    ) -> None:
        client = self._make_client_with_store(tmp_path, store_with_data)
        resp = client.get(
            "/api/v1/events/ne-italy-ansa-20260512-aaa11111",
            params={"target_id": "italy"},
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == "ne-italy-ansa-20260512-aaa11111"

    def test_get_single_event_not_found_with_sqlite(
        self,
        tmp_path: Path,
        store_with_data: AsyncStore,
    ) -> None:
        client = self._make_client_with_store(tmp_path, store_with_data)
        resp = client.get(
            "/api/v1/events/nonexistent",
            params={"target_id": "italy"},
        )
        assert resp.status_code == 404
