"""Phase 6: Operations & Collector API E2E tests.

Covers collector status/config/start/stop, AI enhancement/translation status,
run logs, trigger pipeline, and data status endpoint.
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.e2e

_TEST_TARGET = "e2e-test-target"


# ── Collector Status & Config ─────────────────────────────────────────────


class TestCollector:
    def test_collector_status(self, e2e_client: httpx.Client, auth_header: dict) -> None:
        resp = e2e_client.get("/api/v1/collector/status", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert "enabled" in data
        assert "running" in data

    def test_collector_config(self, e2e_client: httpx.Client, auth_header: dict) -> None:
        resp = e2e_client.get("/api/v1/collector/config", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert "enabled" in data
        assert "target_ids" in data

    def test_collector_config_persists(
        self, e2e_client: httpx.Client, auth_header: dict
    ) -> None:
        """Update collector config and verify it persists."""
        resp = e2e_client.put(
            "/api/v1/collector/config",
            json={"interval_minutes": 5, "stage": "collect"},
            headers=auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("interval_minutes") == 5

    def test_collector_diagnostics(self, e2e_client: httpx.Client, auth_header: dict) -> None:
        resp = e2e_client.get("/api/v1/collector/diagnostics", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert "collector" in data or "data_dir_exists" in data

    def test_collector_start_stop(
        self, e2e_client: httpx.Client, auth_header: dict
    ) -> None:
        # Stop
        resp = e2e_client.post("/api/v1/collector/stop", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("enabled") is False

        # Start
        resp = e2e_client.post("/api/v1/collector/start", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("enabled") is True


# ── AI Enhancement & Translation ──────────────────────────────────────────


class TestAiEnhancement:
    def test_ai_enrichment_status(
        self, e2e_client: httpx.Client, auth_header: dict
    ) -> None:
        resp = e2e_client.get(
            "/api/v1/ai/enrichment/status", headers=auth_header
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "enabled" in data

    def test_ai_translation_status(
        self, e2e_client: httpx.Client, auth_header: dict
    ) -> None:
        resp = e2e_client.get(
            "/api/v1/ai/translation/status", headers=auth_header
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "enabled" in data

    def test_ai_enrichment_dry_run(
        self, e2e_client: httpx.Client, auth_header: dict
    ) -> None:
        """Dry run should return plan without calling any AI provider."""
        resp = e2e_client.post(
            "/api/v1/ai/enrichment/run",
            params={"dry_run": True},
            headers=auth_header,
        )
        assert resp.status_code == 200

    def test_ai_translation_dry_run(
        self, e2e_client: httpx.Client, auth_header: dict
    ) -> None:
        resp = e2e_client.post(
            "/api/v1/ai/translation/run",
            params={"dry_run": True, "target_id": _TEST_TARGET},
            headers=auth_header,
        )
        assert resp.status_code == 200


# ── Data Status ───────────────────────────────────────────────────────────


class TestDataStatus:
    def test_data_status(self, e2e_client: httpx.Client, auth_header: dict) -> None:
        resp = e2e_client.get("/api/v1/status", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert "data_dir" in data
        assert "deployment_env" in data


# ── Run Logs ──────────────────────────────────────────────────────────────


class TestRunLogs:
    def test_list_runs(self, e2e_client: httpx.Client, auth_header: dict) -> None:
        resp = e2e_client.get(
            "/api/v1/runs",
            params={"target_id": _TEST_TARGET, "limit": 5},
            headers=auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "runs" in data

    def test_active_run(self, e2e_client: httpx.Client, auth_header: dict) -> None:
        resp = e2e_client.get(
            "/api/v1/runs/active",
            params={"target_id": _TEST_TARGET},
            headers=auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "active" in data

    def test_trigger_run(
        self, e2e_client: httpx.Client, auth_header: dict
    ) -> None:
        """Trigger a pipeline run (should return triggered status)."""
        resp = e2e_client.post(
            "/api/v1/runs/trigger",
            params={"target_id": _TEST_TARGET, "stage": "all"},
            headers=auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "triggered"
        assert "run_id" in data

    def test_config_reload(
        self, e2e_client: httpx.Client, auth_header: dict
    ) -> None:
        resp = e2e_client.post("/api/v1/config/reload", headers=auth_header)
        assert resp.status_code == 200
        assert resp.json().get("status") == "ok"

    def test_trigger_run_without_auth_returns_401(
        self, e2e_client: httpx.Client
    ) -> None:
        resp = e2e_client.post(
            "/api/v1/runs/trigger",
            params={"target_id": _TEST_TARGET},
        )
        assert resp.status_code == 401
