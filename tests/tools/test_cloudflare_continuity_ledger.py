from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tools.cloudflare_continuity_ledger import (
    ContinuityReceiptError,
    append_receipt,
    evaluate_window,
)

COMMIT = "a" * 40
DEPLOYED_AT = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)


def healthy_receipt(
    *,
    hours: int,
    minutes: int = 17,
    commit: str = COMMIT,
    status: str = "ok",
    run_id: str | None = None,
    environment: str = "production",
    source_health_status: str = "ok",
    source_health_generated_at: datetime | None = None,
    future_timestamp_count: int = 0,
) -> dict[str, object]:
    observed_at = DEPLOYED_AT + timedelta(hours=hours, minutes=minutes)
    audit_generated_at = source_health_generated_at or observed_at
    source_health_audit = {
        "status": source_health_status,
        "generated_at": audit_generated_at.isoformat(),
        "environment": environment,
        "deployed_commit": commit,
    }
    return {
        "deployed_commit": commit,
        "deployed_at": DEPLOYED_AT.isoformat(),
        "observed_at": observed_at.isoformat(),
        "run_id": run_id or f"run-{hours}",
        "environment": environment,
        "status": status,
        "summary": {
            "reason_codes": [],
            "future_timestamp_count": future_timestamp_count,
        },
        "source_health": {
            "status": source_health_status,
            "audits": {
                "current": source_health_audit,
                "start": source_health_audit,
                "end": source_health_audit,
            },
        },
    }


def test_72h_requires_twelve_same_commit_receipts() -> None:
    receipts = [healthy_receipt(hours=(index + 1) * 6) for index in range(11)]

    assert evaluate_window(receipts).status == "collecting_72h"

    receipts.append(healthy_receipt(hours=72))
    result = evaluate_window(receipts)

    assert result.status == "canary_72h_passed"
    assert result.healthy_72h_slots == 12


def test_7d_requires_twenty_eight_same_commit_receipts_and_boundary_audits() -> None:
    receipts = [healthy_receipt(hours=(index + 1) * 6) for index in range(27)]

    assert evaluate_window(receipts).status == "collecting_7d"

    receipts.append(healthy_receipt(hours=168))
    result = evaluate_window(receipts)

    assert result.status == "slo_7d_passed"
    assert result.healthy_7d_slots == 28


def test_window_fails_on_commit_drift_future_timestamps_and_unhealthy_receipts() -> None:
    drifted = [
        healthy_receipt(hours=6),
        healthy_receipt(hours=12, commit="b" * 40),
    ]
    result = evaluate_window(drifted)
    assert result.status == "failed"
    assert "deployed_commit_changed" in result.reason_codes

    future = [healthy_receipt(hours=6, future_timestamp_count=1)]
    assert "future_timestamps_present" in evaluate_window(future).reason_codes

    unhealthy = [healthy_receipt(hours=6, source_health_status="failed")]
    assert "source_health_not_ok" in evaluate_window(unhealthy).reason_codes


def test_append_receipt_rejects_conflicting_duplicate_key(tmp_path: Path) -> None:
    ledger_path = tmp_path / "continuity.jsonl"
    receipt = healthy_receipt(hours=6, run_id="same-run")

    append_receipt(ledger_path, receipt)
    append_receipt(ledger_path, receipt)

    conflicting = {**receipt, "status": "failed"}
    with pytest.raises(ContinuityReceiptError, match="conflicting duplicate"):
        append_receipt(ledger_path, conflicting)


def test_six_hour_buckets_allow_cron_offsets_and_detect_gaps() -> None:
    receipts = [
        healthy_receipt(hours=6, minutes=17, run_id="slot-1-a"),
        healthy_receipt(hours=6, minutes=43, run_id="slot-1-b"),
        healthy_receipt(hours=18, minutes=17, run_id="slot-3"),
    ]

    result = evaluate_window(receipts)

    assert result.status == "failed"
    assert result.healthy_72h_slots == 2
    assert "missing_six_hour_slot" in result.reason_codes


def test_source_health_evidence_requires_fresh_matching_metadata() -> None:
    stale = healthy_receipt(
        hours=6,
        source_health_generated_at=DEPLOYED_AT - timedelta(days=2),
    )
    stale_result = evaluate_window([stale])

    assert stale_result.status == "failed"
    assert "source_health_audit_too_old" in stale_result.reason_codes

    mismatched = healthy_receipt(hours=6)
    mismatched["source_health"] = {
        "audits": {
            "current": {
                "status": "ok",
                "generated_at": (DEPLOYED_AT + timedelta(hours=6)).isoformat(),
                "environment": "preview",
                "deployed_commit": COMMIT,
            },
            "start": {
                "status": "ok",
                "generated_at": (DEPLOYED_AT + timedelta(hours=6)).isoformat(),
                "environment": "production",
                "deployed_commit": "b" * 40,
            },
            "end": {
                "status": "ok",
                "generated_at": (DEPLOYED_AT + timedelta(hours=5)).isoformat(),
                "environment": "production",
                "deployed_commit": COMMIT,
            },
        }
    }
    mismatch_result = evaluate_window([mismatched])

    assert "source_health_environment_mismatch" in mismatch_result.reason_codes
    assert "source_health_commit_mismatch" in mismatch_result.reason_codes
    assert "source_health_window_order_invalid" in mismatch_result.reason_codes
