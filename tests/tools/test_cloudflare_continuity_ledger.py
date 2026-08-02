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
    commit: str = COMMIT,
    status: str = "ok",
    run_id: str | None = None,
    source_health_status: str = "ok",
    future_timestamp_count: int = 0,
) -> dict[str, object]:
    observed_at = DEPLOYED_AT + timedelta(hours=hours)
    return {
        "deployed_commit": commit,
        "deployed_at": DEPLOYED_AT.isoformat(),
        "observed_at": observed_at.isoformat(),
        "run_id": run_id or f"run-{hours}",
        "status": status,
        "summary": {
            "reason_codes": [],
            "future_timestamp_count": future_timestamp_count,
        },
        "source_health": {
            "status": source_health_status,
            "audits": {
                "current": {"status": source_health_status},
                "start": {"status": source_health_status},
                "end": {"status": source_health_status},
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
