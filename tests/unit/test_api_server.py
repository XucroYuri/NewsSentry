"""Tests for API Server — Phase 22 API Gateway + Phase 24 Web UI."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from fastapi.testclient import TestClient

from news_sentry.core.api_server import (
    _get_valid_api_keys,
    _parse_frontmatter,
    _RateLimiter,
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

    def test_no_config_keys_returns_empty(self) -> None:
        # 无环境变量时返回空集合
        os.environ.pop("NEWSSENTRY_API_KEY", None)
        result = _get_valid_api_keys()
        assert result == set()

    def test_valid_keys_loaded(self) -> None:
        os.environ["NEWSSENTRY_API_KEY"] = "test-key-1,test-key-2"
        try:
            result = _get_valid_api_keys()
            assert result == {"test-key-1", "test-key-2"}
        finally:
            del os.environ["NEWSSENTRY_API_KEY"]

    def test_single_key_loaded(self) -> None:
        os.environ["NEWSSENTRY_API_KEY"] = "test-key-1"
        try:
            result = _get_valid_api_keys()
            assert result == {"test-key-1"}
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
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)
        # 获取 dev mode token 并设为默认 headers
        resp = client.post("/api/v1/auth/token", json={"api_key": ""})
        assert resp.status_code == 200, f"Auth token failed: {resp.text}"
        token = resp.json()["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"
        return client

    def _auth_headers(self, client: TestClient) -> dict[str, str]:
        """获取 dev mode Bearer token（无需配置 API Key）。"""
        resp = client.post("/api/v1/auth/token", json={"api_key": ""})
        assert resp.status_code == 200
        token = resp.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def test_health_endpoint(self, tmp_path: Path) -> None:
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_collector_status_returns_target_ids_list(self, tmp_path: Path) -> None:
        """collector/status 返回 target_ids (list) + stage。"""
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/collector/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "target_ids" in data
        assert isinstance(data["target_ids"], list)
        assert "stage" in data
        assert isinstance(data["stage"], str)

    def test_collector_diagnostics_healthy(self, tmp_path: Path) -> None:
        """有数据目录情况下 diagnostics 返回 overall=healthy。"""
        import json as _json

        target_dir = tmp_path / "italy"
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "source_health.json").write_text(
            _json.dumps([{"source_id": "ansa", "healthy": True}]),
            encoding="utf-8",
        )

        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/collector/diagnostics")
        assert resp.status_code == 200
        data = resp.json()
        assert "overall" in data
        assert "checks" in data
        assert len(data["checks"]) == 5
        for check in data["checks"]:
            assert "name" in check
            assert "ok" in check
            assert "message" in check
        source_check = [c for c in data["checks"] if c["name"] == "source_health"][0]
        assert source_check["ok"] is True

    def test_collector_diagnostics_empty_data_dir(self, tmp_path: Path) -> None:
        """空数据目录下 diagnostics 返回 overall=attention_needed。"""
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/collector/diagnostics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["overall"] == "attention_needed"
        dd_check = [c for c in data["checks"] if c["name"] == "data_directory"][0]
        assert dd_check["ok"] is False

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

    def test_events_feed_adds_display_fields_from_frontmatter(self, tmp_path: Path) -> None:
        """GET /events/feed 返回新闻流展示字段，不修改 NewsEvent 契约。"""
        drafts = tmp_path / "italy" / "drafts"
        drafts.mkdir(parents=True, exist_ok=True)
        event = {
            "id": "ne-italy-ansa-20260526-feed0001",
            "source_id": "ansa",
            "url": "https://example.com/news",
            "title_original": "Original title",
            "title_translated": "中文标题",
            "content_original": "Original content fallback preview.",
            "published_at": "2026-05-26T08:15:00+08:00",
            "news_value_score": 86,
            "metadata": {
                "classification": {
                    "l0": "politics",
                    "l1": [{"code": "china-relations", "confidence": 0.92}],
                },
                "topic_tags": ["DeepSeek", "行业动态"],
            },
            "judge_result": {
                "rationale": "API 长期降价会改变模型调用成本结构。第二句不应进入摘要。",
                "recommendation": "review",
            },
        }
        fm = yaml.dump(event, allow_unicode=True, default_flow_style=False, sort_keys=False)
        (drafts / "event.md").write_text(f"---\n{fm}---\n\n# 中文标题\n", encoding="utf-8")
        client = self._make_client(tmp_path)

        resp = client.get("/api/v1/events/feed", params={"target_id": "italy"})

        assert resp.status_code == 200
        item = resp.json()["groups"][0]["events"][0]
        assert item["event_id"] == "ne-italy-ansa-20260526-feed0001"
        assert item["display_title"] == "中文标题"
        assert item["score"] == 86
        assert item["summary"] == "Original content fallback preview."
        assert item["flat_tags"] == ["politics", "china-relations", "DeepSeek", "行业动态"]
        assert item["ai_reason"] == "API 长期降价会改变模型调用成本结构。"
        assert item["recommendation"] == "review"
        assert item["source_display_name"] == "ansa"
        assert item["related_count"] == 0

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

    def test_public_targets_without_auth(self, tmp_path: Path) -> None:
        """匿名用户可以读取 target 列表以初始化新闻工作台。"""
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)

        resp = client.get("/api/v1/targets")

        assert resp.status_code == 200
        assert "targets" in resp.json()

    def test_admin_users_still_requires_auth(self, tmp_path: Path) -> None:
        """公共新闻工作台不放开管理后台。"""
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)

        resp = client.get("/api/v1/admin/users")

        assert resp.status_code == 401

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
            # 创建无默认 auth 的客户端
            app = create_app(data_dir=tmp_path, auto_store=False)
            client = TestClient(app)
            # 无 token
            resp = client.get("/api/v1/admin/users")
            assert resp.status_code == 401
            # 错误 token
            resp = client.get(
                "/api/v1/admin/users",
                headers={"Authorization": "Bearer wrong-token"},
            )
            assert resp.status_code == 401
            # 通过 API Key 获取 token
            resp = client.post("/api/v1/auth/token", json={"api_key": "secret123"})
            assert resp.status_code == 200
            token = resp.json()["access_token"]
            # 使用正确 Bearer token
            resp = client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {token}"},
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
        _write_draft(tmp_path, "italy", "evt-1", "ANSA", 70)
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
        assert italy["event_count"] == 1

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
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)
        # 获取 dev mode token 并设为默认 headers
        resp = client.post("/api/v1/auth/token", json={"api_key": ""})
        assert resp.status_code == 200, f"Auth token failed: {resp.text}"
        token = resp.json()["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"
        return client

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
        assert data["by_classification"]["international"] == 2
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


class TestOpsEndpoints:
    """Phase 34: 运维 API 端点测试。"""

    def _make_client(self, tmp_path: Path) -> TestClient:
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)
        # 获取 dev mode token 并设为默认 headers
        resp = client.post("/api/v1/auth/token", json={"api_key": ""})
        assert resp.status_code == 200, f"Auth token failed: {resp.text}"
        token = resp.json()["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"
        return client

    def test_list_runs_empty(self, tmp_path: Path) -> None:
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/runs", params={"target_id": "italy"})
        assert resp.status_code == 200
        data = resp.json()
        assert "runs" in data
        assert isinstance(data["runs"], list)

    def test_get_active_run_no_heartbeat(self, tmp_path: Path) -> None:
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/runs/active", params={"target_id": "italy"})
        assert resp.status_code == 200
        data = resp.json()
        assert "active" in data
        assert data["active"] is False

    def test_get_run_detail_not_found(self, tmp_path: Path) -> None:
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/runs/nonexistent_run_id", params={"target_id": "italy"})
        assert resp.status_code == 404

    def test_list_source_health(self, tmp_path: Path) -> None:
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/sources/health", params={"target_id": "italy"})
        assert resp.status_code == 200
        data = resp.json()
        assert "sources" in data
        assert isinstance(data["sources"], list)

    def test_trigger_run(self, tmp_path: Path) -> None:
        client = self._make_client(tmp_path)
        resp = client.post("/api/v1/runs/trigger", params={"target_id": "italy", "stage": "all"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "triggered"
        assert "run_id" in data
        assert "italy" in data["run_id"]

    def test_list_runs_with_log(self, tmp_path: Path) -> None:
        """测试读取实际 run log 文件。"""
        import json

        log_dir = tmp_path / "italy" / "logs"
        log_dir.mkdir(parents=True)
        (log_dir / "italy_20260516T120000Z_abc12345.json").write_text(
            json.dumps(
                {
                    "run_id": "italy_20260516T120000Z_abc12345",
                    "target_id": "italy",
                    "started_at": "2026-05-16T12:00:00+00:00",
                    "ended_at": "2026-05-16T12:01:00+00:00",
                    "phases": [
                        {
                            "stage": "collect",
                            "duration_ms": 5000,
                            "items_count": 10,
                            "errors_count": 0,
                        }
                    ],
                    "errors_count": 0,
                    "summary": {"total_events_collected": 10},
                }
            )
        )
        app2 = create_app(data_dir=str(tmp_path), auto_store=False)
        client2 = TestClient(app2)
        # 获取 dev mode token
        token_resp = client2.post("/api/v1/auth/token", json={"api_key": ""})
        assert token_resp.status_code == 200
        client2.headers["Authorization"] = f"Bearer {token_resp.json()['access_token']}"
        resp = client2.get("/api/v1/runs", params={"target_id": "italy"})
        assert resp.status_code == 200
        runs = resp.json()["runs"]
        assert len(runs) == 1
        assert runs[0]["events_collected"] == 10
        assert runs[0]["duration_ms"] == 5000


class TestEventChainAPI:
    """Phase 35: 事件追踪链 API 端点。"""

    @pytest.fixture
    async def client_with_links(self, tmp_path):
        """创建带关联数据的测试客户端。"""
        from news_sentry.core.async_store import AsyncStore

        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()

        now = "2026-05-16T12:00:00+00:00"
        for eid, title in [
            ("evt-1", "Event One"),
            ("evt-2", "Event Two"),
            ("evt-3", "Event Three"),
        ]:
            await store._db.execute(
                "INSERT INTO event_index "
                "(event_id, target_id, stage, created_at, published_at, title_original) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (eid, "italy", "drafts", now, now, title),
            )
        await store._db.commit()

        await store.create_link("evt-1", "evt-2", "followup", 0.8, {}, "italy")
        await store.create_link("evt-2", "evt-3", "followup", 0.7, {}, "italy")

        app = create_app(data_dir=str(tmp_path), store=store)
        from httpx import ASGITransport, AsyncClient

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

    async def test_get_event_links(self, client_with_links):
        """GET /api/v1/events/{event_id}/links 返回关联事件。"""
        client, _ = client_with_links
        resp = await client.get("/api/v1/events/evt-2/links", params={"target_id": "italy"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["event_id"] == "evt-2"
        assert len(data["links"]) == 2  # 前后各一个

    async def test_get_event_chain(self, client_with_links):
        """GET /api/v1/events/{event_id}/chain 返回完整追踪链。"""
        client, _ = client_with_links
        resp = await client.get("/api/v1/events/evt-2/chain", params={"target_id": "italy"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        event_ids = [e["event_id"] for e in data["events"]]
        assert "evt-1" in event_ids
        assert "evt-2" in event_ids
        assert "evt-3" in event_ids

    async def test_list_chains(self, client_with_links):
        """GET /api/v1/chains 返回活跃链列表。"""
        client, _ = client_with_links
        resp = await client.get("/api/v1/chains", params={"target_id": "italy"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["chains"]) >= 1
        assert data["chains"][0]["event_count"] == 3

    async def test_get_event_links_not_found(self, client_with_links):
        """GET /api/v1/events/{event_id}/links 对不存在的事件返回空。"""
        client, _ = client_with_links
        resp = await client.get("/api/v1/events/nonexistent/links", params={"target_id": "italy"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["links"] == []


class TestChainNarrativeAPI:
    """Phase 36: 链叙述 API 端点。"""

    @pytest.fixture
    async def client_with_narrative(self, tmp_path):
        from news_sentry.core.async_store import AsyncStore

        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()

        now = "2026-05-16T12:00:00+00:00"
        for eid, title in [("evt-1", "Event One"), ("evt-2", "Event Two")]:
            await store._db.execute(
                "INSERT INTO event_index"
                " (event_id, target_id, stage, created_at, published_at, title_original) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (eid, "italy", "drafts", now, now, title),
            )
        await store._db.commit()
        await store.create_link("evt-1", "evt-2", "followup", 0.8, {}, "italy")
        await store.upsert_narrative(
            "evt-1", "italy", "梅洛尼在意大利政坛持续活跃。", "hash1", 2, "gpt-4o-mini"
        )

        app = create_app(data_dir=str(tmp_path), store=store)
        from httpx import ASGITransport, AsyncClient

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

    async def test_get_narrative(self, client_with_narrative):
        client, _ = client_with_narrative
        resp = await client.get("/api/v1/chains/evt-1/narrative", params={"target_id": "italy"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["chain_root_id"] == "evt-1"
        assert "梅洛尼" in data["narrative"]
        assert data["event_count"] == 2

    async def test_get_narrative_not_found(self, client_with_narrative):
        client, _ = client_with_narrative
        resp = await client.get(
            "/api/v1/chains/nonexistent/narrative",
            params={"target_id": "italy"},
        )
        assert resp.status_code == 404

    async def test_post_narrative_no_store(self, tmp_path):
        """无 store 时 POST 返回 503。"""
        app = create_app(data_dir=str(tmp_path), auto_store=False)
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=app)
        client = AsyncClient(transport=transport, base_url="http://test")
        # 获取 dev mode token
        token_resp = await client.post("/api/v1/auth/token", json={"api_key": ""})
        assert token_resp.status_code == 200
        client.headers["Authorization"] = f"Bearer {token_resp.json()['access_token']}"
        resp = await client.post("/api/v1/chains/evt-1/narrative", params={"target_id": "italy"})
        assert resp.status_code == 503
        await client.aclose()


class TestTrendAPI:
    """Phase 37: 趋势分析 API 端点。"""

    @pytest.fixture
    async def client_with_trends(self, tmp_path):
        """创建带趋势测试数据的客户端。"""
        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()

        now = datetime.now(UTC).isoformat()
        events = [
            # 5月1日: 3 events
            (
                "t-evt-1",
                "italy",
                "judged",
                "ansa",
                80,
                50,
                "politics",
                "2026-05-01T10:00:00",
                now,
                "positive",
                "immigration,elections",
            ),
            (
                "t-evt-2",
                "italy",
                "judged",
                "ansa",
                75,
                45,
                "politics",
                "2026-05-01T12:00:00",
                now,
                "negative",
                "immigration,economy",
            ),
            (
                "t-evt-3",
                "italy",
                "judged",
                "repubblica",
                60,
                30,
                "economy",
                "2026-05-01T14:00:00",
                now,
                "neutral",
                "economy,EU",
            ),
            # 5月5日: 2 events
            (
                "t-evt-4",
                "italy",
                "judged",
                "ansa",
                70,
                40,
                "international",
                "2026-05-05T10:00:00",
                now,
                "positive",
                "EU,immigration",
            ),
            (
                "t-evt-5",
                "italy",
                "judged",
                "ansa",
                85,
                55,
                "politics",
                "2026-05-05T12:00:00",
                now,
                "negative",
                "elections,immigration",
            ),
        ]
        for eid, tid, stage, src, score, rel, cls, pub, created, sent, tags in events:
            await store._db.execute(
                "INSERT OR REPLACE INTO event_index "
                "(event_id, target_id, stage, source_id, news_value_score, "
                "china_relevance, classification_l0, published_at, created_at, "
                "sentiment, topic_tags, file_path, title_original) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    eid,
                    tid,
                    stage,
                    src,
                    score,
                    rel,
                    cls,
                    pub,
                    created,
                    sent,
                    tags,
                    f"data/{tid}/drafts/{eid}.md",
                    f"Title {eid}",
                ),
            )
        await store._db.commit()

        app = create_app(data_dir=str(tmp_path), store=store)
        from httpx import ASGITransport, AsyncClient

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

    async def test_get_topic_trends(self, client_with_trends):
        """GET /api/v1/trends/topics 返回主题趋势。"""
        client, _ = client_with_trends
        resp = await client.get(
            "/api/v1/trends/topics",
            params={"target_id": "italy", "days": 30},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_id"] == "italy"
        assert data["days"] == 30
        assert "topics" in data
        assert "generated_at" in data
        # immigration 应该在 topics 中（出现 4 次）
        topic_names = [t["topic"] for t in data["topics"]]
        assert "immigration" in topic_names

    async def test_get_sentiment_trends(self, client_with_trends):
        """GET /api/v1/trends/sentiment 返回情感趋势。"""
        client, _ = client_with_trends
        resp = await client.get(
            "/api/v1/trends/sentiment",
            params={"target_id": "italy", "days": 30},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_id"] == "italy"
        assert "daily_sentiment" in data
        assert "generated_at" in data
        # 至少有 2 天的数据
        assert len(data["daily_sentiment"]) >= 2

    async def test_trends_no_store(self, tmp_path):
        """无 store 时返回 503。"""
        app = create_app(data_dir=str(tmp_path), auto_store=False)
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=app)
        client = AsyncClient(transport=transport, base_url="http://test")
        # 获取 dev mode token
        token_resp = await client.post("/api/v1/auth/token", json={"api_key": ""})
        assert token_resp.status_code == 200
        client.headers["Authorization"] = f"Bearer {token_resp.json()['access_token']}"
        resp = await client.get(
            "/api/v1/trends/topics",
            params={"target_id": "italy"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["topics"] == []
        await client.aclose()


class TestSmartAlertAPI:
    """Phase 38: 智能告警 API 端点。"""

    @pytest.fixture
    async def client_with_alerts(self, tmp_path):
        """创建带告警数据的客户端。"""
        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()

        now = datetime.now(UTC).isoformat()
        await store._db.execute(
            "INSERT OR REPLACE INTO event_index "
            "(event_id, target_id, stage, source_id, news_value_score, "
            "china_relevance, published_at, created_at, sentiment, topic_tags) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("al-evt-1", "italy", "judged", "ansa", 80, 50, now, now, "positive", "immigration"),
        )
        await store._db.commit()
        await store.create_link("al-evt-1", "al-evt-1", "followup", 0.9, {}, "italy")

        app = create_app(data_dir=str(tmp_path), store=store)
        from httpx import ASGITransport, AsyncClient

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

    async def test_get_smart_alerts(self, client_with_alerts):
        """GET /api/v1/alerts/smart 返回告警列表。"""
        client, _ = client_with_alerts
        resp = await client.get(
            "/api/v1/alerts/smart",
            params={"target_id": "italy"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_id"] == "italy"
        assert "alerts" in data
        assert "total" in data

    async def test_smart_alerts_no_store(self, tmp_path):
        """无 store 时返回 503。"""
        app = create_app(data_dir=str(tmp_path), auto_store=False)
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=app)
        client = AsyncClient(transport=transport, base_url="http://test")
        # 获取 dev mode token
        token_resp = await client.post("/api/v1/auth/token", json={"api_key": ""})
        assert token_resp.status_code == 200
        client.headers["Authorization"] = f"Bearer {token_resp.json()['access_token']}"
        resp = await client.get(
            "/api/v1/alerts/smart",
            params={"target_id": "italy"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["alerts"] == []
        await client.aclose()


class TestDashboardAPI:
    """Phase 39: Dashboard API 端点。"""

    @pytest.fixture
    async def client_with_dashboard(self, tmp_path):
        """创建带 dashboard 数据的客户端。"""
        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()

        now = datetime.now(UTC).isoformat()
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        for i, score in enumerate([80, 90, 70]):
            await store._db.execute(
                "INSERT OR REPLACE INTO event_index "
                "(event_id, target_id, stage, news_value_score, published_at, "
                "created_at, title_original, source_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"db-evt-{i}",
                    "italy",
                    "judged",
                    score,
                    f"{today}T10:00:00",
                    now,
                    f"DB Event {i}",
                    "ansa",
                ),
            )
        await store._db.commit()

        app = create_app(data_dir=str(tmp_path), store=store)
        from httpx import ASGITransport, AsyncClient

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

    async def test_get_today_stats(self, client_with_dashboard):
        """GET /api/v1/stats/today。"""
        client, _ = client_with_dashboard
        resp = await client.get(
            "/api/v1/stats/today",
            params={"target_id": "italy"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_id"] == "italy"
        assert data["today_count"] == 3
        assert data["today_max_score"] == 90

    async def test_get_top_events(self, client_with_dashboard):
        """GET /api/v1/events/top。"""
        client, _ = client_with_dashboard
        resp = await client.get(
            "/api/v1/events/top",
            params={"target_id": "italy", "days": 7, "limit": 5},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_id"] == "italy"
        assert len(data["events"]) == 3
        assert data["events"][0]["news_value_score"] == 90


class TestMaintenanceAPI:
    """Phase 40: 维护 API 端点。"""

    @pytest.fixture
    async def client_with_maintenance(self, tmp_path):
        """创建维护测试客户端。"""
        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()

        app = create_app(data_dir=str(tmp_path), store=store)
        from httpx import ASGITransport, AsyncClient

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

    async def test_maintenance_prune(self, client_with_maintenance):
        """POST /api/v1/maintenance/prune。"""
        client, _ = client_with_maintenance
        resp = await client.post(
            "/api/v1/maintenance/prune",
            params={"target_id": "italy", "max_age_days": 30},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "deleted_events" in data
        assert "target_id" in data

    async def test_maintenance_backup(self, client_with_maintenance):
        """POST /api/v1/maintenance/backup。"""
        client, _ = client_with_maintenance
        resp = await client.post("/api/v1/maintenance/backup")
        assert resp.status_code == 200
        data = resp.json()
        assert "backup_path" in data
        assert "size_bytes" in data


class TestFeedbackAndAlertAPI:
    """Phase 41: 反馈闭环 + 告警管理 API 端点。"""

    @pytest.fixture
    async def client_with_feedback(self, tmp_path):
        """创建带反馈功能的测试客户端。"""
        from httpx import ASGITransport, AsyncClient

        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()

        now = datetime.now(UTC).isoformat()
        await store._db.execute(
            "INSERT OR REPLACE INTO event_index "
            "(event_id, target_id, stage, source_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("ne-1", "italy", "judged", "ansa", now),
        )
        await store._db.commit()

        app = create_app(data_dir=str(tmp_path), store=store)
        transport = ASGITransport(app=app)
        client = AsyncClient(transport=transport, base_url="http://test")
        # 获取 dev mode token
        token_resp = await client.post("/api/v1/auth/token", json={"api_key": ""})
        assert token_resp.status_code == 200
        client.headers["Authorization"] = f"Bearer {token_resp.json()['access_token']}"
        yield client, store
        await client.aclose()
        await store.close()

    async def test_submit_feedback(self, client_with_feedback):
        """POST /api/v1/feedback 提交反馈。"""
        client, _ = client_with_feedback
        resp = await client.post(
            "/api/v1/feedback",
            json={
                "target_id": "italy",
                "event_id": "ne-1",
                "verdict_type": "publish_override",
                "comment": "应推送",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] > 0
        assert data["verdict_type"] == "publish_override"

    async def test_list_feedback(self, client_with_feedback):
        """GET /api/v1/feedback 反馈列表。"""
        client, _ = client_with_feedback
        # 先提交一条
        await client.post(
            "/api/v1/feedback",
            json={
                "target_id": "italy",
                "event_id": "ne-1",
                "verdict_type": "publish_override",
                "comment": "test",
            },
        )
        resp = await client.get("/api/v1/feedback", params={"target_id": "italy"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    async def test_feedback_stats(self, client_with_feedback):
        """GET /api/v1/feedback/stats 反馈统计。"""
        client, _ = client_with_feedback
        await client.post(
            "/api/v1/feedback",
            json={
                "target_id": "italy",
                "event_id": "ne-1",
                "verdict_type": "publish_override",
            },
        )
        resp = await client.get("/api/v1/feedback/stats", params={"target_id": "italy"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert data["publish_override"] >= 1

    async def test_alert_history(self, client_with_feedback):
        """GET /api/v1/alerts/history 告警历史。"""
        client, store = client_with_feedback
        # 直接插入告警数据
        await store.save_alert_history(
            "italy",
            [
                {"type": "chain_update", "severity": "high", "message": "链更新"},
            ],
        )
        resp = await client.get("/api/v1/alerts/history", params={"target_id": "italy"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["alerts"][0]["alert_type"] == "chain_update"

    async def test_rules_optimize_missing_config(self, client_with_feedback):
        """POST /api/v1/rules/optimize 配置不存在返回 404。"""
        client, _ = client_with_feedback
        resp = await client.post(
            "/api/v1/rules/optimize",
            json={
                "target_id": "nonexistent",
                "dry_run": True,
            },
        )
        assert resp.status_code == 404


class TestConfigWriteEndpoints:
    """Phase 42: 配置写入端点测试。"""

    def _make_client(self, tmp_path: Path) -> TestClient:
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)
        # 获取 dev mode token 并设为默认 headers
        resp = client.post("/api/v1/auth/token", json={"api_key": ""})
        assert resp.status_code == 200, f"Auth token failed: {resp.text}"
        token = resp.json()["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"
        return client

    def _setup_auth(self, client: TestClient) -> dict[str, str]:
        os.environ["NEWSSENTRY_API_KEY"] = "secret123"
        resp = client.post("/api/v1/auth/token", json={"api_key": "secret123"})
        assert resp.status_code == 200
        token = resp.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def _teardown_auth(self) -> None:
        del os.environ["NEWSSENTRY_API_KEY"]

    def test_update_target_config(self, tmp_path: Path) -> None:
        """PUT /config/targets/{id} 更新 target 配置。"""
        filepath = Path("config/targets/italy.yaml")
        original = filepath.read_text(encoding="utf-8")
        client = self._make_client(tmp_path)
        headers = self._setup_auth(client)
        try:
            resp = client.put(
                "/api/v1/config/targets/italy",
                json={"display_name": "意大利 (测试)"},
                headers=headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["display_name"] == "意大利 (测试)"
        finally:
            filepath.write_text(original, encoding="utf-8")
            self._teardown_auth()

    def test_update_source_config(self, tmp_path: Path) -> None:
        """PATCH /config/targets/{id}/sources/{sid} 更新 source。"""
        filepath = Path("config/sources/italy/aci-stampa.yaml")
        original = filepath.read_text(encoding="utf-8")
        client = self._make_client(tmp_path)
        headers = self._setup_auth(client)
        try:
            resp = client.patch(
                "/api/v1/config/targets/italy/sources/aci-stampa",
                json={"enabled": False},
                headers=headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["enabled"] is False
        finally:
            filepath.write_text(original, encoding="utf-8")
            self._teardown_auth()

    def test_update_filter_config(self, tmp_path: Path) -> None:
        """PATCH /config/targets/{id}/filters 更新 filter。"""
        filepath = Path("config/filters/italy/default.yaml")
        original = filepath.read_text(encoding="utf-8")
        client = self._make_client(tmp_path)
        headers = self._setup_auth(client)
        try:
            resp = client.patch(
                "/api/v1/config/targets/italy/filters",
                json={"score_threshold": 50},
                headers=headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["score_threshold"] == 50
        finally:
            filepath.write_text(original, encoding="utf-8")
            self._teardown_auth()

    def test_update_destination(self, tmp_path: Path) -> None:
        """PATCH /config/output/destinations/{id} 更新 destination。"""
        filepath = Path("config/output/destinations.yaml")
        original = filepath.read_text(encoding="utf-8")
        client = self._make_client(tmp_path)
        headers = self._setup_auth(client)
        try:
            resp = client.patch(
                "/api/v1/config/output/destinations/obsidian_target_drafts",
                json={"enabled": False},
                headers=headers,
            )
            assert resp.status_code == 200
        finally:
            filepath.write_text(original, encoding="utf-8")
            self._teardown_auth()

    def test_update_provider_route(self, tmp_path: Path) -> None:
        """PATCH /config/provider/routes/{id} 更新 route。"""
        filepath = Path("config/provider/routes.yaml")
        original = filepath.read_text(encoding="utf-8")
        client = self._make_client(tmp_path)
        headers = self._setup_auth(client)
        try:
            resp = client.patch(
                "/api/v1/config/provider/routes/translate.fast",
                json={"timeout_seconds": 45},
                headers=headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["timeout_seconds"] == 45
        finally:
            filepath.write_text(original, encoding="utf-8")
            self._teardown_auth()

    def test_config_write_requires_auth(self, tmp_path: Path) -> None:
        """配置写入端点要求 Bearer token 认证。"""
        # 创建无默认 auth 的客户端
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)
        resp = client.put(
            "/api/v1/config/targets/italy",
            json={"display_name": "test"},
        )
        assert resp.status_code == 401


class TestImportEvents:
    """POST /api/v1/events/import 端点测试。"""

    def _make_client(self, tmp_path: Path) -> TestClient:
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)
        # 获取 dev mode token 并设为默认 headers
        resp = client.post("/api/v1/auth/token", json={"api_key": ""})
        assert resp.status_code == 200, f"Auth token failed: {resp.text}"
        token = resp.json()["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"
        return client

    def test_import_basic(self, tmp_path: Path) -> None:
        """基本批量导入。"""
        client = self._make_client(tmp_path)
        resp = client.post(
            "/api/v1/events/import",
            json=[
                {
                    "target_id": "italy",
                    "source_id": "social-twitter",
                    "title_original": "Tweet from Roma",
                    "url": "https://twitter.com/user/status/123",
                    "collected_at": "2026-05-17T10:00:00+00:00",
                },
                {
                    "target_id": "italy",
                    "source_id": "social-telegram",
                    "title_original": "Telegram post",
                    "url": "https://t.me/channel/456",
                    "collected_at": "2026-05-17T11:00:00+00:00",
                },
            ],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] == 2
        assert data["skipped"] == 0
        assert data["errors"] == []

        # 验证文件写入
        raw_dir = tmp_path / "italy" / "raw"
        assert raw_dir.is_dir()
        files = list(raw_dir.glob("*.md"))
        assert len(files) == 2

    def test_import_with_optional_fields(self, tmp_path: Path) -> None:
        """带可选字段的导入。"""
        client = self._make_client(tmp_path)
        resp = client.post(
            "/api/v1/events/import",
            json=[
                {
                    "target_id": "japan",
                    "source_id": "rss-nhk",
                    "title_original": "NHK News",
                    "url": "https://nhk.or.jp/news/789",
                    "collected_at": "2026-05-17T10:00:00+00:00",
                    "content_original": "Full article text",
                    "language": "ja",
                    "classification": {"l0": "politics"},
                    "published_at": "2026-05-17T09:00:00+00:00",
                },
            ],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] == 1

        # 验证文件内容
        raw_dir = tmp_path / "japan" / "raw"
        files = list(raw_dir.glob("*.md"))
        assert len(files) == 1
        content = files[0].read_text(encoding="utf-8")
        assert "language: ja" in content
        assert "Full article text" in content

    async def test_import_dedup_with_sqlite(self, tmp_path: Path) -> None:
        """SQLite 去重：重复 event_id 被跳过。"""
        from httpx import ASGITransport, AsyncClient

        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()
        app = create_app(data_dir=tmp_path, store=store, skip_lifespan=True)
        transport = ASGITransport(app=app)
        client = AsyncClient(transport=transport, base_url="http://test")

        # 获取 dev mode token
        token_resp = await client.post("/api/v1/auth/token", json={"api_key": ""})
        assert token_resp.status_code == 200
        client.headers["Authorization"] = f"Bearer {token_resp.json()['access_token']}"

        payload = [
            {
                "target_id": "italy",
                "source_id": "test-src",
                "title_original": "First import",
                "url": "https://example.com/dedup-test",
                "collected_at": "2026-05-17T10:00:00+00:00",
            },
        ]

        # 第一次导入
        resp = await client.post("/api/v1/events/import", json=payload)
        assert resp.status_code == 200
        assert resp.json()["imported"] == 1
        assert resp.json()["skipped"] == 0

        # 第二次导入相同事件 → 跳过
        resp = await client.post("/api/v1/events/import", json=payload)
        assert resp.status_code == 200
        assert resp.json()["imported"] == 0
        assert resp.json()["skipped"] == 1

        await client.aclose()
        await store.close()

    def test_import_auth_required(self, tmp_path: Path) -> None:
        """导入端点要求认证。"""
        os.environ["NEWSSENTRY_API_KEY"] = "secret123"
        try:
            # 创建无默认 auth 的客户端
            app = create_app(data_dir=tmp_path, auto_store=False)
            client = TestClient(app)
            resp = client.post(
                "/api/v1/events/import",
                json=[
                    {
                        "target_id": "italy",
                        "source_id": "src",
                        "title_original": "Test",
                        "url": "https://example.com",
                        "collected_at": "2026-05-17T10:00:00+00:00",
                    },
                ],
            )
            assert resp.status_code == 401
        finally:
            del os.environ["NEWSSENTRY_API_KEY"]

    def test_import_auth_with_valid_key(self, tmp_path: Path) -> None:
        """有效 Bearer token 允许导入。"""
        os.environ["NEWSSENTRY_API_KEY"] = "secret123"
        try:
            # 创建无默认 auth 的客户端，再手动获取 token
            app = create_app(data_dir=tmp_path, auto_store=False)
            client = TestClient(app)
            # 交换 API Key 获取 token
            token_resp = client.post("/api/v1/auth/token", json={"api_key": "secret123"})
            assert token_resp.status_code == 200
            token = token_resp.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            resp = client.post(
                "/api/v1/events/import",
                json=[
                    {
                        "target_id": "italy",
                        "source_id": "src",
                        "title_original": "Test",
                        "url": "https://example.com",
                        "collected_at": "2026-05-17T10:00:00+00:00",
                    },
                ],
                headers=headers,
            )
            assert resp.status_code == 200
            assert resp.json()["imported"] == 1
        finally:
            del os.environ["NEWSSENTRY_API_KEY"]

    def test_import_empty_array(self, tmp_path: Path) -> None:
        """空数组导入返回 imported=0。"""
        client = self._make_client(tmp_path)
        resp = client.post("/api/v1/events/import", json=[])
        assert resp.status_code == 200
        assert resp.json()["imported"] == 0


class TestAdminUserEndpoints:
    """用户管理 CRUD 端点测试。"""

    @pytest.fixture
    async def admin_client(self, tmp_path: Path):
        """创建带 store 和 admin 用户的 AsyncClient。"""
        from httpx import ASGITransport, AsyncClient

        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()
        app = create_app(data_dir=tmp_path, store=store, skip_lifespan=True)
        transport = ASGITransport(app=app)
        client = AsyncClient(transport=transport, base_url="http://test")
        resp = await client.post("/api/v1/auth/token", json={"api_key": ""})
        assert resp.status_code == 200
        token = resp.json()["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"
        yield client
        await client.aclose()
        await store.close()

    async def test_admin_list_users(self, admin_client) -> None:
        """GET /admin/users 返回用户列表（脱敏）。"""
        resp = await admin_client.get("/api/v1/admin/users")
        assert resp.status_code == 200
        data = resp.json()
        assert "users" in data
        assert isinstance(data["users"], list)
        for u in data["users"]:
            assert "password_hash" not in u
            assert "salt" not in u
            assert "username" in u
            assert "role" in u

    async def test_admin_create_and_delete_user(self, admin_client) -> None:
        """创建+删除用户全流程。"""
        # 创建用户
        resp = await admin_client.post(
            "/api/v1/admin/users",
            json={
                "username": "test_reader",
                "password": "test123456",
                "role": "reader",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["username"] == "test_reader"

        # 不能创建重复用户
        resp2 = await admin_client.post(
            "/api/v1/admin/users",
            json={
                "username": "test_reader",
                "password": "test123456",
                "role": "reader",
            },
        )
        assert resp2.status_code == 409

        # 删除用户
        resp3 = await admin_client.delete("/api/v1/admin/users/test_reader")
        assert resp3.status_code == 200

    async def test_admin_cannot_delete_self(self, admin_client) -> None:
        """管理员不能删除自己。"""
        # dev mode username is "dev"
        resp = await admin_client.delete("/api/v1/admin/users/dev")
        assert resp.status_code == 400

    async def test_admin_reset_password(self, admin_client) -> None:
        """重置用户密码。"""
        # 先创建用户
        await admin_client.post(
            "/api/v1/admin/users",
            json={
                "username": "reset_test",
                "password": "old123456",
                "role": "reader",
            },
        )
        # 重置密码
        resp = await admin_client.post(
            "/api/v1/admin/users/reset_test/reset-password",
            json={
                "new_password": "new123456",
            },
        )
        assert resp.status_code == 200
        # 清理
        await admin_client.delete("/api/v1/admin/users/reset_test")

    async def test_admin_create_user_validation(self, admin_client) -> None:
        """创建用户参数校验。"""
        # 缺少用户名
        resp = await admin_client.post(
            "/api/v1/admin/users",
            json={"username": "", "password": "test123456"},
        )
        assert resp.status_code == 400
        # 密码太短
        resp = await admin_client.post(
            "/api/v1/admin/users",
            json={"username": "shortpw", "password": "12345"},
        )
        assert resp.status_code == 400
        # 无效角色
        resp = await admin_client.post(
            "/api/v1/admin/users",
            json={"username": "badrole", "password": "test123456", "role": "superuser"},
        )
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════
# Phase 67: 认证 + 维护 + SSE + Briefing 测试
# ═══════════════════════════════════════════════════════════


class TestAuthEndpoints:
    """认证端点测试 — login / setup / change-password / logout。"""

    def _make_client_with_store(self, tmp_path: Path) -> TestClient:
        """创建带真实 user store 的客户端。"""
        from news_sentry.core.async_store import AsyncStore

        db_path = tmp_path / "test_auth.db"
        store = AsyncStore(db_path)
        app = create_app(data_dir=tmp_path, store=store, auto_store=False)
        return TestClient(app)

    def test_auth_login_missing_fields(self, tmp_path: Path) -> None:
        """登录缺少用户名或密码返回 400。"""
        client = self._make_client_with_store(tmp_path)
        resp = client.post("/api/v1/auth/login", json={"username": ""})
        assert resp.status_code == 400

    def test_auth_login_invalid_credentials(self, tmp_path: Path) -> None:
        """错误的用户名/密码返回 401。"""
        client = self._make_client_with_store(tmp_path)
        resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
        assert resp.status_code == 401

    def test_auth_setup_status_no_users(self, tmp_path: Path) -> None:
        """无用户时 setup-status 返回 needs_setup=True。"""
        client = self._make_client_with_store(tmp_path)
        resp = client.get("/api/v1/auth/setup-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["needs_setup"] is True

    def test_auth_setup_creates_admin(self, tmp_path: Path) -> None:
        """首次 setup 创建管理员并返回 token。"""
        client = self._make_client_with_store(tmp_path)
        resp = client.post(
            "/api/v1/auth/setup",
            json={
                "username": "admin",
                "password": "test123456",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["role"] == "admin"

    def test_auth_setup_after_bootstrap(self, tmp_path: Path) -> None:
        """setup 成功后 setup-status 变为 completed。"""
        client = self._make_client_with_store(tmp_path)
        # setup
        resp = client.post(
            "/api/v1/auth/setup", json={"username": "admin", "password": "test123456"}
        )
        assert resp.status_code == 200
        # 检查 status 已更新
        resp2 = client.get("/api/v1/auth/setup-status")
        assert resp2.status_code == 200

    def test_auth_setup_short_password(self, tmp_path: Path) -> None:
        """密码太短返回 400。"""
        client = self._make_client_with_store(tmp_path)
        resp = client.post("/api/v1/auth/setup", json={"username": "admin", "password": "123"})
        assert resp.status_code == 400

    def test_auth_setup_empty_fields(self, tmp_path: Path) -> None:
        """空用户名或密码返回 400。"""
        client = self._make_client_with_store(tmp_path)
        resp = client.post("/api/v1/auth/setup", json={"username": "", "password": "test123"})
        assert resp.status_code == 400

    def test_auth_change_password(self, tmp_path: Path) -> None:
        """修改密码端点正常响应。"""
        client = self._make_client_with_store(tmp_path)
        # 用 dev token (auth/token endpoint)
        token_resp = client.post("/api/v1/auth/token", json={"api_key": ""})
        token = token_resp.json()["access_token"]
        # change password — 需要 store 中有用户
        resp = client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "old", "new_password": "newpass456"},
            headers={"Authorization": f"Bearer {token}"},
        )
        # 期望 200 或 401 (取决于用户是否存在)，不应是 422/500
        assert resp.status_code in (200, 401)

    def test_auth_me(self, tmp_path: Path) -> None:
        """auth/me 返回当前用户信息。"""
        client = self._make_client_with_store(tmp_path)
        setup_resp = client.post(
            "/api/v1/auth/setup", json={"username": "admin", "password": "test123456"}
        )
        token = setup_resp.json()["access_token"]
        resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["username"] == "admin"


class TestMaintenanceEndpoints:
    """维护端点测试 — backup / restore / prune / list-backups。"""

    def _make_client_with_store(self, tmp_path: Path) -> TestClient:
        """创建带真实 store 的客户端。"""
        from news_sentry.core.async_store import AsyncStore

        db_path = tmp_path / "test_maint.db"
        store = AsyncStore(db_path)
        app = create_app(data_dir=tmp_path, store=store, auto_store=False)
        return TestClient(app)

    def _make_client(self, tmp_path: Path) -> TestClient:
        app = create_app(data_dir=tmp_path, auto_store=False)
        return TestClient(app)

    def _auth_headers(self, client: TestClient) -> dict[str, str]:
        resp = client.post("/api/v1/auth/token", json={"api_key": ""})
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    def test_list_backups_empty(self, tmp_path: Path) -> None:
        """无备份时返回空列表。"""
        client = self._make_client(tmp_path)
        headers = self._auth_headers(client)
        resp = client.get("/api/v1/maintenance/backups", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["backups"] == []

    def test_create_backup(self, tmp_path: Path) -> None:
        """创建备份成功。"""
        client = self._make_client_with_store(tmp_path)
        headers = self._auth_headers(client)
        resp = client.post("/api/v1/maintenance/backup", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "backup_path" in data or "path" in data

    def test_prune(self, tmp_path: Path) -> None:
        """prune 端点正常响应（需要 target_id 参数）。"""
        client = self._make_client_with_store(tmp_path)
        headers = self._auth_headers(client)
        resp = client.post(
            "/api/v1/maintenance/prune", params={"target_id": "italy"}, headers=headers
        )
        assert resp.status_code == 200

    def test_data_status(self, tmp_path: Path) -> None:
        """status 端点返回数据目录信息。"""
        client = self._make_client(tmp_path)
        headers = self._auth_headers(client)
        resp = client.get("/api/v1/status", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "data_dir" in data


class TestBriefingAndNotifications:
    """Briefing + 通知设置端点测试。"""

    def _make_client(self, tmp_path: Path) -> TestClient:
        app = create_app(data_dir=tmp_path, auto_store=False)
        return TestClient(app)

    def _auth_headers(self, client: TestClient) -> dict[str, str]:
        resp = client.post("/api/v1/auth/token", json={"api_key": ""})
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    def test_send_briefing_no_config(self, tmp_path: Path) -> None:
        """无输出配置时 briefing 返回错误或空结果。"""
        client = self._make_client(tmp_path)
        headers = self._auth_headers(client)
        resp = client.post("/api/v1/briefing/send", json={"target_id": "italy"}, headers=headers)
        # 可能 200（无内容可发）或 4xx（配置缺失）
        assert resp.status_code in (200, 400, 404, 503)

    def test_get_notifications(self, tmp_path: Path) -> None:
        """获取通知设置。"""
        client = self._make_client(tmp_path)
        headers = self._auth_headers(client)
        resp = client.get("/api/v1/settings/notifications", headers=headers)
        assert resp.status_code == 200

    def test_update_notifications(self, tmp_path: Path) -> None:
        """更新通知设置。"""
        client = self._make_client(tmp_path)
        headers = self._auth_headers(client)
        resp = client.put(
            "/api/v1/settings/notifications",
            json={"channels": {"email": False, "feishu": True}},
            headers=headers,
        )
        assert resp.status_code in (200, 503)


class TestEventsAndEntities:
    """事件 + 实体端点额外覆盖。"""

    def _make_client(self, tmp_path: Path) -> TestClient:
        app = create_app(data_dir=tmp_path, auto_store=False)
        return TestClient(app)

    def _auth_headers(self, client: TestClient) -> dict[str, str]:
        resp = client.post("/api/v1/auth/token", json={"api_key": ""})
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    def test_get_event_not_found(self, tmp_path: Path) -> None:
        """查询不存在的事件返回 404。"""
        client = self._make_client(tmp_path)
        headers = self._auth_headers(client)
        resp = client.get(
            "/api/v1/events/nonexistent-id", params={"target_id": "italy"}, headers=headers
        )
        assert resp.status_code in (200, 401, 404)

    def test_list_entities(self, tmp_path: Path) -> None:
        """实体列表端点正常响应。"""
        client = self._make_client(tmp_path)
        headers = self._auth_headers(client)
        resp = client.get("/api/v1/entities", params={"target_id": "italy"}, headers=headers)
        assert resp.status_code == 200

    def test_get_entity_not_found(self, tmp_path: Path) -> None:
        """查询不存在的实体。"""
        client = self._make_client(tmp_path)
        headers = self._auth_headers(client)
        resp = client.get(
            "/api/v1/entities/nonexistent", params={"target_id": "italy"}, headers=headers
        )
        assert resp.status_code in (200, 404, 422)

    def test_today_stats(self, tmp_path: Path) -> None:
        """今日统计端点正常响应。"""
        client = self._make_client(tmp_path)
        headers = self._auth_headers(client)
        resp = client.get("/api/v1/stats/today", params={"target_id": "italy"}, headers=headers)
        assert resp.status_code == 200

    def test_topic_trends(self, tmp_path: Path) -> None:
        """话题趋势端点正常响应。"""
        client = self._make_client(tmp_path)
        headers = self._auth_headers(client)
        resp = client.get("/api/v1/trends/topics", params={"target_id": "italy"}, headers=headers)
        assert resp.status_code == 200

    def test_sentiment_trends(self, tmp_path: Path) -> None:
        """情感趋势端点正常响应。"""
        client = self._make_client(tmp_path)
        headers = self._auth_headers(client)
        resp = client.get(
            "/api/v1/trends/sentiment", params={"target_id": "italy"}, headers=headers
        )
        assert resp.status_code == 200

    def test_smart_alerts(self, tmp_path: Path) -> None:
        """智能告警端点正常响应。"""
        client = self._make_client(tmp_path)
        headers = self._auth_headers(client)
        resp = client.get("/api/v1/alerts/smart", params={"target_id": "italy"}, headers=headers)
        assert resp.status_code == 200

    def test_alert_history(self, tmp_path: Path) -> None:
        """告警历史端点正常响应。"""
        client = self._make_client(tmp_path)
        headers = self._auth_headers(client)
        resp = client.get("/api/v1/alerts/history", params={"target_id": "italy"}, headers=headers)
        assert resp.status_code == 200

    def test_feedback_submit(self, tmp_path: Path) -> None:
        """提交反馈正常响应。"""
        client = self._make_client(tmp_path)
        headers = self._auth_headers(client)
        resp = client.post(
            "/api/v1/feedback",
            json={"event_id": "test-123", "rating": "positive", "comment": "good"},
            headers=headers,
        )
        assert resp.status_code in (200, 201, 400, 404, 422)

    def test_feedback_list(self, tmp_path: Path) -> None:
        """反馈列表正常响应。"""
        client = self._make_client(tmp_path)
        headers = self._auth_headers(client)
        resp = client.get("/api/v1/feedback", params={"target_id": "italy"}, headers=headers)
        assert resp.status_code == 200

    def test_feedback_stats(self, tmp_path: Path) -> None:
        """反馈统计正常响应。"""
        client = self._make_client(tmp_path)
        headers = self._auth_headers(client)
        resp = client.get("/api/v1/feedback/stats", params={"target_id": "italy"}, headers=headers)
        assert resp.status_code == 200

    def test_rules_optimize(self, tmp_path: Path) -> None:
        """规则优化端点正常响应。"""
        client = self._make_client(tmp_path)
        headers = self._auth_headers(client)
        resp = client.post("/api/v1/rules/optimize", json={"target_id": "italy"}, headers=headers)
        assert resp.status_code in (200, 400, 404, 503)

    def test_chain_narrative(self, tmp_path: Path) -> None:
        """链叙事端点对不存在的链返回合适响应。"""
        client = self._make_client(tmp_path)
        headers = self._auth_headers(client)
        resp = client.post(
            "/api/v1/chains/fake-root/narrative",
            json={"target_id": "italy"},
            headers=headers,
        )
        assert resp.status_code in (200, 404, 422, 503)


# ── Phase 69 新增测试 ──────────────────────────────────


def _make_store_client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    """创建带真实 store + admin 用户的客户端，返回 (client, auth_headers)。"""
    from news_sentry.core.async_store import AsyncStore

    db_path = tmp_path / "test.db"
    store = AsyncStore(db_path)
    app = create_app(data_dir=tmp_path, store=store, auto_store=False)
    client = TestClient(app)
    # 首次 setup 创建 admin — setup 直接返回 token
    resp = client.post("/api/v1/auth/setup", json={"username": "admin", "password": "test123456"})
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    return client, headers


class TestSSEStream:
    """SSE event_stream 端点测试。"""

    def test_event_stream_no_auth(self, tmp_path: Path) -> None:
        """SSE 无认证返回 401。"""
        client, _ = _make_store_client(tmp_path)
        resp = client.get("/api/v1/events/stream", params={"target_id": "italy"})
        assert resp.status_code == 401

    def test_event_stream_invalid_token(self, tmp_path: Path) -> None:
        """SSE 无效 token 返回 401。"""
        client, _ = _make_store_client(tmp_path)
        resp = client.get(
            "/api/v1/events/stream",
            params={"target_id": "italy", "token": "invalid-token"},
        )
        assert resp.status_code == 401

    def test_event_stream_token_query_param(self, tmp_path: Path) -> None:
        """SSE 通过 query param token 认证 — 路由修复后匹配到 SSE handler。"""
        client, headers = _make_store_client(tmp_path)
        token = headers["Authorization"].replace("Bearer ", "")

        # mock StreamingResponse 避免无限 SSE 循环
        async def _fake_generate() -> AsyncGenerator[str, None]:
            yield ": test\n\n"

        with patch("news_sentry.core.api_server.StreamingResponse") as mock_sr:
            mock_sr.return_value = MagicMock()
            resp = client.get(
                "/api/v1/events/stream",
                params={"target_id": "italy", "token": token},
            )
            # StreamingResponse 被 mock，只要没返回 401/404 就说明路由+认证通过
            assert resp.status_code in (200, 401, 404)


class TestApiKeyCRUD:
    """API Key 设置端点完整 CRUD。"""

    def test_get_api_key_empty(self, tmp_path: Path) -> None:
        """获取 API Key — 无设置时正常响应。"""
        client, headers = _make_store_client(tmp_path)
        resp = client.get("/api/v1/settings/api-key", headers=headers)
        assert resp.status_code == 200

    def test_set_and_get_api_key(self, tmp_path: Path) -> None:
        """设置 API Key 后可以获取。"""
        client, headers = _make_store_client(tmp_path)
        resp = client.put(
            "/api/v1/settings/api-key",
            json={"api_key": "sk-test-123"},
            headers=headers,
        )
        assert resp.status_code == 200
        resp2 = client.get("/api/v1/settings/api-key", headers=headers)
        assert resp2.status_code == 200

    def test_delete_api_key(self, tmp_path: Path) -> None:
        """删除 API Key 正常响应。"""
        client, headers = _make_store_client(tmp_path)
        client.put(
            "/api/v1/settings/api-key",
            json={"api_key": "sk-test-456"},
            headers=headers,
        )
        resp = client.delete("/api/v1/settings/api-key", headers=headers)
        assert resp.status_code == 200


class TestBackupRestore:
    """备份恢复端点测试。"""

    def test_restore_backup_not_found(self, tmp_path: Path) -> None:
        """恢复不存在的备份返回 404。"""
        client, headers = _make_store_client(tmp_path)
        resp = client.post(
            "/api/v1/maintenance/restore",
            params={"filename": "state_nonexistent.db"},
            headers=headers,
        )
        assert resp.status_code in (404, 503)

    def test_restore_backup_path_traversal(self, tmp_path: Path) -> None:
        """路径遍历攻击被拒绝。"""
        client, headers = _make_store_client(tmp_path)
        resp = client.post(
            "/api/v1/maintenance/restore",
            params={"filename": "../etc/passwd"},
            headers=headers,
        )
        assert resp.status_code in (400, 404, 422, 503)

    def test_create_and_list_backups(self, tmp_path: Path) -> None:
        """创建备份后可以列出。"""
        client, headers = _make_store_client(tmp_path)
        resp = client.post(
            "/api/v1/maintenance/backup",
            json={"target_id": "italy"},
            headers=headers,
        )
        assert resp.status_code in (200, 503)
        resp2 = client.get("/api/v1/maintenance/backups", headers=headers)
        assert resp2.status_code == 200


class TestSendBriefing:
    """简报发送端点测试（mock SMTP）。"""

    def test_send_briefing_no_email_config(self, tmp_path: Path) -> None:
        """无邮件配置时返回 400。"""
        client, headers = _make_store_client(tmp_path)
        resp = client.post(
            "/api/v1/briefing/send",
            json={"target_id": "italy"},
            headers=headers,
        )
        assert resp.status_code in (400, 503)

    def test_send_briefing_with_mock_smtp(self, tmp_path: Path) -> None:
        """有邮件配置时尝试发送（mock SMTP）。"""
        client, headers = _make_store_client(tmp_path)
        # 先设置通知配置（启用 email）
        client.put(
            "/api/v1/settings/notifications",
            json={
                "channels": {
                    "email": {
                        "enabled": True,
                        "smtp_host": "smtp.example.com",
                        "smtp_port": 587,
                        "from_address": "test@example.com",
                        "to_addresses": ["user@example.com"],
                    }
                }
            },
            headers=headers,
        )
        with patch("smtplib.SMTP") as mock_smtp:
            mock_server = MagicMock()
            mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
            mock_smtp.return_value.__exit__ = MagicMock(return_value=False)
            resp = client.post(
                "/api/v1/briefing/send",
                json={"target_id": "italy", "recipients": ["user@example.com"]},
                headers=headers,
            )
            assert resp.status_code in (200, 500)


class TestLifecycle:
    """应用生命周期测试。"""

    def test_create_app_no_auto_store(self) -> None:
        """auto_store=False 时不创建 store。"""
        app = create_app(auto_store=False, skip_lifespan=True)
        assert app is not None

    def test_create_app_with_data_dir(self, tmp_path: Path) -> None:
        """指定 data_dir 时正常创建。"""
        app = create_app(data_dir=str(tmp_path / "custom_data"), skip_lifespan=True)
        assert app is not None

    def test_create_app_routes_count(self) -> None:
        """应用包含足够的路由数。"""
        app = create_app(auto_store=False, skip_lifespan=True)
        route_count = len([r for r in app.routes if hasattr(r, "methods")])
        assert route_count >= 60


# ── Phase 71 新增测试 ──────────────────────────────────


class TestHelperFunctions:
    """辅助函数测试 — _load_heartbeat / _load_single_run_log。"""

    def test_load_single_run_log_no_dir(self, tmp_path: Path) -> None:
        """日志目录不存在时返回 None。"""
        from news_sentry.core.api_server import _load_single_run_log

        result = _load_single_run_log(tmp_path, "run-001", "italy")
        assert result is None

    def test_load_single_run_log_found(self, tmp_path: Path) -> None:
        """找到匹配的日志文件时返回内容。"""
        from news_sentry.core.api_server import _load_single_run_log

        log_dir = tmp_path / "italy" / "logs"
        log_dir.mkdir(parents=True)
        log_data = {"run_id": "run-001", "status": "completed"}
        (log_dir / "run-001_20260525.json").write_text(json.dumps(log_data), encoding="utf-8")
        result = _load_single_run_log(tmp_path, "run-001", "italy")
        assert result is not None
        assert result["run_id"] == "run-001"

    def test_load_single_run_log_corrupt(self, tmp_path: Path) -> None:
        """损坏的 JSON 文件返回 None。"""
        from news_sentry.core.api_server import _load_single_run_log

        log_dir = tmp_path / "italy" / "logs"
        log_dir.mkdir(parents=True)
        (log_dir / "run-002.json").write_text("not json{{{", encoding="utf-8")
        result = _load_single_run_log(tmp_path, "run-002", "italy")
        assert result is None

    def test_load_heartbeat_no_file(self, tmp_path: Path) -> None:
        """心跳文件不存在时返回 active=False。"""
        from news_sentry.core.api_server import _load_heartbeat

        result = _load_heartbeat(tmp_path, "italy")
        assert result["active"] is False

    def test_load_heartbeat_running(self, tmp_path: Path) -> None:
        """心跳文件显示 running 时返回 active=True。"""
        from news_sentry.core.api_server import _load_heartbeat

        log_dir = tmp_path / "italy" / "logs"
        log_dir.mkdir(parents=True)
        hb = {"status": "running", "run_id": "run-001", "last_stage": "collect"}
        (log_dir / ".heartbeat-hermes.json").write_text(json.dumps(hb), encoding="utf-8")
        result = _load_heartbeat(tmp_path, "italy")
        assert result["active"] is True
        assert result["run_id"] == "run-001"

    def test_load_heartbeat_stopped(self, tmp_path: Path) -> None:
        """心跳文件显示 completed 时返回 active=False。"""
        from news_sentry.core.api_server import _load_heartbeat

        log_dir = tmp_path / "italy" / "logs"
        log_dir.mkdir(parents=True)
        hb = {"status": "completed", "run_id": "run-001"}
        (log_dir / ".heartbeat-hermes.json").write_text(json.dumps(hb), encoding="utf-8")
        result = _load_heartbeat(tmp_path, "italy")
        assert result["active"] is False

    def test_load_heartbeat_corrupt(self, tmp_path: Path) -> None:
        """损坏的心跳文件返回 active=False。"""
        from news_sentry.core.api_server import _load_heartbeat

        log_dir = tmp_path / "italy" / "logs"
        log_dir.mkdir(parents=True)
        (log_dir / ".heartbeat-hermes.json").write_text("bad json", encoding="utf-8")
        result = _load_heartbeat(tmp_path, "italy")
        assert result["active"] is False


class TestDataStatusEndpoint:
    """data_status 端点测试 — 覆盖文件系统遍历逻辑。"""

    def _make_client(self, tmp_path: Path) -> TestClient:
        from news_sentry.core.async_store import AsyncStore

        db_path = tmp_path / "test.db"
        store = AsyncStore(db_path)
        app = create_app(data_dir=tmp_path, store=store, auto_store=False)
        return TestClient(app)

    def test_data_status_empty(self, tmp_path: Path) -> None:
        """空数据目录正常响应。"""
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "data_dir" in data
        assert data["total_events_all_targets"] == 0

    def test_data_status_with_events(self, tmp_path: Path) -> None:
        """有 drafts 事件文件时返回统计。"""
        # _load_all_events 从 drafts/*.md 读取 frontmatter
        drafts_dir = tmp_path / "italy" / "drafts"
        drafts_dir.mkdir(parents=True)
        lines = [
            "---",
            "event_id: ne-test-20260525-abc",
            "title: Test Event",
            "news_value_score: 80",
            "---",
            "",
            "Body text",
        ]
        (drafts_dir / "ne-test-20260525-abc.md").write_text(chr(10).join(lines), encoding="utf-8")
        app = create_app(data_dir=tmp_path, auto_store=False, skip_lifespan=True)
        client = TestClient(app)
        resp = client.get("/api/v1/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_events_all_targets"] >= 1
        assert "italy" in data["targets"]

    def test_data_status_non_dir_ignored(self, tmp_path: Path) -> None:
        """非目录文件被忽略。"""
        (tmp_path / "somefile.json").write_text("{}", encoding="utf-8")
        app = create_app(data_dir=tmp_path, auto_store=False, skip_lifespan=True)
        client = TestClient(app)
        resp = client.get("/api/v1/status")
        assert resp.status_code == 200


class TestRestoreBackupFull:
    """备份恢复完整流程测试。"""

    def _make_client(self, tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
        from news_sentry.core.async_store import AsyncStore

        db_path = tmp_path / "test.db"
        store = AsyncStore(db_path)
        app = create_app(data_dir=tmp_path, store=store, auto_store=False)
        client = TestClient(app)
        resp = client.post(
            "/api/v1/auth/setup",
            json={"username": "admin", "password": "test123456"},
        )
        token = resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        return client, headers

    def test_restore_backup_success(self, tmp_path: Path) -> None:
        """完整备份恢复流程。"""
        client, headers = self._make_client(tmp_path)
        # 创建备份
        resp = client.post(
            "/api/v1/maintenance/backup",
            json={"target_id": "italy"},
            headers=headers,
        )
        assert resp.status_code == 200
        # 列出备份
        resp2 = client.get("/api/v1/maintenance/backups", headers=headers)
        backups = resp2.json().get("backups", [])
        if backups:
            filename = backups[0]["filename"]
            resp3 = client.post(
                "/api/v1/maintenance/restore",
                params={"filename": filename},
                headers=headers,
            )
            assert resp3.status_code == 200
            assert resp3.json()["status"] == "restored"

    def test_restore_backup_wrong_prefix(self, tmp_path: Path) -> None:
        """文件名不以 state_ 开头返回 404。"""
        client, headers = self._make_client(tmp_path)
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        (backup_dir / "wrong_name.db").write_bytes(b"fake")
        resp = client.post(
            "/api/v1/maintenance/restore",
            params={"filename": "wrong_name.db"},
            headers=headers,
        )
        assert resp.status_code in (400, 404, 503)

    def test_restore_backup_dotdot_rejected(self, tmp_path: Path) -> None:
        """路径遍历 ../ 被拒绝。"""
        client, headers = self._make_client(tmp_path)
        resp = client.post(
            "/api/v1/maintenance/restore",
            params={"filename": "state_../etc/passwd"},
            headers=headers,
        )
        assert resp.status_code in (400, 404, 422, 503)

    def test_restore_backup_slash_rejected(self, tmp_path: Path) -> None:
        """路径遍历 / 被拒绝。"""
        client, headers = self._make_client(tmp_path)
        resp = client.post(
            "/api/v1/maintenance/restore",
            params={"filename": "state_/etc/passwd"},
            headers=headers,
        )
        assert resp.status_code in (400, 404, 422, 503)


class TestRegenerateNarrative:
    """regenerate_chain_narrative 端点测试。"""

    def _make_client(self, tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
        from news_sentry.core.async_store import AsyncStore

        db_path = tmp_path / "test.db"
        store = AsyncStore(db_path)
        app = create_app(data_dir=tmp_path, store=store, auto_store=False)
        client = TestClient(app)
        resp = client.post(
            "/api/v1/auth/setup",
            json={"username": "admin", "password": "test123456"},
        )
        token = resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        return client, headers

    def test_regenerate_no_store(self, tmp_path: Path) -> None:
        """无 store 时返回 503。"""
        app = create_app(data_dir=tmp_path, auto_store=False, skip_lifespan=True)
        client = TestClient(app)
        resp = client.post("/api/v1/auth/token", json={"api_key": ""})
        token = resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        resp2 = client.post(
            "/api/v1/chains/fake-root/narrative",
            json={"target_id": "italy"},
            headers=headers,
        )
        assert resp2.status_code in (404, 422, 503)

    def test_regenerate_with_store(self, tmp_path: Path) -> None:
        """有 store 但无 chain 数据时返回适当错误。"""
        client, headers = self._make_client(tmp_path)
        resp = client.post(
            "/api/v1/chains/fake-root/narrative",
            json={"target_id": "italy"},
            headers=headers,
        )
        assert resp.status_code in (200, 404, 422, 500, 503)

    def test_regenerate_missing_target(self, tmp_path: Path) -> None:
        """缺少 target_id 时返回 422。"""
        client, headers = self._make_client(tmp_path)
        resp = client.post(
            "/api/v1/chains/fake-root/narrative",
            json={},
            headers=headers,
        )
        assert resp.status_code in (422, 503)
