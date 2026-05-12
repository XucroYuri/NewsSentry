"""Tests for API Server — Phase 22 API Gateway."""

from __future__ import annotations

import os
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


def _write_draft(data_dir: Path, target_id: str, event_id: str, title: str = "Test") -> Path:
    """辅助：写入一个 draft 事件文件。"""
    drafts = data_dir / target_id / "drafts"
    drafts.mkdir(parents=True, exist_ok=True)
    data = {
        "id": event_id,
        "source_id": "test-src",
        "url": "https://example.com",
        "title_original": title,
        "pipeline_stage": "outputted",
    }
    fm = yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False)
    # 使用 event_id 全部作为文件名保证唯一性
    filepath = drafts / f"2026-05-12-test-src-{event_id}.md"
    filepath.write_text(f"---\n{fm}---\n\n# {title}\n\nBody\n", encoding="utf-8")
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
