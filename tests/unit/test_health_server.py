"""Phase 18 — HealthServer 测试：/health HTTP 端点。"""

from __future__ import annotations

import json
from urllib.request import urlopen

from news_sentry.core.health_server import (
    _collect_health,
    start_health_server,
    stop_health_server,
)


class TestCollectHealth:
    """_collect_health() 返回结构测试。"""

    def test_returns_ok_status(self) -> None:
        health = _collect_health()
        assert health["status"] == "ok"
        assert "timestamp" in health

    def test_has_process_info(self) -> None:
        health = _collect_health()
        assert "pid" in health["process"]
        assert "data_dir" in health["process"]

    def test_has_system_info(self) -> None:
        health = _collect_health()
        assert "disk_total_gb" in health["system"]
        assert "disk_pct" in health["system"]

    def test_has_integrations(self) -> None:
        health = _collect_health()
        assert "feishu_configured" in health["integrations"]
        assert "smtp_configured" in health["integrations"]
        assert "telegram_configured" in health["integrations"]

    def test_recent_runs_is_list(self) -> None:
        health = _collect_health()
        assert isinstance(health["recent_runs"], list)


class TestHealthServerHTTP:
    """HTTP 端点集成测试。"""

    def test_health_endpoint_returns_200(self) -> None:
        server = start_health_server(port=0)  # random port
        port = server.server_address[1]
        try:
            resp = urlopen(f"http://127.0.0.1:{port}/health")
            assert resp.status == 200
            body = json.loads(resp.read())
            assert body["status"] == "ok"
        finally:
            stop_health_server(server)

    def test_non_health_path_returns_404(self) -> None:
        server = start_health_server(port=0)
        port = server.server_address[1]
        try:
            try:
                urlopen(f"http://127.0.0.1:{port}/other")
                raise AssertionError("Expected error")
            except Exception as e:
                assert "404" in str(e) or "Error" in str(e)
        finally:
            stop_health_server(server)
