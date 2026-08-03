from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from tools.cloudflare_collect_diagnostic import (
    CollectDiagnosticError,
    build_diagnostic,
)

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/cloudflare-collect-diagnostic.yml"


def _d1_result(details: dict[str, object]) -> list[dict[str, object]]:
    return [
        {
            "success": True,
            "results": [
                {
                    "value": json.dumps(
                        {
                            "status": "error",
                            "runId": "collect-cycle:1",
                            "details": details,
                        }
                    ),
                    "updated_at": "2026-08-03T01:00:24Z",
                }
            ],
        }
    ]


def test_collect_diagnostic_extracts_bounded_runtime_failure() -> None:
    diagnostic = build_diagnostic(
        _d1_result(
            {
                "deploy_commit": "a" * 40,
                "worker_version": "worker-version-1",
                "environment": "production",
                "container_start": "auto_fetch",
                "http_status": 500,
                "container_timeout_ms": 480_000,
                "body": "Failed to start container: port 8000 is not ready",
                "collect_batch": {"selected_target_ids": ["france"]},
            }
        )
    )

    assert diagnostic["status"] == "error"
    assert diagnostic["deployment"]["worker_version"] == "worker-version-1"
    assert diagnostic["container"] == {
        "start": "auto_fetch",
        "http_status": 500,
        "timeout_ms": 480_000,
        "retryable_error": None,
        "error": "Failed to start container: port 8000 is not ready",
    }
    assert diagnostic["selected_target_ids"] == ["france"]
    assert diagnostic["target_results"] == []


def test_collect_diagnostic_extracts_sanitized_target_results() -> None:
    diagnostic = build_diagnostic(
        _d1_result(
            {
                "body": {
                    "error": "target collection failed",
                    "summary": {
                        "target_results": [
                            {
                                "target_id": "china-watch-en",
                                "status": "error",
                                "events_collected": 0,
                                "import_events_count": 0,
                                "reason": "target_database_missing",
                            }
                        ]
                    },
                }
            }
        )
    )

    assert diagnostic["target_results"] == [
        {
            "target_id": "china-watch-en",
            "status": "error",
            "events_collected": 0,
            "import_events_count": 0,
            "reason": "target_database_missing",
        }
    ]


def test_collect_diagnostic_redacts_credentials_and_truncates_error() -> None:
    sensitive_values = [
        "fixture-token-value",
        "fixture-bearer-value",
        "fixture-cloudflare-value",
        "fixture-deepseek-value",
        "fixture-basic-value",
        "fixture-json-key-value",
        "fixture-json-auth-value",
    ]
    diagnostic = build_diagnostic(
        _d1_result(
            {
                "message": (
                    f"token={sensitive_values[0]} "
                    f"Authorization: Bearer {sensitive_values[1]} "
                    f"CLOUDFLARE_API_TOKEN={sensitive_values[2]} "
                    f'DEEPSEEK_API_KEY="{sensitive_values[3]}" '
                    f"Basic {sensitive_values[4]} "
                    f'"OPENROUTER_API_KEY": "{sensitive_values[5]}" '
                    f'"Authorization": "Bearer {sensitive_values[6]}" '
                    "https://user:pass@example.test/path "
                    + "x" * 900
                )
            }
        )
    )
    serialized = json.dumps(diagnostic)

    assert all(sensitive_value not in serialized for sensitive_value in sensitive_values)
    assert "user:pass" not in serialized
    assert "<redacted>" in diagnostic["container"]["error"]
    assert len(diagnostic["container"]["error"]) == 500


def test_collect_diagnostic_rejects_missing_or_malformed_rows() -> None:
    with pytest.raises(CollectDiagnosticError, match="exactly one row"):
        build_diagnostic([{"success": True, "results": []}])
    with pytest.raises(CollectDiagnosticError, match="not valid JSON"):
        build_diagnostic(
            [{"success": True, "results": [{"value": "{", "updated_at": "now"}]}]
        )


def test_collect_diagnostic_workflow_is_read_only_and_uploads_only_sanitized_output() -> None:
    workflow = yaml.load(
        WORKFLOW.read_text(),
        Loader=yaml.BaseLoader,  # noqa: S506 - preserves GitHub's `on` key.
    )
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["collect-diagnostic"]
    assert job["environment"] == "production"
    assert job["timeout-minutes"] == "5"
    steps = {step["name"]: step for step in job["steps"] if "name" in step}
    query = steps["Query and sanitize latest collect continuity"]["run"]
    assert "SELECT value, updated_at FROM ops_state" in query
    assert "INSERT" not in query
    assert "UPDATE" not in query
    assert "DELETE" not in query
    assert "tools/cloudflare_collect_diagnostic.py" in query
    query_env = steps["Query and sanitize latest collect continuity"]["env"]
    assert "CLOUDFLARE_API_TOKEN" in query_env
    assert "CLOUDFLARE_API_KEY" not in query_env
    assert "CLOUDFLARE_EMAIL" not in query_env
    artifact = steps["Upload sanitized collect diagnostic"]
    artifact_path = artifact["with"]["path"]
    assert artifact_path.endswith("/news-sentry-collect-diagnostic.json")
    assert "raw" not in artifact_path
