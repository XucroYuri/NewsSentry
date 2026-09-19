from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools import control_receipt as receipt

COMMIT = "a" * 40
WINDOW_START = "2026-09-19T00:00:00Z"
WINDOW_END = "2026-09-20T00:00:00Z"


def _rows(*event_ids: str, score: float = 70.0) -> list[dict[str, Any]]:
    return [
        {
            "event_id": event_id,
            "value_score": score,
            "pipeline_stage": "judged",
        }
        for event_id in event_ids
    ]


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.write_text(json.dumps([{"results": rows, "success": True}]), encoding="utf-8")
    return path


def _build(**overrides: Any) -> dict[str, Any]:
    params: dict[str, Any] = {
        "track": "control",
        "environment": "production",
        "run_id": "run-1",
        "commit": COMMIT,
        "rows": _rows("e-1", "e-2"),
        "window_start": WINDOW_START,
        "window_end": WINDOW_END,
        "cpu_p50": 1.0,
        "cpu_p99": 4.0,
        "cpu_samples": 100,
        "source_ok_ratio": 0.95,
        "artifact_bytes": None,
        "dependency_count": None,
        "incremental_cost_usd": None,
        "silent_errors": 0,
        "healthy_slots": 0,
        "control_data_loss": 0,
        "control_downtime_seconds": 0,
    }
    params.update(overrides)
    return receipt.build_receipt(**params)


def test_build_receipt_is_valid_and_records_counts() -> None:
    built = _build()
    receipt.validate_receipt(built)

    assert built["receipt_version"] == receipt.RECEIPT_VERSION
    assert built["track"] == "control"
    assert built["counts"]["events"] == 2
    assert built["counts"]["by_stage"] == {"judged": 2}
    assert built["events_digest"].startswith("sha256:")
    assert built["scores_digest"].startswith("sha256:")


def test_digests_are_order_independent() -> None:
    """摘要必须与行序无关，否则两条轨道的读数无法配对。"""
    forward = _build(rows=_rows("e-1", "e-2", "e-3"))
    backward = _build(rows=_rows("e-3", "e-2", "e-1"))

    assert forward["events_digest"] == backward["events_digest"]
    assert forward["scores_digest"] == backward["scores_digest"]


def test_digests_detect_score_change() -> None:
    same = _build(rows=_rows("e-1", score=70.0))
    changed = _build(rows=_rows("e-1", score=71.0))

    assert same["events_digest"] == changed["events_digest"]  # 同一批事件
    assert same["scores_digest"] != changed["scores_digest"]  # 但研判结果不同


def test_cpu_without_samples_is_null_not_fabricated() -> None:
    built = _build(cpu_samples=0, cpu_p50=None, cpu_p99=None)

    assert built["cpu_ms"] == {"samples": 0, "p50": None, "p99": None}


def test_cpu_with_samples_requires_percentiles() -> None:
    import pytest
    from tools.control_common import ControlError

    with pytest.raises(ControlError):
        _build(cpu_samples=10, cpu_p50=None, cpu_p99=None)


def test_build_rejects_bad_inputs() -> None:
    import pytest
    from tools.control_common import ControlError

    for overrides in (
        {"track": "bogus"},
        {"commit": "short"},
        {"run_id": "   "},
        {"window_start": "2026-09-21T00:00:00Z"},  # start 晚于 end
        {"window_start": "not-a-date"},
        {"cpu_p50": 9.0, "cpu_p99": 1.0},  # p99 < p50
        {"silent_errors": -1},
        {"healthy_slots": -1},
    ):
        with pytest.raises(ControlError):
            _build(**overrides)


def test_validate_rejects_tampered_receipt() -> None:
    import pytest
    from tools.control_common import ControlError

    tampered_cases = (
        {"receipt_version": "control-v2"},
        {"track": "other"},
        {"commit": "x" * 40},
        {"events_digest": "sha256:short"},
        {"counts": {"events": "many", "by_stage": {}}},
        {"cpu_ms": {"samples": 5, "p50": 9.0, "p99": 1.0}},
        {"silent_errors": "none"},
        {"window": {"start": WINDOW_END, "end": WINDOW_START}},
    )
    for override in tampered_cases:
        bad = _build()
        bad.update(override)
        with pytest.raises(ControlError):
            receipt.validate_receipt(bad)


def test_cli_build_then_validate_roundtrip(tmp_path: Path) -> None:
    rows_path = _write_rows(tmp_path / "events.json", _rows("e-1", "e-2"))
    out = tmp_path / "receipt.json"

    assert (
        receipt.main(
            [
                "build",
                "--track", "treatment",
                "--environment", "preview",
                "--run-id", "run-9",
                "--commit", COMMIT,
                "--events", str(rows_path),
                "--window-start", WINDOW_START,
                "--window-end", WINDOW_END,
                "--cpu-p50", "1.5",
                "--cpu-p99", "3.5",
                "--cpu-samples", "42",
                "--output", str(out),
            ]
        )
        == 0
    )
    assert receipt.main(["validate", "--input", str(out)]) == 0

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["track"] == "treatment"
    assert payload["environment"] == "preview"
    assert payload["cpu_ms"] == {"samples": 42, "p50": 1.5, "p99": 3.5}


def test_cli_validate_fails_closed_on_bad_commit(tmp_path: Path) -> None:
    bad = _build()
    bad["commit"] = "nope"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad), encoding="utf-8")

    assert receipt.main(["validate", "--input", str(path)]) == 2


def test_cli_rejects_d1_payload_without_results(tmp_path: Path) -> None:
    path = tmp_path / "events.json"
    path.write_text(json.dumps({"unexpected": True}), encoding="utf-8")

    assert (
        receipt.main(
            [
                "build",
                "--track", "control",
                "--environment", "production",
                "--run-id", "r",
                "--commit", COMMIT,
                "--events", str(path),
                "--window-start", WINDOW_START,
                "--window-end", WINDOW_END,
                "--output", str(tmp_path / "out.json"),
            ]
        )
        == 2
    )
