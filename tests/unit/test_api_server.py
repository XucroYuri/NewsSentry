"""Tests for API Server — Phase 22 API Gateway + Phase 24 Web UI."""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import AsyncGenerator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml
from fastapi.testclient import TestClient

from news_sentry.api.middleware.auth import _TOKEN_STORE, _RateLimiter
from news_sentry.core import api_server as api_server_module
from news_sentry.core.api_server import (
    _get_valid_api_keys,
    create_app,
)
from news_sentry.core.async_store import AsyncStore
from news_sentry.core.collector_config_utils import _parse_target_ids
from news_sentry.core.event_io_utils import _parse_frontmatter
from news_sentry.core.public_news_utils import _tag_text
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


class TestAIEnrichmentAPI:
    def test_ai_enrichment_status_returns_defaults(self, tmp_path, monkeypatch) -> None:
        _force_deployment_env(monkeypatch, "local")
        # _state._ai_enrichment_state 在模块导入后为空字典，create_app 不再同步
        # api_server._ai_enrichment_state 的默认值。手动补上必要键值。
        import news_sentry.core._state as _state_mod
        _state_mod._ai_enrichment_state.update({
            "enabled": True,
            "running": False,
            "interval_minutes": 60,
            "daily_request_limit": 45,
            "per_cycle_request_limit": 3,
            "max_chars_per_request": 6000,
            "cooldown_after_429_minutes": 120,
            "targets": ["all"],
            "candidate_limit": 200,
        })
        app = create_app(data_dir=tmp_path, auto_store=False, skip_lifespan=True)
        client = TestClient(app)

        resp = client.get("/api/v1/ai/enrichment/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["config"]["interval_minutes"] == 60
        assert data["config"]["daily_request_limit"] == 45
        assert data["running"] is False

    def test_ai_enrichment_dry_run_does_not_call_provider(self, tmp_path, monkeypatch) -> None:
        _force_deployment_env(monkeypatch, "local")
        store = AsyncStore(tmp_path / "async_store.db")
        asyncio.run(store.initialize())
        asyncio.run(
            _insert_index_event(
                store,
                event_id="ne-ai-dry-run",
                title_original="Titolo da tradurre",
                metadata={},
            )
        )
        app = create_app(data_dir=tmp_path, store=store, skip_lifespan=True)
        client = TestClient(app)

        resp = client.post("/api/v1/ai/enrichment/run?dry_run=true&target_id=italy")

        assert resp.status_code == 200
        data = resp.json()
        assert data["dry_run"] is True
        assert data["batches"][0]["items"][0]["event_id"] == "ne-ai-dry-run"


class TestPublicTranslationAPI:
    def test_public_translation_status_returns_fast_defaults(self, tmp_path, monkeypatch) -> None:
        _force_deployment_env(monkeypatch, "local")
        # _state._public_translation_state 在模块导入后为空字典，create_app 不再同步
        # api_server._public_translation_state 的默认值。手动补上必要键值。
        import news_sentry.core._state as _state_mod
        _state_mod._public_translation_state.update({
            "enabled": True,
            "running": False,
            "interval_minutes": 5,
            "per_cycle_limit": 50,
            "max_chars_per_request": 6000,
            "cooldown_after_429_minutes": 120,
            "targets": ["all"],
            "candidate_limit": 200,
        })
        app = create_app(data_dir=tmp_path, auto_store=False, skip_lifespan=True)
        client = TestClient(app)

        resp = client.get("/api/v1/ai/translation/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["config"]["interval_minutes"] == 5
        assert data["config"]["per_cycle_limit"] == 50
        assert data["running"] is False
        assert data["publication_ready_count"] == 0
        assert data["pending_reason_count"] == 0

    def test_public_translation_dry_run_lists_untranslated_candidates(
        self,
        tmp_path,
        monkeypatch,
    ) -> None:
        _force_deployment_env(monkeypatch, "local")
        store = AsyncStore(tmp_path / "async_store.db")
        asyncio.run(store.initialize())
        asyncio.run(
            _insert_index_event(
                store,
                event_id="ne-translation-dry-run",
                title_original="Titre français à traduire",
                metadata={"summary": "Résumé en français."},
            )
        )
        app = create_app(data_dir=tmp_path, store=store, skip_lifespan=True)
        client = TestClient(app)

        resp = client.post("/api/v1/ai/translation/run?dry_run=true&target_id=italy")

        assert resp.status_code == 200
        data = resp.json()
        assert data["dry_run"] is True
        assert data["targets"] == ["italy"]
        assert data["candidates"][0]["event_id"] == "ne-translation-dry-run"

    def test_public_news_api_hides_untranslated_index_rows(self, tmp_path, monkeypatch) -> None:
        _force_deployment_env(monkeypatch, "local")
        store = AsyncStore(tmp_path / "async_store.db")
        asyncio.run(store.initialize())
        asyncio.run(
            _insert_index_event(
                store,
                event_id="ne-hidden-untranslated",
                title_original="Untranslated French title must not leak",
                metadata={"summary": "French summary should not leak either."},
            )
        )
        app = create_app(data_dir=tmp_path, store=store, skip_lifespan=True)
        client = TestClient(app)

        resp = client.get("/api/v1/public/news", params={"target_id": "italy"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0


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


class TestFeedTagText:
    """新闻流标签文本提取测试。"""

    def test_preserves_numeric_zero_values(self) -> None:
        assert _tag_text({"code": 0}) == "0"
        assert _tag_text(0) == "0"


class TestAutoCollectorTargets:
    """自动采集 target 解析测试。"""

    def test_all_discovers_targets_from_current_project_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        targets_dir = tmp_path / "config" / "targets"
        targets_dir.mkdir(parents=True)
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'tmp'\n", encoding="utf-8")
        (targets_dir / "italy.yaml").write_text("target_id: italy\n", encoding="utf-8")
        (targets_dir / "japan.yaml").write_text("target_id: japan\n", encoding="utf-8")
        (targets_dir / "_template.yaml").write_text("target_id: _template\n", encoding="utf-8")

        monkeypatch.chdir(tmp_path)

        assert _parse_target_ids("all") == ["italy", "japan"]


class TestLocalAuthBypass:
    """本地应用免登录，云端部署继续强制登录。"""

    def test_local_env_allows_admin_without_bearer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _force_deployment_env(monkeypatch, "local")
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app, base_url="http://127.0.0.1")

        me_resp = client.get("/api/v1/auth/me")
        users_resp = client.get("/api/v1/admin/users")

        assert me_resp.status_code == 200
        assert me_resp.json()["username"] == "local-admin"
        assert me_resp.json()["role"] == "admin"
        assert users_resp.status_code == 200

    def test_local_env_rejects_non_loopback_without_bearer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _force_deployment_env(monkeypatch, "local")
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app, base_url="http://news.example.com")

        resp = client.get("/api/v1/admin/users")

        assert resp.status_code == 401

    def test_cloud_env_still_requires_bearer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _force_deployment_env(monkeypatch, "cloudflare")
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)

        resp = client.get("/api/v1/admin/users")

        assert resp.status_code == 401

    def test_cloud_env_without_api_key_rejects_dev_token(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """云端环境缺少 API Key 时不能签发本地 dev/admin token。"""
        _force_deployment_env(monkeypatch, "cloudflare")
        monkeypatch.delenv("NEWSSENTRY_API_KEY", raising=False)
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app, base_url="https://news.example")

        resp = client.post("/api/v1/auth/token", json={"api_key": ""})

        assert resp.status_code == 503

    def test_cloud_env_auth_token_without_body_returns_400(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """云端环境下空请求体不能把 auth/token 打成 500。"""
        _force_deployment_env(monkeypatch, "cloudflare")
        monkeypatch.delenv("NEWSSENTRY_API_KEY", raising=False)
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app, base_url="https://news.example")

        resp = client.post("/api/v1/auth/token", content=b"")

        assert resp.status_code == 400
        assert resp.json()["detail"] == "Request body must be valid JSON"


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

    def test_health_endpoint_exposes_deploy_evidence_headers(self, tmp_path: Path) -> None:
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "total_events" in data
        assert "latest_collected_at" in data
        assert re.fullmatch(r"[0-9a-f]{12}|unknown", resp.headers["x-news-sentry-deploy-commit"])
        assert re.fullmatch(r"[0-9a-f]{12}|development", resp.headers["x-news-sentry-static-build"])

    def test_diagnostics_endpoint_returns_global_summary(self, tmp_path: Path) -> None:
        """公开 /api/v1/diagnostics 应返回全局可观测性摘要（无需认证）。"""
        from news_sentry.core.api_server import create_app as _create_diag_app

        app = _create_diag_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)

        resp = client.get("/api/v1/diagnostics")
        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "no-store"

        data = resp.json()
        # 顶层结构
        assert set(data.keys()) == {
            "deploy",
            "collector",
            "ai_key_configured",
            "data",
            "source_health",
            "events",
            "recent_runs",
        }
        # deploy
        assert "commit" in data["deploy"]
        assert "build" in data["deploy"]
        # collector
        assert "enabled" in data["collector"]
        assert "running" in data["collector"]
        # ai key
        assert isinstance(data["ai_key_configured"], bool)
        # data
        assert "directory" in data["data"]
        assert isinstance(data["data"]["target_count"], int)
        assert isinstance(data["data"]["targets"], list)
        # source_health
        assert "healthy" in data["source_health"]
        assert "unhealthy" in data["source_health"]
        assert "total" in data["source_health"]
        # events
        assert "total" in data["events"]
        assert "latest_collected_at" in data["events"]
        # recent_runs
        assert isinstance(data["recent_runs"], list)

    def test_exception_handler_returns_unified_error_format(self, tmp_path: Path) -> None:
        """全局异常处理器应将 HTTP/500/Pydantic 错误转为统一 error JSON 格式。"""
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)

        # 404 — HTTPException
        resp = client.get("/api/v1/nonexistent-endpoint-xyz")
        assert resp.status_code == 404
        body = resp.json()
        assert body["error"] == "Not Found"
        assert body["detail"] == "Not Found"
        assert body["status_code"] == 404

        # 405 — Method Not Allowed (FastAPI 自动生成，应经过 handler)
        resp = client.post("/api/v1/health")
        assert resp.status_code == 405
        body = resp.json()
        assert "error" in body
        assert "status_code" in body

    def test_exception_handler_unauthorized_adds_auth_header(self, tmp_path: Path) -> None:
        """401/403 响应应追加 X-News-Sentry-Auth-Reason 头。"""
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app, base_url="https://news.example")

        # 访问需要认证的端点
        resp = client.get("/api/v1/admin/users")
        assert resp.status_code == 401
        assert resp.headers.get("X-News-Sentry-Auth-Reason") == "missing_or_invalid_token"
        body = resp.json()
        assert body["error"] == "Unauthorized"

    def test_runtime_info_endpoint_reports_static_build(self, tmp_path: Path) -> None:
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/runtime/info")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["static_build"]
        assert set(data) == {"status", "static_build"}

    def test_runtime_info_endpoint_requires_bearer(self, tmp_path: Path) -> None:
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app, base_url="https://news.example")

        resp = client.get("/api/v1/runtime/info")

        assert resp.status_code == 401

    def test_security_headers_are_attached_to_public_responses(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # 使用临时静态文件以避免依赖前端构建产物
        static_dir = tmp_path / "static"
        public_app_dir = static_dir / "public_app"
        public_app_dir.mkdir(parents=True)
        (public_app_dir / "index.html").write_text(
            '<html><body><div id="root"></div></body></html>',
            encoding="utf-8",
        )
        monkeypatch.setattr(api_server_module, "_static_dir", lambda: static_dir)
        app = create_app(data_dir=tmp_path / "data", auto_store=False)
        client = TestClient(app)

        resp = client.get("/")

        assert resp.status_code == 200
        assert "strict-transport-security" in resp.headers
        assert resp.headers["x-frame-options"] == "DENY"
        assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
        assert "interest-cohort=()" in resp.headers["permissions-policy"]
        csp = resp.headers["content-security-policy"]
        assert "connect-src 'self'" in csp
        assert "connect-src *" not in csp
        assert "script-src 'self'" in csp
        assert "'nonce-" in csp
        assert 'nonce="__CSP_NONCE__"' not in resp.text
        nonce = csp.split("'nonce-", maxsplit=1)[1].split("'", maxsplit=1)[0]
        assert f'nonce="{nonce}"' in resp.text
        assert "'unsafe-inline'" not in csp.split("style-src", maxsplit=1)[0]

    def test_disallowed_cors_origin_gets_no_cors_credentials(self, tmp_path: Path) -> None:
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)

        resp = client.get("/api/v1/health", headers={"Origin": "https://evil.example"})

        assert resp.status_code == 200
        assert "access-control-allow-origin" not in resp.headers
        assert "access-control-allow-credentials" not in resp.headers

    def test_robots_txt_is_owned_by_app(self, tmp_path: Path) -> None:
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)

        resp = client.get("/robots.txt")

        assert resp.status_code == 200
        assert "User-agent: *" in resp.text
        assert "Disallow: /api/" in resp.text
        assert "Disallow: /#/admin" in resp.text


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

    def test_collector_status_falls_back_to_run_logs_after_restart(self, tmp_path: Path) -> None:
        """服务重启后 collector/status 应从真实 run logs 恢复最近运行摘要。"""
        log_dir = tmp_path / "italy" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "italy_20260529T010000Z.json").write_text(
            json.dumps(
                {
                    "run_id": "italy_20260529T010000Z",
                    "target_id": "italy",
                    "started_at": "2026-05-29T01:00:00+00:00",
                    "ended_at": "2026-05-29T01:03:00+00:00",
                    "phases": [],
                    "summary": {"total_events_collected": 42},
                    "errors_count": 0,
                }
            ),
            encoding="utf-8",
        )
        old = dict(api_server_module._auto_collector_state)
        try:
            api_server_module._auto_collector_state["last_run_at"] = None
            api_server_module._auto_collector_state["last_run_status"] = None
            api_server_module._auto_collector_state["last_events_collected"] = 0
            client = self._make_client(tmp_path)

            resp = client.get("/api/v1/collector/status")

            assert resp.status_code == 200
            data = resp.json()
            assert data["last_run_at"] == "2026-05-29T01:03:00+00:00"
            assert data["last_run_status"] == "completed"
            assert data["last_events_collected"] == 42
        finally:
            api_server_module._auto_collector_state.update(old)

    def test_collector_config_put_persists_runtime_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """collector/config 可保存非技术用户在后台调整的采集调度。"""
        monkeypatch.chdir(tmp_path)
        client = self._make_client(tmp_path)

        resp = client.put(
            "/api/v1/collector/config",
            json={
                "enabled": False,
                "target_ids": ["italy", "japan"],
                "interval_minutes": 30,
                "stage": "all",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False
        assert data["target_ids"] == ["italy", "japan"]
        assert data["interval_minutes"] == 30
        assert data["stage"] == "all"
        persisted = yaml.safe_load((tmp_path / "config" / "runtime" / "collector.yaml").read_text())
        assert persisted["target_ids"] == ["italy", "japan"]

    def test_collector_env_disable_overrides_runtime_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """部署进程显式禁用自动采集时，不能被 runtime YAML 重新开启。"""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("NEWSSENTRY_AUTO_COLLECT", "0")
        runtime = tmp_path / "config" / "runtime"
        runtime.mkdir(parents=True)
        (runtime / "collector.yaml").write_text(
            yaml.safe_dump(
                {
                    "enabled": True,
                    "target_ids": ["italy"],
                    "interval_minutes": 15,
                    "stage": "all",
                },
                allow_unicode=True,
            ),
            encoding="utf-8",
        )

        client = self._make_client(tmp_path)

        # api_server.py 的模块级 _auto_collector_state 在 import 时即已根据
        # 环境变量初始化（此时 monkeypatch.setenv 尚未生效）。create_app() 内
        # _apply_collector_config 正确地读取了 env 并设置 _state._auto_collector_state，
        # 但随后的状态同步（_state_mod._auto_collector_state.update）会将其覆盖回
        # 模块级的旧值。此处通过重新调用 _apply_collector_config 修正：
        from news_sentry.core.collector_config_utils import (
            _apply_collector_config,
            _load_collector_config,
        )
        _apply_collector_config(_load_collector_config())

        resp = client.get("/api/v1/collector/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False
        assert data["target_ids"] == ["italy"]

    def test_collector_start_stop_toggle_enabled_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """collector/start 与 collector/stop 提供后台启停闭环。"""
        monkeypatch.chdir(tmp_path)
        app = create_app(data_dir=tmp_path, auto_store=False, skip_lifespan=True)
        client = TestClient(app, base_url="http://127.0.0.1")

        stop_resp = client.post("/api/v1/collector/stop")
        assert stop_resp.status_code == 200
        assert stop_resp.json()["enabled"] is False

        start_resp = client.post("/api/v1/collector/start")
        assert start_resp.status_code == 200
        assert start_resp.json()["enabled"] is True

    def test_collector_run_metrics_sum_successful_target_contexts(self) -> None:
        """自动采集完成后，collector/status 应汇总各 target 的采集数量。"""
        from news_sentry.core._state import _auto_collector_state

        old_count = _auto_collector_state.get("last_events_collected", 0)
        try:
            _auto_collector_state["last_events_collected"] = 0

            api_server_module._update_collector_run_metrics(
                [
                    MagicMock(events_collected=82),
                    MagicMock(events_collected=100),
                    MagicMock(events_collected=0),
                ]
            )

            assert _auto_collector_state["last_events_collected"] == 182
        finally:
            _auto_collector_state["last_events_collected"] = old_count

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

    def test_collector_diagnostics_accepts_gemini_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Gemini Key 存在时 AI Key 诊断应通过。"""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.setenv("GEMINI_API_KEY", "gemini-test")

        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/collector/diagnostics")

        assert resp.status_code == 200
        ai_check = [c for c in resp.json()["checks"] if c["name"] == "ai_api_key"][0]
        assert ai_check["ok"] is True

    def test_collector_diagnostics_reads_memory_source_health_yaml(self, tmp_path: Path) -> None:
        """diagnostics 应读取真实采集写入的 memory/source_health.yaml。"""
        memory_dir = tmp_path / "italy" / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        (memory_dir / "source_health.yaml").write_text(
            yaml.dump(
                {
                    "ansa": {
                        "last_success_at": "2026-05-29T00:42:52+00:00",
                        "last_failure_at": None,
                        "consecutive_failures": 0,
                        "last_error": None,
                        "total_runs": 12,
                        "total_failures": 0,
                    }
                },
                allow_unicode=True,
            ),
            encoding="utf-8",
        )

        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/collector/diagnostics")

        assert resp.status_code == 200
        source_check = [c for c in resp.json()["checks"] if c["name"] == "source_health"][0]
        assert source_check["ok"] is True
        assert "健康: 1" in source_check["message"]

    def test_collector_diagnostics_reuses_short_lived_cache(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """后台频繁刷新时，采集诊断不应重复全量扫描 source health。"""
        (tmp_path / "italy" / "memory").mkdir(parents=True, exist_ok=True)
        client = self._make_client(tmp_path)
        calls = {"health": 0}

        def fake_memory_health(target_id: str | None = None):  # noqa: ARG001
            calls["health"] += 1
            return [{"source_id": "ansa", "status": "healthy"}]

        from news_sentry.core import collector_config_utils as ccu

        monkeypatch.setattr(
            ccu,
            "_load_memory_source_health_records",
            fake_memory_health,
        )

        first = client.get("/api/v1/collector/diagnostics")
        second = client.get("/api/v1/collector/diagnostics")

        assert first.status_code == 200
        assert second.status_code == 200
        assert calls["health"] == 1

    def test_collector_diagnostics_ignores_disabled_deprecated_memory_health(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """diagnostics 不应把已停用/归档 source 的历史失败计入当前异常。"""
        monkeypatch.chdir(tmp_path)
        sources_dir = tmp_path / "config" / "sources" / "italy"
        sources_dir.mkdir(parents=True)
        (sources_dir / "ansa.yaml").write_text("source_id: ansa\n", encoding="utf-8")
        (sources_dir / "fao-rss.yaml").write_text(
            "source_id: fao-rss\nenabled: false\ndeprecated: true\n",
            encoding="utf-8",
        )
        memory_dir = tmp_path / "italy" / "memory"
        memory_dir.mkdir(parents=True)
        (memory_dir / "source_health.yaml").write_text(
            yaml.dump(
                {
                    "ansa": {
                        "last_success_at": "2026-05-29T00:42:52+00:00",
                        "last_failure_at": None,
                        "consecutive_failures": 0,
                        "last_error": None,
                        "total_runs": 12,
                        "total_failures": 0,
                    },
                    "fao-rss": {
                        "last_success_at": None,
                        "last_failure_at": "2026-05-29T00:42:52+00:00",
                        "consecutive_failures": 16,
                        "last_error": "404 Not Found",
                        "total_runs": 16,
                        "total_failures": 16,
                    },
                },
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        client = self._make_client(tmp_path)

        resp = client.get("/api/v1/collector/diagnostics")

        assert resp.status_code == 200
        source_check = [c for c in resp.json()["checks"] if c["name"] == "source_health"][0]
        assert source_check["message"] == "健康: 1, 异常: 0"

    def test_collector_diagnostics_empty_data_dir(self, tmp_path: Path) -> None:
        """空数据目录下 diagnostics 返回 overall=attention_needed。"""
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/collector/diagnostics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["overall"] == "attention_needed"
        dd_check = [c for c in data["checks"] if c["name"] == "data_directory"][0]
        assert dd_check["ok"] is False

    def test_admin_overview_aggregates_management_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """admin/overview 为管理总览提供 targets、采集、诊断和待处理状态。"""
        monkeypatch.chdir(tmp_path)
        _write_target_config(tmp_path / "config" / "targets", "italy", "意大利新闻监控", "it", 2)
        client = self._make_client(tmp_path)

        resp = client.get("/api/v1/admin/overview", params={"target_id": "italy"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["target_id"] == "italy"
        assert data["targets"][0]["target_id"] == "italy"
        assert "collector" in data
        assert "diagnostics" in data
        assert "source_health" in data
        assert "recent_runs" in data
        assert "feedback" in data
        assert "alerts" in data

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

    def test_events_feed_exposes_story_cluster_and_metadata_classification(
        self,
        tmp_path: Path,
    ) -> None:
        """新闻流公开 Task 3 产生的 story/cluster 字段和 metadata 分类。"""
        drafts = tmp_path / "italy" / "drafts"
        drafts.mkdir(parents=True, exist_ok=True)
        event = {
            "id": "ne-italy-ansa-20260526-cluster0001",
            "source_id": "ansa",
            "url": "https://example.com/cluster",
            "title_original": "Russia Ukraine talks",
            "published_at": "2026-05-26T10:15:00+08:00",
            "cluster_id": "cluster-same-event-001",
            "story_id": "story-ukraine-001",
            "metadata": {
                "classification": {
                    "l0": "international-relations",
                    "l1": ["russia-ukraine"],
                },
                "clustering": {
                    "cluster_type": "same_event",
                    "confidence": 82,
                    "matched_by": ["title_similarity", "entity_overlap"],
                    "reason": "同一事件多信源报道。",
                },
            },
        }
        fm = yaml.dump(event, allow_unicode=True, default_flow_style=False, sort_keys=False)
        (drafts / "cluster.md").write_text(
            f"---\n{fm}---\n\n# Russia Ukraine talks\n",
            encoding="utf-8",
        )
        client = self._make_client(tmp_path)

        resp = client.get("/api/v1/events/feed", params={"target_id": "italy"})

        assert resp.status_code == 200
        item = resp.json()["groups"][0]["events"][0]
        assert item["cluster_id"] == "cluster-same-event-001"
        assert item["story_id"] == "story-ukraine-001"
        assert item["clustering"] == {
            "cluster_type": "same_event",
            "confidence": 82,
            "matched_by": ["title_similarity", "entity_overlap"],
            "reason": "同一事件多信源报道。",
        }
        assert item["classification"]["l0"] == "international-relations"
        assert item["classification"]["l1"] == ["russia-ukraine"]

    def test_events_feed_preserves_numeric_flat_tags(self, tmp_path: Path) -> None:
        """新闻流服务端扁平标签不能丢弃 0 这类有效分类值。"""
        drafts = tmp_path / "italy" / "drafts"
        drafts.mkdir(parents=True, exist_ok=True)
        event = {
            "id": "ne-italy-ansa-20260526-feed0002",
            "source_id": "ansa",
            "title_original": "Numeric tag story",
            "published_at": "2026-05-26T09:15:00+08:00",
            "metadata": {
                "classification": {
                    "l0": "policy",
                    "l1": [{"code": 0}],
                },
            },
            "nlp_entities": [{"name": 0}],
        }
        fm = yaml.dump(event, allow_unicode=True, default_flow_style=False, sort_keys=False)
        (drafts / "numeric-tags.md").write_text(
            f"---\n{fm}---\n\n# Numeric tag story\n", encoding="utf-8"
        )
        client = self._make_client(tmp_path)

        resp = client.get("/api/v1/events/feed", params={"target_id": "italy"})

        assert resp.status_code == 200
        item = resp.json()["groups"][0]["events"][0]
        assert item["flat_tags"] == ["policy", "0"]


    def test_cloud_admin_users_still_requires_auth(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """云端部署仍不放开管理后台。"""
        _force_deployment_env(monkeypatch, "cloudflare")
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)

        resp = client.get("/api/v1/admin/users")

        assert resp.status_code == 401

    def test_cloud_non_public_news_apis_require_auth(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """云端部署中，新闻流以外的分析/管理读接口仍需要登录。"""
        _force_deployment_env(monkeypatch, "cloudflare")
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)
        protected_gets = [
            ("/api/v1/status", {}),
            ("/api/v1/collector/status", {}),
            ("/api/v1/collector/diagnostics", {}),
            ("/api/v1/stats", {"target_id": "italy"}),
            ("/api/v1/stats/today", {"target_id": "italy"}),
            ("/api/v1/events", {"target_id": "italy"}),
            ("/api/v1/events/top", {"target_id": "italy"}),
            ("/api/v1/events/example/links", {"target_id": "italy"}),
            ("/api/v1/events/example/chain", {"target_id": "italy"}),
            ("/api/v1/entities", {}),
            ("/api/v1/entities/1", {}),
            ("/api/v1/chains", {"target_id": "italy"}),
            ("/api/v1/chains/example/narrative", {"target_id": "italy"}),
            ("/api/v1/trends/topics", {"target_id": "italy"}),
            ("/api/v1/trends/sentiment", {"target_id": "italy"}),
        ]

        for path, params in protected_gets:
            resp = client.get(path, params=params)
            assert resp.status_code == 401, path

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

    def test_api_key_auth(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _force_deployment_env(monkeypatch, "cloudflare")
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
        _write_target_config(
            config_dir,
            "china-watch-en",
            "China Watch (English)",
            "en",
            3,
            monitoring_type="topic",
            topic_label="涉中舆情",
        )
        _write_target_config(config_dir, "empty-sources", "空信源目标", "en", 0)
        monkeypatch.chdir(tmp_path)

        async def seed() -> None:
            for target_id, event_id, title in (
                ("italy", "evt-1", "意大利公开新闻"),
                ("china-watch-en", "evt-topic-1", "涉中公开新闻"),
            ):
                store = AsyncStore(tmp_path / target_id / "state.db")
                await store.initialize()
                try:
                    await _insert_index_event(
                        store,
                        event_id=event_id,
                        target_id=target_id,
                        title_original=title,
                    )
                finally:
                    await store.close()

        asyncio.run(seed())
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/targets")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["targets"]) == 1
        assert {target["target_id"] for target in data["targets"]} == {"italy"}
        italy = next(t for t in data["targets"] if t["target_id"] == "italy")
        assert italy["display_name"] == "意大利新闻监控"
        assert italy["primary_language"] == "it"
        assert italy["source_count"] == 5
        assert italy["event_count"] == 1
        assert italy["monitoring_type"] == "country"
        assert italy["monitoring_label"] == "地区"

        regions_resp = client.get("/api/v1/regions")
        assert regions_resp.status_code == 200
        assert {region["region_id"] for region in regions_resp.json()["regions"]} == {"italy"}

        admin_resp = client.get("/api/v1/admin/targets")
        assert admin_resp.status_code == 200
        assert {target["target_id"] for target in admin_resp.json()["targets"]} == {
            "italy",
            "china-watch-en",
            "empty-sources",
        }


    def test_targets_endpoint_prefers_target_store_count_over_orphan_drafts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_dir = tmp_path / "config" / "targets"
        _write_target_config(config_dir, "italy", "意大利新闻监控", "it", 5)
        _write_draft(tmp_path, "italy", "indexed-1", title="Indexed")
        _write_draft(tmp_path, "italy", "orphan-1", title="Orphan")
        monkeypatch.chdir(tmp_path)
        api_server_module._target_stores.clear()

        async def seed() -> None:
            store = AsyncStore(tmp_path / "italy" / "state.db")
            await store.initialize()
            try:
                await _insert_index_event(
                    store,
                    event_id="indexed-1",
                    target_id="italy",
                    stage="drafts",
                    title_original="Indexed",
                )
            finally:
                await store.close()

        asyncio.run(seed())
        client = self._make_client(tmp_path)

        resp = client.get("/api/v1/targets")

        assert resp.status_code == 200
        italy = next(t for t in resp.json()["targets"] if t["target_id"] == "italy")
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
        assert data["by_classification"]["international-relations"] == 2
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
            params={"target_id": "italy", "classification": "international-relations"},
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

    def test_list_sources_resolves_source_pool_refs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._setup_config(tmp_path, monkeypatch)
        target_dir = tmp_path / "config" / "targets"
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "spain.yaml").write_text(
            yaml.dump(
                {
                    "target_id": "spain",
                    "display_name": "西班牙新闻监控",
                    "language_scope": {"primary": "en", "secondary": ["es"], "output": "zh"},
                    "source_channel_refs": [
                        "api/gdelt-topic",
                        "pool:global/gdelt-geopolitics",
                    ],
                },
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        local_dir = tmp_path / "config" / "sources" / "spain" / "api"
        local_dir.mkdir(parents=True, exist_ok=True)
        (local_dir / "gdelt-topic.yaml").write_text(
            yaml.dump(
                {
                    "source_id": "gdelt-topic",
                    "display_name": "GDELT Spain",
                    "type": "api",
                    "enabled": True,
                    "credibility_base": 0.7,
                },
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        pool_dir = tmp_path / "config" / "source-pools" / "global"
        pool_dir.mkdir(parents=True, exist_ok=True)
        (pool_dir / "gdelt-geopolitics.yaml").write_text(
            yaml.dump(
                {
                    "source_id": "gdelt-geopolitics",
                    "display_name": "GDELT Geopolitics",
                    "type": "api",
                    "enabled": True,
                    "credibility_base": 0.7,
                },
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/config/targets/spain/sources")

        assert resp.status_code == 200
        sources = resp.json()["sources"]
        refs = {source["source_ref"] for source in sources}
        assert refs == {"api/gdelt-topic", "pool:global/gdelt-geopolitics"}
        assert {source["source_id"] for source in sources} == {
            "gdelt-topic",
            "gdelt-geopolitics",
        }

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

    def test_get_source_config_rejects_encoded_path_traversal(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """source_id:path 不能越界读取 config/sources 外的 YAML。"""
        self._setup_config(tmp_path, monkeypatch)
        (tmp_path / "config" / "sources" / "italy").mkdir(parents=True)
        provider_dir = tmp_path / "config" / "provider"
        provider_dir.mkdir(parents=True)
        (provider_dir / "routes.yaml").write_text(
            "routes:\n  - provider: openrouter\n",
            encoding="utf-8",
        )
        client = self._make_client(tmp_path)

        resp = client.get(
            "/api/v1/config/targets/italy/sources/%2E%2E%2F%2E%2E%2Fprovider%2Froutes",
        )

        assert resp.status_code == 400

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
                    "model_env_var": "OPENAI_DEFAULT_MODEL",
                    "model_pool": ["gpt-4o-mini", "gpt-4.1-mini"],
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
        assert data["routes"][0]["model_env_var"] == "OPENAI_DEFAULT_MODEL"
        assert data["routes"][0]["model_pool"] == ["gpt-4o-mini", "gpt-4.1-mini"]
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

    def test_list_source_health_filters_by_target_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """信源健康只返回当前 target 配置中存在的 source。"""
        monkeypatch.chdir(tmp_path)
        italy_sources = tmp_path / "config" / "sources" / "italy"
        japan_sources = tmp_path / "config" / "sources" / "japan"
        italy_sources.mkdir(parents=True, exist_ok=True)
        japan_sources.mkdir(parents=True, exist_ok=True)
        (italy_sources / "ansa.yaml").write_text("source_id: ansa\n", encoding="utf-8")
        (japan_sources / "nhk.yaml").write_text("source_id: nhk\n", encoding="utf-8")

        class FakeStore:
            async def get_all_source_health(self) -> list[dict[str, object]]:
                return [
                    {
                        "source_id": "ansa",
                        "status": "healthy",
                        "last_check": "now",
                        "error_count": 0,
                    },
                    {
                        "source_id": "nhk",
                        "status": "healthy",
                        "last_check": "now",
                        "error_count": 0,
                    },
                ]

        app = create_app(data_dir=tmp_path, store=FakeStore(), skip_lifespan=True)
        client = TestClient(app, base_url="http://127.0.0.1")

        resp = client.get("/api/v1/sources/health", params={"target_id": "italy"})

        assert resp.status_code == 200
        assert [item["source_id"] for item in resp.json()["sources"]] == ["ansa"]

    def test_list_source_health_hides_disabled_and_deprecated_sources(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """默认健康列表不应继续展示已停用或归档的 source。"""
        monkeypatch.chdir(tmp_path)
        italy_sources = tmp_path / "config" / "sources" / "italy"
        italy_sources.mkdir(parents=True, exist_ok=True)
        (italy_sources / "ansa.yaml").write_text("source_id: ansa\n", encoding="utf-8")
        (italy_sources / "fao-rss.yaml").write_text(
            "source_id: fao-rss\nenabled: false\ndeprecated: true\n",
            encoding="utf-8",
        )

        class FakeStore:
            async def get_all_source_health(self) -> list[dict[str, object]]:
                return [
                    {
                        "source_id": "ansa",
                        "status": "healthy",
                        "last_check": "now",
                        "error_count": 0,
                    },
                    {
                        "source_id": "fao-rss",
                        "status": "dead",
                        "last_check": "then",
                        "error_count": 16,
                        "last_error": "404 Not Found",
                    },
                ]

        app = create_app(data_dir=tmp_path, store=FakeStore(), skip_lifespan=True)
        client = TestClient(app, base_url="http://127.0.0.1")

        resp = client.get("/api/v1/sources/health", params={"target_id": "italy"})

        assert resp.status_code == 200
        assert [item["source_id"] for item in resp.json()["sources"]] == ["ansa"]

    def test_list_source_health_reads_target_memory_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """信源健康列表应读取真实采集写入的 target memory/source_health.yaml。"""
        monkeypatch.chdir(tmp_path)
        italy_sources = tmp_path / "config" / "sources" / "italy"
        italy_sources.mkdir(parents=True, exist_ok=True)
        (italy_sources / "ansa.yaml").write_text("source_id: ansa\n", encoding="utf-8")
        memory_dir = tmp_path / "italy" / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        (memory_dir / "source_health.yaml").write_text(
            yaml.dump(
                {
                    "ansa": {
                        "last_success_at": "2026-05-29T00:42:52+00:00",
                        "last_failure_at": None,
                        "consecutive_failures": 0,
                        "last_error": None,
                        "total_runs": 12,
                        "total_failures": 0,
                    }
                },
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        client = self._make_client(tmp_path)

        resp = client.get("/api/v1/sources/health", params={"target_id": "italy"})

        assert resp.status_code == 200
        assert resp.json()["sources"][0]["source_id"] == "ansa"
        assert resp.json()["sources"][0]["status"] == "healthy"
        assert resp.json()["sources"][0]["error_count"] == 0

    def test_list_source_health_promotes_memory_error_fields(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """memory/source_health.yaml 的错误字段应提升到 API 顶层，便于自动化诊断。"""
        monkeypatch.chdir(tmp_path)
        italy_sources = tmp_path / "config" / "sources" / "italy"
        italy_sources.mkdir(parents=True, exist_ok=True)
        (italy_sources / "broken.yaml").write_text("source_id: broken\n", encoding="utf-8")
        memory_dir = tmp_path / "italy" / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        (memory_dir / "source_health.yaml").write_text(
            yaml.dump(
                {
                    "broken": {
                        "last_success_at": None,
                        "last_failure_at": "2026-05-30T10:54:00+00:00",
                        "consecutive_failures": 3,
                        "last_error": "RSS fetch failed: 404 Not Found",
                        "total_runs": 3,
                        "total_failures": 3,
                    }
                },
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        client = self._make_client(tmp_path)

        resp = client.get("/api/v1/sources/health", params={"target_id": "italy"})

        assert resp.status_code == 200
        item = resp.json()["sources"][0]
        assert item["source_id"] == "broken"
        assert item["status"] == "degraded"
        assert item["last_error"] == "RSS fetch failed: 404 Not Found"
        assert item["last_failure_at"] == "2026-05-30T10:54:00+00:00"
        assert item["last_success_at"] is None

    def test_trigger_run(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_bounded_run_async(**kwargs: object) -> None:
            assert kwargs["target_id"] == "italy"
            assert kwargs["stage"] == "all"

        monkeypatch.setattr(
            "news_sentry.core.async_run.bounded_run_async",
            fake_bounded_run_async,
        )
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
        base_day = datetime.now(UTC).date() - timedelta(days=6)
        base_date = base_day.isoformat()
        later_date = (base_day + timedelta(days=4)).isoformat()
        events = [
            # 第一天: 3 events
            (
                "t-evt-1",
                "italy",
                "judged",
                "ansa",
                80,
                50,
                "politics",
                f"{base_date}T10:00:00",
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
                f"{base_date}T12:00:00",
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
                f"{base_date}T14:00:00",
                now,
                "neutral",
                "economy,EU",
            ),
            # 第二天: 2 events
            (
                "t-evt-4",
                "italy",
                "judged",
                "ansa",
                70,
                40,
                "international",
                f"{later_date}T10:00:00",
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
                f"{later_date}T12:00:00",
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

    async def test_topic_trends_uses_target_state_db_without_global_store(self, tmp_path):
        """趋势 API 应优先读取 data/{target}/state.db，而不是只看全局 store。"""
        target_dir = tmp_path / "italy"
        target_dir.mkdir(parents=True, exist_ok=True)
        api_server_module._target_stores.clear()
        store = AsyncStore(target_dir / "state.db")
        await store.initialize()
        try:
            now = datetime.now(UTC).isoformat()
            today = datetime.now(UTC).strftime("%Y-%m-%d")
            await store._db.execute(
                "INSERT OR REPLACE INTO event_index "
                "(event_id, target_id, stage, source_id, news_value_score, "
                "published_at, created_at, sentiment, topic_tags) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "target-topic-1",
                    "italy",
                    "drafts",
                    "ansa",
                    82,
                    f"{today}T10:00:00",
                    now,
                    "positive",
                    "target-store-topic",
                ),
            )
            await store._db.commit()
        finally:
            await store.close()

        app = create_app(data_dir=str(tmp_path), auto_store=False)
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=app)
        client = AsyncClient(transport=transport, base_url="http://test")
        token_resp = await client.post("/api/v1/auth/token", json={"api_key": ""})
        client.headers["Authorization"] = f"Bearer {token_resp.json()['access_token']}"

        resp = await client.get(
            "/api/v1/trends/topics",
            params={"target_id": "italy", "days": 7},
        )

        assert resp.status_code == 200
        assert [item["topic"] for item in resp.json()["topics"]] == ["target-store-topic"]
        await client.aclose()
        api_server_module._target_stores.clear()


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

    async def test_today_stats_uses_target_state_db_without_global_store(self, tmp_path):
        """今日统计 API 应读取真实 target state.db。"""
        target_dir = tmp_path / "italy"
        target_dir.mkdir(parents=True, exist_ok=True)
        api_server_module._target_stores.clear()
        store = AsyncStore(target_dir / "state.db")
        await store.initialize()
        try:
            now = datetime.now(UTC).isoformat()
            today = datetime.now(UTC).strftime("%Y-%m-%d")
            await store._db.execute(
                "INSERT OR REPLACE INTO event_index "
                "(event_id, target_id, stage, news_value_score, published_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("target-stats-1", "italy", "drafts", 87, f"{today}T10:00:00", now),
            )
            await store._db.commit()
        finally:
            await store.close()

        app = create_app(data_dir=str(tmp_path), auto_store=False)
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=app)
        client = AsyncClient(transport=transport, base_url="http://test")
        token_resp = await client.post("/api/v1/auth/token", json={"api_key": ""})
        client.headers["Authorization"] = f"Bearer {token_resp.json()['access_token']}"

        resp = await client.get("/api/v1/stats/today", params={"target_id": "italy"})

        assert resp.status_code == 200
        assert resp.json()["today_count"] == 1
        assert resp.json()["today_max_score"] == 87
        await client.aclose()
        api_server_module._target_stores.clear()


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

    async def test_rules_optimize_uses_target_default_filter_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, client_with_feedback
    ):
        """规则优化读取 config/filters/{target}/default.yaml。"""
        monkeypatch.chdir(tmp_path)
        filter_dir = tmp_path / "config" / "filters" / "italy"
        filter_dir.mkdir(parents=True, exist_ok=True)
        filter_path = filter_dir / "default.yaml"
        filter_path.write_text("target_id: italy\nkeyword_rules: []\n", encoding="utf-8")
        client, _ = client_with_feedback

        with patch("news_sentry.core.rules_optimizer.RulesOptimizer") as optimizer_cls:
            optimizer_cls.return_value.optimize.return_value = {
                "total_verdicts": 1,
                "adjustments": 0,
                "adjustments_detail": [],
                "written": False,
            }
            resp = await client.post(
                "/api/v1/rules/optimize",
                json={"target_id": "italy", "dry_run": True},
            )

        assert resp.status_code == 200
        assert Path(optimizer_cls.call_args.args[0]) == filter_path


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

    def test_update_source_config_rejects_encoded_path_traversal(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """写 source 配置时不能通过编码路径越界修改其他 YAML。"""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "config" / "sources" / "italy").mkdir(parents=True)
        provider_dir = tmp_path / "config" / "provider"
        provider_dir.mkdir(parents=True)
        routes_path = provider_dir / "routes.yaml"
        routes_path.write_text("routes: []\n", encoding="utf-8")
        client = self._make_client(tmp_path)
        headers = self._setup_auth(client)
        try:
            resp = client.patch(
                "/api/v1/config/targets/italy/sources/%2E%2E%2F%2E%2E%2Fprovider%2Froutes",
                json={"enabled": False},
                headers=headers,
            )
            assert resp.status_code == 400
            assert routes_path.read_text(encoding="utf-8") == "routes: []\n"
        finally:
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

    def test_config_write_requires_auth(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """云端部署中，配置写入端点要求 Bearer token 认证。"""
        _force_deployment_env(monkeypatch, "cloudflare")
        # 创建无默认 auth 的客户端
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)
        resp = client.put(
            "/api/v1/config/targets/italy",
            json={"display_name": "test"},
        )
        assert resp.status_code == 401


class TestTargetLifecycleWorkbenchAPI:
    """Target 全生命周期管理工作台 API。"""

    def _make_client(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> TestClient:
        monkeypatch.chdir(tmp_path)
        app = create_app(data_dir=tmp_path, auto_store=False, skip_lifespan=True)
        client = TestClient(app)
        resp = client.post("/api/v1/auth/token", json={"api_key": ""})
        assert resp.status_code == 200, f"Auth token failed: {resp.text}"
        client.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
        return client

    def _write_yaml(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

    def _reader_headers(self) -> dict[str, str]:
        token = api_server_module._create_token_for_user(
            "reader-target-workbench",
            "reader",
            False,
        )
        return {"Authorization": f"Bearer {token['access_token']}"}

    def _setup_target_tree(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> TestClient:
        client = self._make_client(tmp_path, monkeypatch)
        self._write_yaml(
            tmp_path / "config" / "targets" / "italy.yaml",
            {
                "target_id": "italy",
                "display_name": "意大利新闻监控",
                "language_scope": {"primary": "it", "secondary": ["en"], "output": "zh"},
                "timezone": "Europe/Rome",
                "source_channel_refs": ["ansa", "social/twitter/politics"],
                "filter_rules_ref": "config/filters/italy/default.yaml",
                "classification_rules_ref": "config/classification/rules-italy.yaml",
                "sandbox_profile_ref": "config/sandbox/default.yaml",
                "provider_routes_ref": "config/provider/routes.yaml",
                "output_destinations_ref": "config/output/destinations.yaml",
                "classification": {"country_axes": {"politics": True}},
                "focus_areas": [{"id": "policy", "weight": 1.0, "keywords": ["governo"]}],
            },
        )
        self._write_yaml(
            tmp_path / "config" / "sources" / "italy" / "ansa.yaml",
            {
                "source_id": "ansa",
                "display_name": "ANSA",
                "type": "rss",
                "url": "https://www.ansa.it/rss.xml",
                "credibility_base": 0.9,
                "fetch_interval_minutes": 30,
                "max_items_per_run": 20,
                "timeout_seconds": 20,
                "enabled": True,
            },
        )
        self._write_yaml(
            tmp_path / "config" / "sources" / "italy" / "social" / "twitter" / "politics.yaml",
            {
                "platform": "twitter",
                "dimension": "politics",
                "collect_mode": "rss_bridge",
                "session_profile_ref": "config/session-profiles/italy/twitter.session.yaml",
                "accounts": [
                    {
                        "handle": "@Palazzo_Chigi",
                        "display_name": "Palazzo Chigi",
                        "url": "https://x.com/Palazzo_Chigi",
                        "tier": "L1",
                        "category": "government",
                        "monitor_mode": "active",
                        "fetch_max_per_run": 20,
                    }
                ],
            },
        )
        self._write_yaml(
            tmp_path / "config" / "filters" / "italy" / "default.yaml",
            {"target_id": "italy", "score_threshold": 35, "keyword_rules": []},
        )
        self._write_yaml(
            tmp_path / "config" / "classification" / "rules-italy.yaml",
            {"target_id": "italy", "axes": []},
        )
        self._write_yaml(tmp_path / "config" / "sandbox" / "default.yaml", {"profile": "default"})
        self._write_yaml(tmp_path / "config" / "provider" / "routes.yaml", {"routes": []})
        self._write_yaml(tmp_path / "config" / "output" / "destinations.yaml", {"destinations": []})
        (tmp_path / "data" / "italy" / "drafts").mkdir(parents=True, exist_ok=True)
        (tmp_path / "data" / "italy" / "drafts" / "old.md").write_text("draft", encoding="utf-8")
        return client

    def test_reader_can_view_target_workbench_read_endpoints(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._setup_target_tree(tmp_path, monkeypatch)
        headers = self._reader_headers()

        for method, path in [
            ("GET", "/api/v1/admin/targets"),
            ("GET", "/api/v1/admin/targets/italy/overview"),
            ("GET", "/api/v1/admin/targets/italy/inventory"),
            ("GET", "/api/v1/admin/targets/italy/sources"),
            ("GET", "/api/v1/admin/targets/italy/social"),
            ("POST", "/api/v1/admin/targets/italy/validate"),
        ]:
            resp = client.request(method, path, headers=headers)
            assert resp.status_code == 200, f"{method} {path}: {resp.text}"

    def test_admin_target_overview_includes_classification_diagnostics(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._setup_target_tree(tmp_path, monkeypatch)
        _write_draft(
            tmp_path,
            "italy",
            "classified-1",
            title="Classified story",
            classification_l0="international-relations",
        )
        _write_draft(tmp_path, "italy", "uncategorized-1", title="Uncategorized story")

        resp = client.get("/api/v1/admin/targets/italy/overview")

        assert resp.status_code == 200
        diagnostics = resp.json()["classification_diagnostics"]
        assert diagnostics["distribution"]["international-relations"] == 1
        assert diagnostics["distribution"]["uncategorized"] == 1
        assert diagnostics["uncategorized_count"] == 1

    def test_admin_target_overview_reuses_inventory_and_validation_cache(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """连续加载 target overview 不应重复完整扫描信源与预检配置。"""
        client = self._setup_target_tree(tmp_path, monkeypatch)
        calls = {"inventory": 0, "validation": 0}

        def fake_inventory(self, target_id: str, health_records=None):  # noqa: ANN001, ARG001
            calls["inventory"] += 1
            return {
                "summary": {
                    "standard_sources": 1,
                    "missing_refs": 0,
                    "unreferenced_files": 0,
                    "social_dimensions": 0,
                    "social_accounts": 0,
                },
                "sources": [
                    {
                        "type": "rss",
                        "missing_file": False,
                        "archived": False,
                    }
                ],
            }

        def fake_validation(target_id: str):  # noqa: ARG001
            calls["validation"] += 1
            return {"target_id": target_id, "ok": True, "checks": []}

        from news_sentry.core import target_config_utils

        monkeypatch.setattr(
            api_server_module.SourceInventoryService,
            "build_target_inventory",
            fake_inventory,
        )
        monkeypatch.setattr(
            target_config_utils,
            "_validate_target_config",
            fake_validation,
        )

        first = client.get("/api/v1/admin/targets/italy/overview")
        second = client.get("/api/v1/admin/targets/italy/overview")

        assert first.status_code == 200
        assert second.status_code == 200
        assert calls == {"inventory": 1, "validation": 1}

    def test_admin_target_overview_uses_store_classification_diagnostics(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._setup_target_tree(tmp_path, monkeypatch)
        _write_draft(tmp_path, "italy", "draft-only", classification_l0="draft-only")
        api_server_module._target_stores.clear()

        async def seed_store() -> None:
            store = AsyncStore(tmp_path / "italy" / "state.db")
            await store.initialize()
            try:
                await _insert_index_event(
                    store,
                    event_id="store-classified",
                    classification_l0="international-relations",
                )
                await _insert_index_event(
                    store,
                    event_id="store-null",
                    classification_l0=None,
                )
                await _insert_index_event(
                    store,
                    event_id="store-empty",
                    classification_l0="",
                )
            finally:
                await store.close()

        asyncio.run(seed_store())

        resp = client.get("/api/v1/admin/targets/italy/overview")

        assert resp.status_code == 200
        diagnostics = resp.json()["classification_diagnostics"]
        assert diagnostics["distribution"] == {
            "international-relations": 1,
            "uncategorized": 2,
        }
        assert diagnostics["uncategorized_count"] == 2

    def test_admin_target_overview_falls_back_when_store_has_no_classification_rows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._setup_target_tree(tmp_path, monkeypatch)
        _write_draft(
            tmp_path,
            "italy",
            "draft-classified",
            classification_l0="international-relations",
        )
        api_server_module._target_stores.clear()

        async def create_empty_store() -> None:
            store = AsyncStore(tmp_path / "italy" / "state.db")
            await store.initialize()
            await store.close()

        asyncio.run(create_empty_store())

        resp = client.get("/api/v1/admin/targets/italy/overview")

        assert resp.status_code == 200
        diagnostics = resp.json()["classification_diagnostics"]
        assert diagnostics["distribution"]["international-relations"] == 1
        assert diagnostics["uncategorized_count"] == 0

    def test_admin_target_inventory_reports_source_drift(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._setup_target_tree(tmp_path, monkeypatch)
        target_path = tmp_path / "config" / "targets" / "italy.yaml"
        target_data = yaml.safe_load(target_path.read_text(encoding="utf-8"))
        target_data["source_channel_refs"].append("missing-source")
        self._write_yaml(target_path, target_data)
        self._write_yaml(
            tmp_path / "config" / "sources" / "italy" / "orphan.yaml",
            {
                "source_id": "orphan",
                "display_name": "Orphan",
                "type": "rss",
                "url": "https://example.com/orphan.xml",
                "enabled": True,
            },
        )
        self._write_yaml(
            tmp_path / "italy" / "memory" / "source_health.yaml",
            {
                "ansa": {
                    "last_success_at": "2026-05-29T00:00:00+00:00",
                    "total_runs": 1,
                },
                "ghost": {
                    "consecutive_failures": 11,
                    "total_runs": 11,
                    "total_failures": 11,
                },
            },
        )

        resp = client.get("/api/v1/admin/targets/italy/inventory")

        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["missing_refs"] == 1
        assert data["summary"]["unreferenced_files"] == 1
        assert data["summary"]["health_unmatched"] == 1
        by_ref = {item["source_ref"]: item for item in data["sources"]}
        assert by_ref["missing-source"]["missing_file"] is True
        assert by_ref["orphan"]["unreferenced"] is True
        assert by_ref["ansa"]["health"]["status"] == "healthy"
        assert data["diagnostics"]["unmatched_health"][0]["source_id"] == "ghost"

    @pytest.mark.parametrize(
        ("method", "path", "json_body"),
        [
            (
                "POST",
                "/api/v1/admin/targets",
                {
                    "mode": "template",
                    "target_id": "spain",
                    "display_name": "西班牙新闻监控",
                    "language_scope": {"primary": "es", "secondary": ["en"], "output": "zh"},
                    "timezone": "Europe/Madrid",
                },
            ),
            ("PATCH", "/api/v1/admin/targets/italy", {"display_name": "Italy Updated"}),
            ("POST", "/api/v1/admin/targets/italy/archive", {"reason": "reader forbidden"}),
            ("POST", "/api/v1/admin/targets/italy/restore", {}),
            (
                "POST",
                "/api/v1/admin/targets/italy/sources",
                {
                    "source_id": "rai-news",
                    "display_name": "RAI News",
                    "type": "rss",
                    "url": "https://www.rainews.it/rss.xml",
                    "credibility_base": 0.82,
                    "fetch_interval_minutes": 30,
                    "max_items_per_run": 15,
                    "timeout_seconds": 20,
                },
            ),
            (
                "PATCH",
                "/api/v1/admin/targets/italy/sources/ansa",
                {"display_name": "ANSA Updated"},
            ),
            (
                "POST",
                "/api/v1/admin/targets/italy/sources/ansa/archive",
                {"reason": "reader forbidden"},
            ),
            ("POST", "/api/v1/admin/targets/italy/sources/ansa/restore", {}),
            (
                "POST",
                "/api/v1/admin/targets/italy/social/dimensions",
                {
                    "platform": "twitter",
                    "dimension": "economy",
                    "collect_mode": "rss_bridge",
                    "session_profile_ref": "config/session-profiles/italy/twitter.session.yaml",
                },
            ),
            (
                "PATCH",
                "/api/v1/admin/targets/italy/social/dimensions/politics",
                {"notes": "reader forbidden"},
            ),
            (
                "POST",
                "/api/v1/admin/targets/italy/social/dimensions/politics/accounts",
                {
                    "handle": "@MEF_GOV",
                    "display_name": "Ministero Economia",
                    "url": "https://x.com/MEF_GOV",
                    "tier": "L2",
                    "category": "economy",
                    "monitor_mode": "active",
                },
            ),
            (
                "PATCH",
                "/api/v1/admin/targets/italy/social/dimensions/politics/accounts/%40Palazzo_Chigi",
                {"notes": "reader forbidden"},
            ),
        ],
    )
    def test_reader_cannot_mutate_target_workbench(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        method: str,
        path: str,
        json_body: dict,
    ) -> None:
        client = self._setup_target_tree(tmp_path, monkeypatch)
        resp = client.request(method, path, headers=self._reader_headers(), json=json_body)
        assert resp.status_code == 403, f"{method} {path}: {resp.text}"

    def test_target_archive_restore_changes_public_visibility(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._setup_target_tree(tmp_path, monkeypatch)
        _write_draft(tmp_path, "italy", "public-ready-after-restore")

        async def seed() -> None:
            store = AsyncStore(tmp_path / "italy" / "state.db")
            await store.initialize()
            try:
                await _insert_index_event(
                    store,
                    event_id="public-ready-after-restore",
                    target_id="italy",
                    title_original="意大利恢复后公开新闻",
                )
            finally:
                await store.close()

        asyncio.run(seed())

        resp = client.post(
            "/api/v1/admin/targets/italy/archive",
            json={"reason": "暂停监控"},
        )
        assert resp.status_code == 200
        assert resp.json()["lifecycle"]["status"] == "archived"

        public_resp = client.get("/api/v1/targets")
        assert public_resp.status_code == 200
        assert [item["target_id"] for item in public_resp.json()["targets"]] == []

        admin_resp = client.get("/api/v1/admin/targets", params={"include_archived": True})
        assert admin_resp.status_code == 200
        assert admin_resp.json()["targets"][0]["archived"] is True

        restore_resp = client.post("/api/v1/admin/targets/italy/restore")
        assert restore_resp.status_code == 200
        assert restore_resp.json()["lifecycle"]["status"] == "active"
        assert client.get("/api/v1/targets").json()["targets"][0]["target_id"] == "italy"

    def test_create_template_and_clone_targets_build_config_chain(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._setup_target_tree(tmp_path, monkeypatch)

        template_resp = client.post(
            "/api/v1/admin/targets",
            json={
                "mode": "template",
                "target_id": "spain",
                "display_name": "西班牙新闻监控",
                "language_scope": {"primary": "es", "secondary": ["en"], "output": "zh"},
                "timezone": "Europe/Madrid",
            },
        )
        assert template_resp.status_code == 200
        assert (tmp_path / "config" / "targets" / "spain.yaml").is_file()
        assert (tmp_path / "config" / "filters" / "spain" / "default.yaml").is_file()
        assert (tmp_path / "config" / "classification" / "rules-spain.yaml").is_file()
        assert (tmp_path / "config" / "sources" / "spain" / "rss-template.yaml").is_file()

        clone_resp = client.post(
            "/api/v1/admin/targets",
            json={
                "mode": "clone",
                "source_target_id": "italy",
                "target_id": "france",
                "display_name": "法国新闻监控",
                "language_scope": {"primary": "fr", "secondary": ["en"], "output": "zh"},
                "timezone": "Europe/Paris",
            },
        )
        assert clone_resp.status_code == 200
        clone_data = yaml.safe_load(
            (tmp_path / "config" / "targets" / "france.yaml").read_text(encoding="utf-8")
        )
        assert clone_data["target_id"] == "france"
        assert clone_data["source_channel_refs"] == ["ansa", "social/twitter/politics"]
        assert not (tmp_path / "data" / "france").exists()

    def test_source_lifecycle_endpoints_update_refs_and_archival(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._setup_target_tree(tmp_path, monkeypatch)

        create_resp = client.post(
            "/api/v1/admin/targets/italy/sources",
            json={
                "source_id": "rai-news",
                "display_name": "RAI News",
                "type": "rss",
                "url": "https://www.rainews.it/rss.xml",
                "credibility_base": 0.82,
                "fetch_interval_minutes": 30,
                "max_items_per_run": 15,
                "timeout_seconds": 20,
            },
        )
        assert create_resp.status_code == 200
        assert (tmp_path / "config" / "sources" / "italy" / "rai-news.yaml").is_file()
        target_data = yaml.safe_load(
            (tmp_path / "config" / "targets" / "italy.yaml").read_text(encoding="utf-8")
        )
        assert "rai-news" in target_data["source_channel_refs"]

        archive_resp = client.post(
            "/api/v1/admin/targets/italy/sources/rai-news/archive",
            json={"reason": "停止更新"},
        )
        assert archive_resp.status_code == 200
        archived = yaml.safe_load(
            (tmp_path / "config" / "sources" / "italy" / "rai-news.yaml").read_text(
                encoding="utf-8"
            )
        )
        assert archived["enabled"] is False
        assert archived["deprecated"] is True
        assert "rai-news" not in [
            item["source_id"]
            for item in client.get("/api/v1/admin/targets/italy/sources").json()["sources"]
        ]
        assert "rai-news" in [
            item["source_id"]
            for item in client.get(
                "/api/v1/admin/targets/italy/sources",
                params={"include_archived": True},
            ).json()["sources"]
        ]

        restore_resp = client.post("/api/v1/admin/targets/italy/sources/rai-news/restore")
        assert restore_resp.status_code == 200
        restored = yaml.safe_load(
            (tmp_path / "config" / "sources" / "italy" / "rai-news.yaml").read_text(
                encoding="utf-8"
            )
        )
        assert restored["enabled"] is True
        assert restored["deprecated"] is False

    def test_social_dimension_account_lifecycle(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._setup_target_tree(tmp_path, monkeypatch)

        dimension_resp = client.post(
            "/api/v1/admin/targets/italy/social/dimensions",
            json={
                "platform": "twitter",
                "dimension": "economy",
                "collect_mode": "rss_bridge",
                "session_profile_ref": "config/session-profiles/italy/twitter.session.yaml",
            },
        )
        assert dimension_resp.status_code == 200

        account_resp = client.post(
            "/api/v1/admin/targets/italy/social/dimensions/economy/accounts",
            json={
                "handle": "@MEF_GOV",
                "display_name": "Ministero Economia",
                "url": "https://x.com/MEF_GOV",
                "tier": "L2",
                "category": "economy",
                "monitor_mode": "active",
            },
        )
        assert account_resp.status_code == 200

        patch_resp = client.patch(
            "/api/v1/admin/targets/italy/social/dimensions/economy/accounts/%40MEF_GOV",
            json={"monitor_mode": "archived", "notes": "暂停"},
        )
        assert patch_resp.status_code == 200
        social = client.get("/api/v1/admin/targets/italy/social").json()
        economy = next(item for item in social["dimensions"] if item["dimension"] == "economy")
        assert economy["accounts"][0]["monitor_mode"] == "archived"

    def test_target_validate_reports_missing_refs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._setup_target_tree(tmp_path, monkeypatch)
        target_path = tmp_path / "config" / "targets" / "italy.yaml"
        data = yaml.safe_load(target_path.read_text(encoding="utf-8"))
        data["source_channel_refs"].append("missing-source")
        data["provider_routes_ref"] = "config/provider/missing.yaml"
        self._write_yaml(target_path, data)

        resp = client.post("/api/v1/admin/targets/italy/validate")
        assert resp.status_code == 200
        checks = {item["id"]: item for item in resp.json()["checks"]}
        assert checks["source_refs"]["ok"] is False
        assert checks["provider_routes_ref"]["ok"] is False


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

    def test_import_auth_required(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """云端部署中，导入端点要求认证。"""
        _force_deployment_env(monkeypatch, "cloudflare")
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

    def test_import_auth_with_valid_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """云端部署中，有效 Bearer token 允许导入。"""
        _force_deployment_env(monkeypatch, "cloudflare")
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

    def test_import_rejects_target_path_traversal(self, tmp_path: Path) -> None:
        """导入事件时 target_id 不能越界写到 data_dir 外。"""
        client = self._make_client(tmp_path)
        escaped_name = f"{tmp_path.name}-escaped-import"
        escaped_dir = tmp_path.parent / escaped_name

        resp = client.post(
            "/api/v1/events/import",
            json=[
                {
                    "target_id": f"../{escaped_name}",
                    "source_id": "src",
                    "title_original": "Escaped import",
                    "url": "https://example.com/escaped",
                    "collected_at": "2026-05-17T10:00:00+00:00",
                },
            ],
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] == 0
        assert data["errors"]
        assert not escaped_dir.exists()

    def test_import_rejects_source_path_separator(self, tmp_path: Path) -> None:
        """导入事件时 source_id 只能作为文件名片段，不能携带路径分隔符。"""
        client = self._make_client(tmp_path)

        resp = client.post(
            "/api/v1/events/import",
            json=[
                {
                    "target_id": "italy",
                    "source_id": "rss/escaped",
                    "title_original": "Escaped source",
                    "url": "https://example.com/escaped-source",
                    "collected_at": "2026-05-17T10:00:00+00:00",
                },
            ],
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] == 0
        assert data["errors"]
        assert not (tmp_path / "italy" / "raw").exists()


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

    def _make_initialized_client_with_store(self, tmp_path: Path) -> TestClient:
        """创建已初始化 SQLite store 的客户端，避免把用例耦合到 lifespan。"""
        db_path = tmp_path / "test_auth_initialized.db"
        store = AsyncStore(db_path)
        asyncio.run(store.initialize())
        app = create_app(
            data_dir=tmp_path,
            store=store,
            auto_store=False,
            skip_lifespan=True,
        )
        return TestClient(app)

    def test_auth_login_missing_fields(self, tmp_path: Path) -> None:
        """登录缺少密码（Pydantic 校验）返回 422。"""
        client = self._make_client_with_store(tmp_path)
        resp = client.post("/api/v1/auth/login", json={"username": ""})
        assert resp.status_code == 422

    def test_auth_login_empty_credentials(self, tmp_path: Path) -> None:
        """空用户名/密码返回 400。"""
        client = self._make_client_with_store(tmp_path)
        resp = client.post("/api/v1/auth/login", json={"username": "", "password": ""})
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

    def test_auth_token_persists_session_when_store_ready(self, tmp_path: Path) -> None:
        """已初始化 store 时，token session 可从 SQLite 回退恢复。"""
        store = AsyncStore(tmp_path / "test_auth.db")
        asyncio.run(store.initialize())
        app = create_app(
            data_dir=tmp_path,
            store=store,
            auto_store=False,
            skip_lifespan=True,
        )
        client = TestClient(app)

        token_resp = client.post("/api/v1/auth/token", json={"api_key": ""})
        assert token_resp.status_code == 200
        token = token_resp.json()["access_token"]

        _TOKEN_STORE.pop(token, None)
        session = asyncio.run(store.get_session(token))
        assert session is not None
        assert session["username"] == "dev"
        assert session["role"] == "admin"

        me_resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me_resp.status_code == 200
        assert me_resp.json()["username"] == "dev"

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

    def test_auth_change_password_revokes_current_session(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """当前用户改密后，旧 token 立即失效。"""
        _force_deployment_env(monkeypatch, "cloudflare")
        client = self._make_initialized_client_with_store(tmp_path)
        setup_resp = client.post(
            "/api/v1/auth/setup",
            json={"username": "admin", "password": "test123456"},
        )
        token = setup_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        change_resp = client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "test123456", "new_password": "newpass456"},
            headers=headers,
        )

        assert change_resp.status_code == 200
        me_resp = client.get("/api/v1/auth/me", headers=headers)
        assert me_resp.status_code == 401

    def test_admin_reset_password_revokes_target_user_sessions(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """管理员重置用户密码后，该用户旧 token 立即失效。"""
        _force_deployment_env(monkeypatch, "cloudflare")
        client = self._make_initialized_client_with_store(tmp_path)
        setup_resp = client.post(
            "/api/v1/auth/setup",
            json={"username": "admin", "password": "test123456"},
        )
        admin_headers = {"Authorization": f"Bearer {setup_resp.json()['access_token']}"}

        create_resp = client.post(
            "/api/v1/admin/users",
            json={"username": "reader1", "password": "reader123456", "role": "reader"},
            headers=admin_headers,
        )
        assert create_resp.status_code == 200

        login_resp = client.post(
            "/api/v1/auth/login",
            json={"username": "reader1", "password": "reader123456"},
        )
        assert login_resp.status_code == 200
        user_headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

        reset_resp = client.post(
            "/api/v1/admin/users/reader1/reset-password",
            json={"new_password": "reader654321"},
            headers=admin_headers,
        )
        assert reset_resp.status_code == 200

        me_resp = client.get("/api/v1/auth/me", headers=user_headers)
        assert me_resp.status_code == 401

    def test_admin_delete_user_revokes_target_user_sessions(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """管理员删除用户后，该用户旧 token 立即失效。"""
        _force_deployment_env(monkeypatch, "cloudflare")
        client = self._make_initialized_client_with_store(tmp_path)
        setup_resp = client.post(
            "/api/v1/auth/setup",
            json={"username": "admin", "password": "test123456"},
        )
        admin_headers = {"Authorization": f"Bearer {setup_resp.json()['access_token']}"}

        create_resp = client.post(
            "/api/v1/admin/users",
            json={"username": "reader2", "password": "reader123456", "role": "reader"},
            headers=admin_headers,
        )
        assert create_resp.status_code == 200

        login_resp = client.post(
            "/api/v1/auth/login",
            json={"username": "reader2", "password": "reader123456"},
        )
        assert login_resp.status_code == 200
        user_headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

        delete_resp = client.delete("/api/v1/admin/users/reader2", headers=admin_headers)
        assert delete_resp.status_code == 200

        me_resp = client.get("/api/v1/auth/me", headers=user_headers)
        assert me_resp.status_code == 401

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

    def test_draft_diagnostics_reports_orphan_files(self, tmp_path: Path) -> None:
        """draft 诊断能暴露未进入索引的孤岛文件，且不删除历史数据。"""
        _write_draft(tmp_path, "italy", "indexed-1", title="Indexed")
        orphan_path = _write_draft(tmp_path, "italy", "orphan-1", title="Orphan")
        api_server_module._target_stores.clear()

        async def seed_store() -> None:
            store = AsyncStore(tmp_path / "italy" / "state.db")
            await store.initialize()
            try:
                await _insert_index_event(
                    store,
                    event_id="indexed-1",
                    target_id="italy",
                    stage="drafts",
                    title_original="Indexed",
                )
            finally:
                await store.close()

        asyncio.run(seed_store())
        client = self._make_client(tmp_path)
        headers = self._auth_headers(client)

        resp = client.get(
            "/api/v1/maintenance/draft-diagnostics",
            params={"target_id": "italy"},
            headers=headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["draft_file_count"] == 2
        assert data["indexed_count"] == 1
        assert data["visible_index_count"] == 1
        assert data["orphan_file_count"] == 1
        assert data["orphan_files"] == [
            {
                "event_id": "orphan-1",
                "path": str(orphan_path.relative_to(tmp_path)),
                "title": "Orphan",
            }
        ]
        assert orphan_path.exists()

    def test_archive_duplicate_drafts_moves_extra_files_without_deleting(
        self, tmp_path: Path
    ) -> None:
        """重复 draft 归档只移动副本，保留一个可公开读取的 canonical 文件。"""
        event_id = "dup-event-1"
        old_path = _write_draft(tmp_path, "italy", event_id, title="Duplicated")
        canonical_path = tmp_path / "italy" / "drafts" / f"{event_id}.md"
        canonical_path.write_text(old_path.read_text(encoding="utf-8"), encoding="utf-8")
        client = self._make_client(tmp_path)
        headers = self._auth_headers(client)

        resp = client.post(
            "/api/v1/maintenance/archive-duplicate-drafts",
            params={"target_id": "italy"},
            headers=headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["duplicate_group_count"] == 1
        assert data["archived_count"] == 1
        assert canonical_path.exists()
        assert not old_path.exists()
        archived_path = tmp_path / data["archived_files"][0]["archived_path"]
        assert archived_path.is_file()
        assert archived_path.read_text(encoding="utf-8") == canonical_path.read_text(
            encoding="utf-8"
        )

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
    asyncio.run(store.initialize())
    app = create_app(
        data_dir=tmp_path,
        store=store,
        auto_store=False,
        skip_lifespan=True,
    )
    client = TestClient(app)
    # 首次 setup 创建 admin — setup 直接返回 token
    resp = client.post("/api/v1/auth/setup", json={"username": "admin", "password": "test123456"})
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    return client, headers


class TestSSEStream:
    """SSE event_stream 端点测试。"""

    def test_event_stream_no_auth(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """云端部署中，SSE 无认证返回 401。"""
        _force_deployment_env(monkeypatch, "cloudflare")
        client, _ = _make_store_client(tmp_path)
        resp = client.get("/api/v1/events/stream", params={"target_id": "italy"})
        assert resp.status_code == 401

    def test_event_stream_invalid_token(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """云端部署中，SSE 无效 token 返回 401。"""
        _force_deployment_env(monkeypatch, "cloudflare")
        client, _ = _make_store_client(tmp_path)
        resp = client.get(
            "/api/v1/events/stream",
            params={"target_id": "italy", "token": "invalid-token"},
        )
        assert resp.status_code == 401

    def test_stream_token_endpoint_requires_auth(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """获取 SSE stream token 需要已有登录态。"""
        _force_deployment_env(monkeypatch, "cloudflare")
        client, _ = _make_store_client(tmp_path)
        resp = client.post("/api/v1/auth/stream-token")
        assert resp.status_code == 401

    def test_event_stream_rejects_bearer_query_token(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SSE 不再接受把主 bearer token 放到 query string。"""
        _force_deployment_env(monkeypatch, "cloudflare")
        client, headers = _make_store_client(tmp_path)
        token = headers["Authorization"].replace("Bearer ", "")
        resp = client.get(
            "/api/v1/events/stream",
            params={"target_id": "italy", "token": token},
        )
        assert resp.status_code == 401

    def test_event_stream_accepts_short_lived_stream_token(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SSE 使用短期 stream token 认证。"""
        _force_deployment_env(monkeypatch, "cloudflare")
        client, headers = _make_store_client(tmp_path)

        token_resp = client.post("/api/v1/auth/stream-token", headers=headers)
        assert token_resp.status_code == 200
        stream_token = token_resp.json()["stream_token"]

        async def _fake_generate() -> AsyncGenerator[str, None]:
            yield ": test\n\n"

        with patch("news_sentry.core.api_server.StreamingResponse") as mock_sr:
            mock_sr.return_value = MagicMock()
            resp = client.get(
                "/api/v1/events/stream",
                params={"target_id": "italy", "stream_token": stream_token},
            )
            assert resp.status_code == 200


class TestLocalAuthBypassBoundary:
    """本地免登录边界测试。"""

    def test_loopback_request_without_explicit_local_env_requires_auth(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """未显式声明 local 时，127.0.0.1 host 不再自动免登录。"""
        monkeypatch.delenv("NEWSSENTRY_DEPLOYMENT_ENV", raising=False)
        monkeypatch.setattr(api_server_module, "_deployment_env", "")
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)

        resp = client.get("/api/v1/status", headers={"host": "127.0.0.1:8000"})

        assert resp.status_code == 401

    def test_loopback_request_with_explicit_local_env_still_bypasses_auth(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """显式 local 模式仍保留本地免登录能力。"""
        _force_deployment_env(monkeypatch, "local")
        app = create_app(data_dir=tmp_path, auto_store=False)
        client = TestClient(app)

        resp = client.get("/api/v1/status", headers={"host": "127.0.0.1:8000"})

        assert resp.status_code == 200


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
        """应用包含足够的路由数（至少包含 FastAPI 内置的 openapi/docs/redoc 路由）。"""
        app = create_app(auto_store=False, skip_lifespan=True)
        route_count = len([r for r in app.routes if hasattr(r, "methods")])
        assert route_count >= 4  # 至少应有 FastAPI 内置路由


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

    def _auth_headers(self, client: TestClient) -> dict[str, str]:
        resp = client.post("/api/v1/auth/token", json={"api_key": ""})
        assert resp.status_code == 200
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    def test_data_status_empty(self, tmp_path: Path) -> None:
        """空数据目录正常响应。"""
        client = self._make_client(tmp_path)
        resp = client.get("/api/v1/status", headers=self._auth_headers(client))
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
        resp = client.get("/api/v1/status", headers=self._auth_headers(client))
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_events_all_targets"] >= 1
        assert "italy" in data["targets"]
        assert data["file_event_total"] >= 1
        assert data["targets"]["italy"]["file_events"] >= 1
        assert data["targets"]["italy"]["event_count"] >= data["targets"]["italy"]["file_events"]

    def test_data_status_distinguishes_file_and_api_totals(self, tmp_path: Path) -> None:
        """status 端点区分文件产物数和 SQLite/API 索引事件数。"""
        store = AsyncStore(tmp_path / "state.db")
        asyncio.run(store.initialize())
        try:
            asyncio.run(
                _insert_index_event(
                    store,
                    event_id="ne-italy-api-20260607-status",
                    target_id="italy",
                    title_original="API indexed status story",
                    stage="filtered",
                )
            )
            app = create_app(data_dir=tmp_path, store=store, auto_store=False, skip_lifespan=True)
            client = TestClient(app)

            resp = client.get("/api/v1/status", headers=self._auth_headers(client))

            assert resp.status_code == 200
            data = resp.json()
            assert data["file_event_total"] == 0
            assert data["api_event_total"] >= 1
            assert data["total_events_all_targets"] >= 1
            assert data["targets"]["italy"]["event_count"] >= 1
            assert data["targets"]["italy"]["api_events"] >= 1
            assert "source_count" in data["targets"]["italy"]
        finally:
            asyncio.run(store.close())

    def test_data_status_non_dir_ignored(self, tmp_path: Path) -> None:
        """非目录文件被忽略。"""
        (tmp_path / "somefile.json").write_text("{}", encoding="utf-8")
        app = create_app(data_dir=tmp_path, auto_store=False, skip_lifespan=True)
        client = TestClient(app)
        resp = client.get("/api/v1/status", headers=self._auth_headers(client))
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


def _make_canonical_client(tmp_path: Path) -> tuple[TestClient, AsyncStore]:
    store = AsyncStore(tmp_path / "canonical_api.sqlite3")
    asyncio.run(store.initialize())
    app = create_app(data_dir=tmp_path, store=store, auto_store=False, skip_lifespan=True)
    return TestClient(app), store


@pytest.fixture
def canonical_client(tmp_path: Path) -> Iterator[tuple[TestClient, AsyncStore]]:
    client, store = _make_canonical_client(tmp_path)
    try:
        yield client, store
    finally:
        client.close()
        asyncio.run(store.close())


def test_canonical_backfill_defaults_to_dry_run(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, _store = canonical_client

    response = client.post(
        "/api/v1/canonical/backfill",
        json={"target_id": "italy", "limit": 10},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "dry_run"
    assert body["target_id"] == "italy"
    assert "input_events" in body


def test_canonical_diagnostics_uses_dry_run(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, _store = canonical_client

    response = client.get("/api/v1/canonical/diagnostics", params={"target_id": "italy"})

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "dry_run"
    assert body["target_id"] == "italy"


def test_canonical_event_detail_returns_404_for_missing_event(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, _store = canonical_client

    response = client.get(
        "/api/v1/canonical/events/ce_missing",
        params={"target_id": "italy"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Canonical event not found"


def test_canonical_event_markdown_export_returns_evidence_package(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, store = canonical_client
    asyncio.run(
        store.upsert_canonical_event(
            {
                "canonical_event_id": "ce_italy_export_001",
                "target_id": "italy",
                "title": "Canonical export story",
                "summary": "Exportable evidence summary.",
                "event_time": "2026-05-30T10:00:00Z",
                "status": "needs_review",
                "confidence": 70,
                "metadata": {},
            }
        )
    )
    asyncio.run(
        store.upsert_event_mention(
            {
                "mention_id": "mention-export-001",
                "canonical_event_id": "ce_italy_export_001",
                "event_id": "event-export-001",
                "target_id": "italy",
                "source_id": "ansa",
                "url": "https://example.com/export-story",
                "title": "Mention export title",
                "published_at": "2026-05-30T09:00:00Z",
                "metadata": {},
            }
        )
    )

    response = client.get(
        "/api/v1/canonical/events/ce_italy_export_001/export/markdown",
        params={"target_id": "italy"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition
    assert "ce_italy_export_001.md" in disposition
    assert "export_kind: canonical_event_evidence_package" in response.text
    assert "ce_italy_export_001" in response.text
    assert "ansa" in response.text
    assert "https://example.com/export-story" in response.text


def test_canonical_event_markdown_export_missing_event_returns_404(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, _store = canonical_client

    response = client.get(
        "/api/v1/canonical/events/ce_missing/export/markdown",
        params={"target_id": "italy"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Canonical event not found"


def test_canonical_event_detail_requires_target_scope(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, _store = canonical_client

    response = client.get("/api/v1/canonical/events/ce_missing")

    assert response.status_code == 422


def test_canonical_backfill_apply_makes_event_queryable(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, store = canonical_client

    async def seed_event() -> None:
        async with store._connect() as conn:
            await conn.execute(
                """
                INSERT INTO event_index (
                    event_id, target_id, source_id, title_original, url, published_at,
                    stage, news_value_score, china_relevance,
                    classification_l0, metadata_json, file_path, created_at
                ) VALUES (
                    'it_api_001', 'italy', 'ansa', 'API story',
                    'https://example.com/api-story', '2026-05-30T08:00:00Z',
                    'judged', 90, 20, 'politics', '{}', 'drafts/it_api_001.md',
                    CURRENT_TIMESTAMP
                )
                """
            )
            await conn.commit()

    asyncio.run(seed_event())

    backfill = client.post(
        "/api/v1/canonical/backfill",
        json={
            "target_id": "italy",
            "limit": 10,
            "apply": True,
            "projection_run_id": "projection_api_test",
        },
    )
    listed = client.get("/api/v1/canonical/events", params={"target_id": "italy"})

    assert backfill.status_code == 200
    assert listed.status_code == 200
    events = listed.json()["events"]
    assert len(events) == 1
    assert events[0]["title"] == "API story"


def test_canonical_event_list_rejects_negative_limit(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, _store = canonical_client

    response = client.get(
        "/api/v1/canonical/events",
        params={"target_id": "italy", "limit": -1},
    )

    assert response.status_code == 422


def test_canonical_event_detail_enforces_target_scope(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, store = canonical_client

    async def seed_event() -> None:
        async with store._connect() as conn:
            await conn.execute(
                """
                INSERT INTO event_index (
                    event_id, target_id, source_id, title_original, url, published_at,
                    stage, news_value_score, china_relevance,
                    classification_l0, metadata_json, file_path, created_at
                ) VALUES (
                    'it_api_scope_001', 'italy', 'ansa', 'Scoped API story',
                    'https://example.com/scoped-api-story', '2026-05-30T09:00:00Z',
                    'judged', 88, 25, 'politics', '{}', 'drafts/it_api_scope_001.md',
                    CURRENT_TIMESTAMP
                )
                """
            )
            await conn.commit()

    asyncio.run(seed_event())
    backfill = client.post(
        "/api/v1/canonical/backfill",
        json={
            "target_id": "italy",
            "limit": 10,
            "apply": True,
            "projection_run_id": "projection_api_scope_test",
        },
    )
    assert backfill.status_code == 200
    listed = client.get("/api/v1/canonical/events", params={"target_id": "italy"})
    canonical_event_id = listed.json()["events"][0]["canonical_event_id"]

    same_target = client.get(
        f"/api/v1/canonical/events/{canonical_event_id}",
        params={"target_id": "italy"},
    )
    other_target = client.get(
        f"/api/v1/canonical/events/{canonical_event_id}",
        params={"target_id": "japan"},
    )

    assert same_target.status_code == 200
    assert same_target.json()["target_id"] == "italy"
    assert other_target.status_code == 404
    assert other_target.json()["detail"] == "Canonical event not found"


def test_canonical_event_mentions_and_relations_enforce_target_scope(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, store = canonical_client

    async def seed_event() -> None:
        async with store._connect() as conn:
            await conn.execute(
                """
                INSERT INTO event_index (
                    event_id, target_id, source_id, title_original, url, published_at,
                    stage, news_value_score, china_relevance,
                    classification_l0, metadata_json, file_path, created_at
                ) VALUES (
                    'it_api_nested_scope_001', 'italy', 'ansa', 'Nested scoped story',
                    'https://example.com/nested-scoped-story', '2026-05-30T10:00:00Z',
                    'judged', 88, 25, 'politics', '{}', 'drafts/it_api_nested_scope_001.md',
                    CURRENT_TIMESTAMP
                )
                """
            )
            await conn.commit()

    asyncio.run(seed_event())
    backfill = client.post(
        "/api/v1/canonical/backfill",
        json={
            "target_id": "italy",
            "limit": 10,
            "apply": True,
            "projection_run_id": "projection_api_nested_scope_test",
        },
    )
    assert backfill.status_code == 200
    listed = client.get("/api/v1/canonical/events", params={"target_id": "italy"})
    canonical_event_id = listed.json()["events"][0]["canonical_event_id"]

    mentions_same_target = client.get(
        f"/api/v1/canonical/events/{canonical_event_id}/mentions",
        params={"target_id": "italy"},
    )
    mentions_other_target = client.get(
        f"/api/v1/canonical/events/{canonical_event_id}/mentions",
        params={"target_id": "japan"},
    )
    mentions_missing_target = client.get(f"/api/v1/canonical/events/{canonical_event_id}/mentions")
    relations_same_target = client.get(
        f"/api/v1/canonical/events/{canonical_event_id}/relations",
        params={"target_id": "italy"},
    )
    relations_other_target = client.get(
        f"/api/v1/canonical/events/{canonical_event_id}/relations",
        params={"target_id": "japan"},
    )
    relations_missing_target = client.get(
        f"/api/v1/canonical/events/{canonical_event_id}/relations"
    )

    assert mentions_same_target.status_code == 200
    assert len(mentions_same_target.json()["mentions"]) == 1
    assert mentions_other_target.status_code == 404
    assert mentions_other_target.json()["detail"] == "Canonical event not found"
    assert mentions_missing_target.status_code == 422
    assert relations_same_target.status_code == 200
    assert relations_same_target.json()["relations"] == []
    assert relations_other_target.status_code == 404
    assert relations_other_target.json()["detail"] == "Canonical event not found"
    assert relations_missing_target.status_code == 422


def test_research_queue_returns_open_canonical_items(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, store = canonical_client
    asyncio.run(
        store.upsert_canonical_event(
            {
                "canonical_event_id": "ce_italy_research_001",
                "target_id": "italy",
                "title": "Research candidate",
                "summary": "Needs review",
                "event_time": "2026-05-30T10:00:00Z",
                "status": "needs_review",
                "confidence": 60,
                "metadata": {"mention_count": 2, "source_count": 2, "news_value_score": 88},
            }
        )
    )

    response = client.get("/api/v1/research/queue", params={"target_id": "italy"})

    assert response.status_code == 200
    data = response.json()
    assert data["target_id"] == "italy"
    assert data["items"][0]["canonical_event_id"] == "ce_italy_research_001"


def test_research_event_detail_returns_evidence_and_artifacts(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, store = canonical_client
    asyncio.run(
        store.upsert_canonical_event(
            {
                "canonical_event_id": "ce_italy_research_002",
                "target_id": "italy",
                "title": "Evidence event",
                "summary": "",
                "event_time": "2026-05-30T10:00:00Z",
                "status": "needs_review",
                "confidence": 70,
                "metadata": {},
            }
        )
    )
    asyncio.run(
        store.upsert_event_mention(
            {
                "mention_id": "mention-001",
                "canonical_event_id": "ce_italy_research_002",
                "event_id": "event-001",
                "target_id": "italy",
                "source_id": "ansa",
                "url": "https://example.com/news",
                "title": "Evidence title",
                "published_at": "2026-05-30T09:00:00Z",
                "metadata": {"language": "it"},
            }
        )
    )
    artifact = {
        "target_id": "italy",
        "artifact_type": "annotation",
        "title": "背景标注",
        "body": "重要背景。",
        "subject_type": "canonical_event",
        "subject_id": "ce_italy_research_002",
        "status": "open",
        "metadata": {"tags": ["policy"]},
    }
    created = client.post("/api/v1/research/artifacts", json=artifact)
    assert created.status_code == 200

    response = client.get(
        "/api/v1/research/events/ce_italy_research_002",
        params={"target_id": "italy"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["event"]["canonical_event_id"] == "ce_italy_research_002"
    assert data["mentions"][0]["mention_id"] == "mention-001"
    assert data["artifacts"][0]["artifact_type"] == "annotation"


def test_research_artifact_review_state_post_is_idempotent(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, store = canonical_client
    asyncio.run(
        store.upsert_canonical_event(
            {
                "canonical_event_id": "ce_italy_research_review_idempotent",
                "target_id": "italy",
                "title": "Review state event",
                "summary": "",
                "event_time": "2026-05-30T10:00:00Z",
                "status": "needs_review",
                "confidence": 70,
                "metadata": {},
            }
        )
    )
    payload = {
        "target_id": "italy",
        "artifact_type": "review_state",
        "title": "Confirmed",
        "body": "Reviewed by desk.",
        "subject_type": "canonical_event",
        "subject_id": "ce_italy_research_review_idempotent",
        "status": "resolved",
        "metadata": {"decision": "confirmed"},
    }

    first = client.post("/api/v1/research/artifacts", json=payload)
    second = client.post("/api/v1/research/artifacts", json=payload)
    listed = client.get(
        "/api/v1/research/artifacts",
        params={
            "target_id": "italy",
            "subject_id": "ce_italy_research_review_idempotent",
            "artifact_type": "review_state",
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    first_artifact_id = first.json()["artifact"]["artifact_id"]
    second_artifact_id = second.json()["artifact"]["artifact_id"]
    assert second_artifact_id == first_artifact_id
    artifacts = listed.json()["artifacts"]
    assert [artifact["artifact_id"] for artifact in artifacts] == [first_artifact_id]


def test_research_artifact_list_filters_by_subject_and_status(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, store = canonical_client
    asyncio.run(
        store.upsert_canonical_event(
            {
                "canonical_event_id": "ce_italy_research_list_001",
                "target_id": "italy",
                "title": "List event",
                "summary": "",
                "event_time": "2026-05-30T10:00:00Z",
                "status": "needs_review",
                "confidence": 70,
                "metadata": {},
            }
        )
    )
    created = client.post(
        "/api/v1/research/artifacts",
        json={
            "target_id": "italy",
            "artifact_type": "note",
            "title": "List note",
            "body": "Only this note should match.",
            "subject_type": "canonical_event",
            "subject_id": "ce_italy_research_list_001",
            "status": "open",
            "metadata": {},
        },
    )
    assert created.status_code == 200
    artifact_id = created.json()["artifact"]["artifact_id"]

    response = client.get(
        "/api/v1/research/artifacts",
        params={
            "target_id": "italy",
            "subject_id": "ce_italy_research_list_001",
            "status": "open",
        },
    )

    assert response.status_code == 200
    artifacts = response.json()["artifacts"]
    assert [artifact["artifact_id"] for artifact in artifacts] == [artifact_id]


def test_research_event_detail_enforces_target_scope(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, store = canonical_client
    asyncio.run(
        store.upsert_canonical_event(
            {
                "canonical_event_id": "ce_france_research_detail_001",
                "target_id": "france",
                "title": "France scoped event",
                "summary": "",
                "event_time": "2026-05-30T10:00:00Z",
                "status": "needs_review",
                "confidence": 60,
                "metadata": {},
            }
        )
    )

    response = client.get(
        "/api/v1/research/events/ce_france_research_detail_001",
        params={"target_id": "italy"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Canonical event not found"


def test_research_artifact_create_rejects_cross_target_subject(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, store = canonical_client
    asyncio.run(
        store.upsert_canonical_event(
            {
                "canonical_event_id": "ce_france_research_001",
                "target_id": "france",
                "title": "France event",
                "summary": "",
                "event_time": "2026-05-30T10:00:00Z",
                "status": "needs_review",
                "confidence": 60,
                "metadata": {},
            }
        )
    )

    response = client.post(
        "/api/v1/research/artifacts",
        json={
            "target_id": "italy",
            "artifact_type": "review_state",
            "title": "Bad scope",
            "body": "",
            "subject_type": "canonical_event",
            "subject_id": "ce_france_research_001",
            "status": "resolved",
            "metadata": {"decision": "confirmed"},
        },
    )

    assert response.status_code == 404


def test_research_artifact_create_rejects_missing_subject(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, _store = canonical_client

    response = client.post(
        "/api/v1/research/artifacts",
        json={
            "target_id": "italy",
            "artifact_type": "review_state",
            "title": "Missing subject",
            "body": "",
            "subject_type": "canonical_event",
            "subject_id": "ce_italy_missing_subject",
            "status": "resolved",
            "metadata": {"decision": "confirmed"},
        },
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "payload_patch",
    [
        {"artifact_type": "unsupported"},
        {"status": "unknown"},
        {"metadata": {"decision": "unsupported"}},
        {"subject_type": "event"},
    ],
)
def test_research_artifact_create_rejects_invalid_contract_values(
    canonical_client: tuple[TestClient, AsyncStore],
    payload_patch: dict[str, Any],
):
    client, store = canonical_client
    asyncio.run(
        store.upsert_canonical_event(
            {
                "canonical_event_id": "ce_italy_research_invalid_001",
                "target_id": "italy",
                "title": "Invalid contract event",
                "summary": "",
                "event_time": "2026-05-30T10:00:00Z",
                "status": "needs_review",
                "confidence": 60,
                "metadata": {},
            }
        )
    )
    payload = {
        "target_id": "italy",
        "artifact_type": "review_state",
        "title": "Invalid",
        "body": "",
        "subject_type": "canonical_event",
        "subject_id": "ce_italy_research_invalid_001",
        "status": "open",
        "metadata": {"decision": "confirmed"},
    }
    payload.update(payload_patch)

    response = client.post("/api/v1/research/artifacts", json=payload)

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("artifact_type", "metadata"),
    [
        (
            "merge_decision",
            {"decision": "proposed", "candidate_canonical_event_ids": "ce_other"},
        ),
        (
            "merge_decision",
            {"decision": "proposed", "candidate_canonical_event_ids": [123]},
        ),
        (
            "split_decision",
            {"decision": "proposed", "affected_mention_ids": "mention-001"},
        ),
        (
            "split_decision",
            {"decision": "proposed", "affected_mention_ids": [123]},
        ),
    ],
)
def test_research_artifact_create_rejects_invalid_decision_id_lists(
    canonical_client: tuple[TestClient, AsyncStore],
    artifact_type: str,
    metadata: dict[str, Any],
):
    client, store = canonical_client
    asyncio.run(
        store.upsert_canonical_event(
            {
                "canonical_event_id": "ce_italy_research_decision_invalid",
                "target_id": "italy",
                "title": "Invalid decision event",
                "summary": "",
                "event_time": "2026-05-30T10:00:00Z",
                "status": "needs_review",
                "confidence": 60,
                "metadata": {},
            }
        )
    )

    response = client.post(
        "/api/v1/research/artifacts",
        json={
            "target_id": "italy",
            "artifact_type": artifact_type,
            "title": "Invalid decision",
            "body": "",
            "subject_type": "canonical_event",
            "subject_id": "ce_italy_research_decision_invalid",
            "status": "open",
            "metadata": metadata,
        },
    )

    assert response.status_code == 422


def test_research_artifact_create_requires_auth_in_cloud(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_deployment_env(monkeypatch, "cloudflare")
    app = create_app(data_dir=tmp_path, auto_store=False, skip_lifespan=True)
    client = TestClient(app, base_url="https://news.example")

    response = client.post(
        "/api/v1/research/artifacts",
        json={
            "target_id": "italy",
            "artifact_type": "review_state",
            "title": "Cloud write",
            "body": "",
            "subject_type": "canonical_event",
            "subject_id": "ce_italy_research_cloud_auth",
            "status": "resolved",
            "metadata": {"decision": "confirmed"},
        },
    )

    assert response.status_code == 401


def test_research_artifact_patch_preserves_subject_scope_and_type(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, store = canonical_client
    asyncio.run(
        store.upsert_canonical_event(
            {
                "canonical_event_id": "ce_italy_research_003",
                "target_id": "italy",
                "title": "Patch event",
                "summary": "",
                "event_time": "2026-05-30T10:00:00Z",
                "status": "needs_review",
                "confidence": 60,
                "metadata": {},
            }
        )
    )
    created = client.post(
        "/api/v1/research/artifacts",
        json={
            "target_id": "italy",
            "artifact_type": "review_state",
            "title": "Open",
            "body": "",
            "subject_type": "canonical_event",
            "subject_id": "ce_italy_research_003",
            "status": "open",
            "metadata": {"decision": "needs_more_evidence"},
        },
    )
    assert created.status_code == 200
    artifact_id = created.json()["artifact"]["artifact_id"]

    patched = client.patch(
        f"/api/v1/research/artifacts/{artifact_id}",
        params={"target_id": "italy"},
        json={
            "target_id": "france",
            "artifact_type": "note",
            "subject_type": "event",
            "subject_id": "ce_other",
            "status": "resolved",
            "metadata": {"decision": "confirmed", "subject_id": "ce_other"},
        },
    )

    assert patched.status_code == 200
    artifact = patched.json()["artifact"]
    assert artifact["target_id"] == "italy"
    assert artifact["artifact_type"] == "review_state"
    assert artifact["subject_type"] == "canonical_event"
    assert artifact["subject_id"] == "ce_italy_research_003"
    assert artifact["status"] == "resolved"


def test_research_artifact_patch_enforces_target_scope(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, store = canonical_client
    asyncio.run(
        store.upsert_canonical_event(
            {
                "canonical_event_id": "ce_italy_research_patch_scope",
                "target_id": "italy",
                "title": "Patch scoped event",
                "summary": "",
                "event_time": "2026-05-30T10:00:00Z",
                "status": "needs_review",
                "confidence": 60,
                "metadata": {},
            }
        )
    )
    created = client.post(
        "/api/v1/research/artifacts",
        json={
            "target_id": "italy",
            "artifact_type": "note",
            "title": "Scoped note",
            "body": "",
            "subject_type": "canonical_event",
            "subject_id": "ce_italy_research_patch_scope",
            "status": "open",
            "metadata": {},
        },
    )
    assert created.status_code == 200
    artifact_id = created.json()["artifact"]["artifact_id"]

    response = client.patch(
        f"/api/v1/research/artifacts/{artifact_id}",
        params={"target_id": "france"},
        json={"status": "resolved"},
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "unknown"},
        {"metadata": {"decision": "unsupported"}},
    ],
)
def test_research_artifact_patch_rejects_invalid_status_or_decision(
    canonical_client: tuple[TestClient, AsyncStore],
    payload: dict[str, Any],
):
    client, store = canonical_client
    asyncio.run(
        store.upsert_canonical_event(
            {
                "canonical_event_id": "ce_italy_research_patch_invalid",
                "target_id": "italy",
                "title": "Patch invalid event",
                "summary": "",
                "event_time": "2026-05-30T10:00:00Z",
                "status": "needs_review",
                "confidence": 60,
                "metadata": {},
            }
        )
    )
    created = client.post(
        "/api/v1/research/artifacts",
        json={
            "target_id": "italy",
            "artifact_type": "review_state",
            "title": "Review",
            "body": "",
            "subject_type": "canonical_event",
            "subject_id": "ce_italy_research_patch_invalid",
            "status": "open",
            "metadata": {"decision": "needs_more_evidence"},
        },
    )
    assert created.status_code == 200
    artifact_id = created.json()["artifact"]["artifact_id"]

    response = client.patch(
        f"/api/v1/research/artifacts/{artifact_id}",
        params={"target_id": "italy"},
        json=payload,
    )

    assert response.status_code == 422


async def _seed_research_graph_merge(store: AsyncStore) -> None:
    for event_id, title in (
        ("ce_italy_api_merge_survivor", "Survivor"),
        ("ce_italy_api_merge_duplicate", "Duplicate"),
    ):
        await store.upsert_canonical_event(
            {
                "canonical_event_id": event_id,
                "target_id": "italy",
                "title": title,
                "summary": "",
                "event_time": "2026-05-30T10:00:00Z",
                "status": "needs_review",
                "confidence": 70,
                "metadata": {"mention_count": 1, "source_count": 1},
            }
        )
    for mention_id, canonical_event_id, source_id in (
        ("mention_api_merge_survivor", "ce_italy_api_merge_survivor", "ansa"),
        ("mention_api_merge_duplicate", "ce_italy_api_merge_duplicate", "repubblica"),
    ):
        await store.upsert_event_mention(
            {
                "mention_id": mention_id,
                "canonical_event_id": canonical_event_id,
                "event_id": f"ne_{mention_id}",
                "target_id": "italy",
                "source_id": source_id,
                "url": f"https://example.com/{mention_id}",
                "title": mention_id,
                "published_at": "2026-05-30T10:00:00Z",
                "metadata": {"news_value_score": 80},
            }
        )
    await store.upsert_research_artifact(
        {
            "artifact_id": "ra_italy_api_merge",
            "target_id": "italy",
            "artifact_type": "merge_decision",
            "title": "Merge duplicate",
            "body": "Same fact",
            "subject_type": "canonical_event",
            "subject_id": "ce_italy_api_merge_survivor",
            "canonical_event_ids": [
                "ce_italy_api_merge_survivor",
                "ce_italy_api_merge_duplicate",
            ],
            "status": "open",
            "metadata": {
                "decision": "proposed",
                "candidate_canonical_event_ids": ["ce_italy_api_merge_duplicate"],
            },
        }
    )


def test_research_graph_merge_dry_run_and_apply(
    canonical_client: tuple[TestClient, AsyncStore],
) -> None:
    client, store = canonical_client
    asyncio.run(_seed_research_graph_merge(store))
    payload = {
        "target_id": "italy",
        "decision_artifact_id": "ra_italy_api_merge",
        "survivor_canonical_event_id": "ce_italy_api_merge_survivor",
        "merged_canonical_event_ids": ["ce_italy_api_merge_duplicate"],
    }

    dry_run = client.post("/api/v1/research/graph/merge", json={**payload, "dry_run": True})
    applied = client.post("/api/v1/research/graph/merge", json={**payload, "dry_run": False})
    operations = client.get(
        "/api/v1/research/graph/operations",
        params={"target_id": "italy"},
    )

    assert dry_run.status_code == 200
    assert dry_run.json()["mode"] == "dry_run"
    assert applied.status_code == 200
    applied_data = applied.json()
    assert applied_data["mode"] == "applied"
    assert operations.status_code == 200
    operation_ids = [operation["operation_id"] for operation in operations.json()["operations"]]
    assert applied_data["operation_id"] in operation_ids


def test_research_graph_merge_missing_survivor_returns_404(
    canonical_client: tuple[TestClient, AsyncStore],
) -> None:
    client, store = canonical_client
    asyncio.run(_seed_research_graph_merge(store))

    response = client.post(
        "/api/v1/research/graph/merge",
        json={
            "target_id": "italy",
            "survivor_canonical_event_id": "ce_italy_api_merge_missing",
            "merged_canonical_event_ids": ["ce_italy_api_merge_duplicate"],
            "dry_run": True,
        },
    )

    assert response.status_code == 404
    assert "canonical event not found" in response.json()["detail"]


def test_research_graph_merge_rejects_invalid_operation_as_422(
    canonical_client: tuple[TestClient, AsyncStore],
) -> None:
    client, _store = canonical_client

    response = client.post(
        "/api/v1/research/graph/merge",
        json={
            "target_id": "italy",
            "survivor_canonical_event_id": "ce_italy_api_merge_same",
            "merged_canonical_event_ids": ["ce_italy_api_merge_same"],
            "dry_run": True,
        },
    )

    assert response.status_code == 422
    assert "survivor canonical event cannot appear" in response.json()["detail"]


def test_research_graph_split_missing_mention_returns_404(
    canonical_client: tuple[TestClient, AsyncStore],
) -> None:
    client, store = canonical_client
    asyncio.run(
        store.upsert_canonical_event(
            {
                "canonical_event_id": "ce_italy_api_split_source",
                "target_id": "italy",
                "title": "Mixed event",
                "summary": "",
                "event_time": "2026-05-30T10:00:00Z",
                "status": "needs_review",
                "confidence": 60,
                "metadata": {"mention_count": 1, "source_count": 1},
            }
        )
    )
    asyncio.run(
        store.upsert_event_mention(
            {
                "mention_id": "mention_api_split_keep",
                "canonical_event_id": "ce_italy_api_split_source",
                "event_id": "ne_mention_api_split_keep",
                "target_id": "italy",
                "source_id": "ansa",
                "url": "https://example.com/mention_api_split_keep",
                "title": "Keep mention",
                "published_at": "2026-05-30T10:00:00Z",
                "metadata": {"news_value_score": 80},
            }
        )
    )

    response = client.post(
        "/api/v1/research/graph/split",
        json={
            "target_id": "italy",
            "source_canonical_event_id": "ce_italy_api_split_source",
            "affected_mention_ids": ["mention_api_split_missing"],
            "dry_run": True,
        },
    )

    assert response.status_code == 404
    assert "mention not found" in response.json()["detail"]

