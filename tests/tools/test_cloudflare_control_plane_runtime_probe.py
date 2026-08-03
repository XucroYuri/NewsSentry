from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from tools.cloudflare_control_plane_runtime_probe import (
    ControlPlaneProbeError,
    build_receipt,
)

COMMIT = "a" * 40
NOW = datetime(2026, 8, 3, 0, 0, tzinfo=UTC)


def _metadata() -> dict[str, str]:
    return {
        "environment": "production",
        "deployed_commit": COMMIT,
        "deployed_at": "2026-08-02T22:07:30Z",
        "worker_version": "version-1",
        "deployment_id": "deployment-1",
    }


def _versions() -> list[dict[str, object]]:
    return [
        {
            "id": "version-1",
            "annotations": {
                "workers/tag": COMMIT,
                "workers/message": f"NewsSentry production {COMMIT}",
            },
        }
    ]


def _deployments() -> dict[str, object]:
    return {
        "id": "deployment-1",
        "versions": [{"version_id": "version-1", "percentage": 100.0}],
    }


def _d1_row(**overrides: object) -> dict[str, object]:
    collect = {
        "status": "ok",
        "runId": "collect-1",
        "details": {
            "environment": "production",
            "deploy_commit": COMMIT,
            "worker_version": "version-1",
            "scheduler_mode": "shadow",
            "worker_native_collect_enabled": False,
            "collection_authoritative": False,
            "container_configured": True,
            "queue_configured": True,
            "dlq_configured": True,
            "artifacts_configured": True,
            "collect_batch": {"selected_target_ids": ["japan"]},
        },
    }
    row: dict[str, object] = {
        "collect_value": json.dumps(collect),
        "collect_updated_at": "2026-08-02T23:45:00Z",
        "total_events": 31708,
        "latest_valid_collected_at": "2026-08-02T23:44:50Z",
        "future_timestamp_count": 0,
        "snapshot_total": 17,
        "latest_snapshot_generated_at": "2026-08-02T23:45:05Z",
        "latest_source_public_at": "2026-08-02T23:40:00Z",
        "p0_dead_lettered": 0,
    }
    row.update(overrides)
    return row


def _d1_payload(**overrides: object) -> list[dict[str, object]]:
    return [{"success": True, "results": [_d1_row(**overrides)]}]


def test_control_plane_probe_accepts_exact_runtime_and_fresh_d1_state() -> None:
    receipt = build_receipt(
        deployment_metadata=_metadata(),
        versions_json=_versions(),
        deployments_json=_deployments(),
        d1_json=_d1_payload(),
        max_data_age_hours=2,
        max_future_skew_minutes=5,
        run_id="run-1",
        now=NOW,
    )

    assert receipt["status"] == "ok"
    assert receipt["deployed_commit"] == COMMIT
    assert receipt["evidence_source"] == "cloudflare-control-plane+d1"
    assert receipt["summary"]["future_timestamp_count"] == 0
    assert {check["name"] for check in receipt["checks"]} == {
        "deployment_receipt",
        "active_deployment",
        "collect_continuity",
        "data_freshness",
        "public_snapshot",
        "p0_dlq",
    }


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"collect_updated_at": "2026-08-02T20:00:00Z"}, "collect_continuity_stale"),
        ({"latest_valid_collected_at": "2026-08-02T20:00:00Z"}, "latest_collected_too_old"),
        ({"future_timestamp_count": 1}, "future_timestamps_present"),
        ({"snapshot_total": 0}, "active_snapshot_missing"),
        ({"latest_snapshot_generated_at": "2026-08-02T20:00:00Z"}, "active_snapshot_stale"),
        ({"p0_dead_lettered": 1}, "p0_dlq_not_empty"),
    ],
)
def test_control_plane_probe_fails_closed_on_unhealthy_d1_signals(
    overrides: dict[str, object],
    reason: str,
) -> None:
    receipt = build_receipt(
        deployment_metadata=_metadata(),
        versions_json=_versions(),
        deployments_json=_deployments(),
        d1_json=_d1_payload(**overrides),
        max_data_age_hours=2,
        max_future_skew_minutes=5,
        run_id="run-1",
        now=NOW,
    )

    assert receipt["status"] == "failed"
    assert reason in receipt["summary"]["reason_codes"]


def test_control_plane_probe_binds_d1_runtime_to_exact_commit_and_version() -> None:
    row = _d1_row()
    collect = json.loads(str(row["collect_value"]))
    collect["details"]["deploy_commit"] = "b" * 40
    collect["details"]["worker_version"] = "version-2"
    row["collect_value"] = json.dumps(collect)

    receipt = build_receipt(
        deployment_metadata=_metadata(),
        versions_json=_versions(),
        deployments_json=_deployments(),
        d1_json=[{"success": True, "results": [row]}],
        max_data_age_hours=2,
        max_future_skew_minutes=5,
        run_id="run-1",
        now=NOW,
    )

    assert receipt["status"] == "failed"
    assert "collect_commit_mismatch" in receipt["summary"]["reason_codes"]
    assert "collect_worker_version_mismatch" in receipt["summary"]["reason_codes"]


def test_control_plane_probe_rejects_malformed_d1_evidence() -> None:
    with pytest.raises(ControlPlaneProbeError, match="D1 query did not return one row"):
        build_receipt(
            deployment_metadata=_metadata(),
            versions_json=_versions(),
            deployments_json=_deployments(),
            d1_json=[{"success": True, "results": []}],
            max_data_age_hours=2,
            max_future_skew_minutes=5,
            run_id="run-1",
            now=NOW,
        )


def test_control_plane_probe_rejects_deployment_history_as_current_status() -> None:
    receipt = build_receipt(
        deployment_metadata=_metadata(),
        versions_json=_versions(),
        deployments_json=[
            {
                "id": "deployment-rollback",
                "versions": [{"version_id": "version-old", "percentage": 100}],
            },
            *_deployments(),
        ],
        d1_json=_d1_payload(),
        max_data_age_hours=2,
        max_future_skew_minutes=5,
        run_id="run-1",
        now=NOW,
    )

    assert receipt["status"] == "failed"
    assert "active_deployment_id_mismatch" in receipt["summary"]["reason_codes"]
    assert "active_worker_version_mismatch" in receipt["summary"]["reason_codes"]


def test_control_plane_probe_rejects_missing_receipt_deployment() -> None:
    receipt = build_receipt(
        deployment_metadata=_metadata(),
        versions_json=_versions(),
        deployments_json={
            "id": "deployment-rollback",
            "versions": [{"version_id": "version-old", "percentage": 100}],
        },
        d1_json=_d1_payload(),
        max_data_age_hours=2,
        max_future_skew_minutes=5,
        run_id="run-1",
        now=NOW,
    )

    assert receipt["status"] == "failed"
    assert "active_deployment_id_mismatch" in receipt["summary"]["reason_codes"]
    assert "active_worker_version_mismatch" in receipt["summary"]["reason_codes"]


def test_control_plane_probe_rejects_receipt_deployment_without_exact_version() -> None:
    receipt = build_receipt(
        deployment_metadata=_metadata(),
        versions_json=_versions(),
        deployments_json={
            "id": "deployment-1",
            "versions": [
                {"version_id": "version-1", "percentage": 50},
                {"version_id": "version-old", "percentage": 50},
            ],
        },
        d1_json=_d1_payload(),
        max_data_age_hours=2,
        max_future_skew_minutes=5,
        run_id="run-1",
        now=NOW,
    )

    assert receipt["status"] == "failed"
    assert "active_worker_version_mismatch" in receipt["summary"]["reason_codes"]
