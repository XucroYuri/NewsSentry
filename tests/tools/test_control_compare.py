from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools import control_compare as compare

COMMIT = "b" * 40


def _rows(spec: dict[str, float | None]) -> list[dict[str, Any]]:
    return [
        {"event_id": event_id, "value_score": score, "pipeline_stage": "judged"}
        for event_id, score in spec.items()
    ]


def _receipt(
    *,
    track: str,
    cpu_p99: float | None,
    source_ok_ratio: float | None = 0.95,
    artifact_bytes: int | None = None,
    dependency_count: int | None = None,
    incremental_cost_usd: float | None = None,
    silent_errors: int = 0,
    healthy_slots: int = 28,
    control_data_loss: int = 0,
    control_downtime_seconds: int = 0,
) -> dict[str, Any]:
    return {
        "receipt_version": "control-v1",
        "track": track,
        "environment": "production" if track == "control" else "preview",
        "run_id": f"run-{track}",
        "commit": COMMIT,
        "window": {"start": "2026-09-19T00:00:00Z", "end": "2026-09-20T00:00:00Z"},
        "counts": {"events": 1, "by_stage": {"judged": 1}},
        "events_digest": "sha256:" + "0" * 64,
        "scores_digest": "sha256:" + "1" * 64,
        "cpu_ms": {"samples": 100, "p50": 1.0, "p99": cpu_p99},
        "source_ok_ratio": source_ok_ratio,
        "artifact_bytes": artifact_bytes,
        "dependency_count": dependency_count,
        "incremental_cost_usd": incremental_cost_usd,
        "silent_errors": silent_errors,
        "healthy_slots": healthy_slots,
        "control_data_loss": control_data_loss,
        "control_downtime_seconds": control_downtime_seconds,
    }


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.write_text(json.dumps([{"results": rows}]), encoding="utf-8")
    return path


# ── 集合运算 ──────────────────────────────────────────────────────────────


def test_compare_event_sets_reports_both_directions() -> None:
    control = _rows({"e-1": 70.0, "e-2": 60.0, "e-3": 50.0})
    treatment = _rows({"e-1": 70.0, "e-3": 50.0, "e-4": 40.0})

    sets = compare.compare_event_sets(control, treatment)

    assert sets["control_events"] == 3
    assert sets["treatment_events"] == 3
    assert sets["common"] == 2
    assert sets["recall"] == 2 / 3
    assert sets["precision"] == 2 / 3
    assert sets["missing_from_treatment_count"] == 1  # 对照组看到、实验组漏掉
    assert sets["missing_from_treatment_sample"] == ["e-2"]
    assert sets["extra_in_treatment_count"] == 1
    assert sets["digest_diff_count"] == 0


def test_compare_event_sets_detects_score_drift() -> None:
    control = _rows({"e-1": 70.0, "e-2": 60.0})
    treatment = _rows({"e-1": 70.0, "e-2": 61.0})  # 同一事件、不同分值

    sets = compare.compare_event_sets(control, treatment)

    assert sets["digest_diff_count"] == 1
    assert sets["digest_diff_sample"] == ["e-2"]


# ── 支配判定：六项指标 ────────────────────────────────────────────────────


def _fully_specified(
    *, treatment_cpu: float = 3.0, treatment_cost: float = 0.0
) -> dict[str, Any]:
    """构造六项数据齐备、且实验组占优的一组输入。"""
    sets = compare.compare_event_sets(_rows({"e-1": 70.0}), _rows({"e-1": 70.0}))
    control = _receipt(
        track="control", cpu_p99=6.0, artifact_bytes=300_000, incremental_cost_usd=5.0
    )
    treatment = _receipt(
        track="treatment",
        cpu_p99=treatment_cpu,
        artifact_bytes=100_000,
        dependency_count=0,
        incremental_cost_usd=treatment_cost,
    )
    return compare.evaluate_dominance(sets, control, treatment)


def test_dominance_requires_all_six_metrics() -> None:
    """核心 fail-closed 性质：缺数据的指标一律判不满足，支配不成立。"""
    sets = compare.compare_event_sets(_rows({"e-1": 70.0}), _rows({"e-1": 70.0}))

    # 无回执 → E1/E4/E5/E6 全部缺数据
    result = compare.evaluate_dominance(sets, None, None)

    assert result["verdict"] == "not_dominant"
    missing = [m["id"] for m in result["metrics"] if not m["present"]]
    assert set(missing) == {"E1", "E4", "E5", "E6"}
    assert any("缺少 A/B 双方数据" in blocker for blocker in result["blockers"])


def test_dominance_holds_when_everything_is_better() -> None:
    result = _fully_specified()

    assert result["verdict"] == "dominant"
    assert result["rules"]["no_weakness"] is True
    assert result["rules"]["absolute_floors"] is True
    assert result["rules"]["strict_advantage_count"] >= 3
    assert result["blockers"] == []


def test_absolute_floor_blocks_even_when_relatively_better() -> None:
    """召回 98.5% 相对更好也无用 —— 绝对地板是 99%。"""
    control = _rows({f"e-{i}": 50.0 for i in range(200)})
    treatment = _rows({f"e-{i}": 50.0 for i in range(197)})  # 197/200 = 98.5%
    sets = compare.compare_event_sets(control, treatment)

    assert sets["recall"] < compare.FLOOR_RECALL
    result = compare.evaluate_dominance(
        sets,
        _receipt(track="control", cpu_p99=6.0),
        _receipt(track="treatment", cpu_p99=3.0, artifact_bytes=1, dependency_count=0,
                 incremental_cost_usd=0.0),
    )

    assert result["verdict"] == "not_dominant"
    assert any("绝对地板" in blocker for blocker in result["blockers"])


def test_control_source_ok_ratio_is_an_admission_gate() -> None:
    """对照组自身 ok 率不达 90% 时，实验无效。"""
    result = compare.evaluate_dominance(
        compare.compare_event_sets(_rows({"e-1": 70.0}), _rows({"e-1": 70.0})),
        _receipt(track="control", cpu_p99=6.0, source_ok_ratio=0.74),
        _receipt(track="treatment", cpu_p99=3.0, artifact_bytes=1, dependency_count=0,
                 incremental_cost_usd=0.0),
    )

    assert result["verdict"] == "not_dominant"
    assert any("E2 未达绝对地板" in blocker for blocker in result["blockers"])


def test_digest_drift_blocks_dominance() -> None:
    sets = compare.compare_event_sets(_rows({"e-1": 70.0}), _rows({"e-1": 99.0}))
    result = compare.evaluate_dominance(
        sets,
        _receipt(track="control", cpu_p99=6.0),
        _receipt(track="treatment", cpu_p99=3.0, artifact_bytes=1, dependency_count=0,
                 incremental_cost_usd=0.0),
    )

    assert sets["digest_diff_count"] == 1
    assert result["verdict"] == "not_dominant"
    assert any("E3" in blocker for blocker in result["blockers"])


def test_persistence_and_zero_cost_are_mandatory() -> None:
    sets = compare.compare_event_sets(_rows({"e-1": 70.0}), _rows({"e-1": 70.0}))

    too_few_slots = compare.evaluate_dominance(
        sets,
        _receipt(track="control", cpu_p99=6.0),
        _receipt(track="treatment", cpu_p99=3.0, artifact_bytes=1, dependency_count=0,
                 incremental_cost_usd=0.0, healthy_slots=27),
    )
    assert too_few_slots["verdict"] == "not_dominant"
    assert any("连续健康槽位不足" in blocker for blocker in too_few_slots["blockers"])

    control_harmed = compare.evaluate_dominance(
        sets,
        _receipt(track="control", cpu_p99=6.0),
        _receipt(track="treatment", cpu_p99=3.0, artifact_bytes=1, dependency_count=0,
                 incremental_cost_usd=0.0, control_data_loss=1),
    )
    assert control_harmed["verdict"] == "not_dominant"
    assert any("对照组出现数据损失" in blocker for blocker in control_harmed["blockers"])


def test_dependency_count_blocks_artifact_floor() -> None:
    """E4 的地板是"体积 + 0 依赖"合取，缺一不可。"""
    result = compare.evaluate_dominance(
        compare.compare_event_sets(_rows({"e-1": 70.0}), _rows({"e-1": 70.0})),
        _receipt(track="control", cpu_p99=6.0),
        _receipt(track="treatment", cpu_p99=3.0, artifact_bytes=1, dependency_count=1,
                 incremental_cost_usd=0.0),
    )

    assert result["verdict"] == "not_dominant"
    assert any("E4 未达绝对地板" in blocker for blocker in result["blockers"])


# ── CLI 与不可覆盖性 ──────────────────────────────────────────────────────


def test_cli_assert_dominance_exits_nonzero_when_not_dominant(tmp_path: Path) -> None:
    control = _write_rows(tmp_path / "c.json", _rows({"e-1": 70.0}))
    treatment = _write_rows(tmp_path / "t.json", _rows({"e-1": 70.0}))
    out = tmp_path / "dominance.json"

    code = compare.main(
        [
            "compare",
            "--control-events", str(control),
            "--treatment-events", str(treatment),
            "--output", str(out),
            "--assert-dominance",
        ]
    )

    assert code == 1
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["verdict"] == "not_dominant"
    assert report["schema_version"] == compare.SCHEMA_VERSION


def test_cli_has_no_flag_that_can_force_dominance() -> None:
    """判定不可人工覆盖：命令行只暴露输入与断言开关，没有任何"强制通过"选项。

    这是 L1.6 的硬要求 —— 一个可以被开关覆盖的判据等于没有判据。
    """
    import io
    from contextlib import redirect_stdout

    buffer = io.StringIO()
    with redirect_stdout(buffer), pytest.raises(SystemExit):
        compare.main(["compare", "--help"])

    help_text = buffer.getvalue()
    assert "--assert-dominance" in help_text
    for forbidden in ("--force", "--override", "--assume", "--skip", "--ignore"):
        assert forbidden not in help_text, f"存在可能覆盖判定的开关：{forbidden}"


def test_cli_writes_report_with_input_digests(tmp_path: Path) -> None:
    control = _write_rows(tmp_path / "c.json", _rows({"e-1": 70.0}))
    treatment = _write_rows(tmp_path / "t.json", _rows({"e-1": 70.0}))
    out = tmp_path / "dominance.json"

    assert (
        compare.main(
            [
                "compare",
                "--control-events", str(control),
                "--treatment-events", str(treatment),
                "--output", str(out),
            ]
        )
        == 0
    )

    report = json.loads(out.read_text(encoding="utf-8"))
    generated = report["generated_from"]
    assert generated["control_events_digest"].startswith("sha256:")
    assert generated["treatment_events_digest"].startswith("sha256:")
    assert generated["control_receipt_digest"] is None
