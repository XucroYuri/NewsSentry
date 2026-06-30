from __future__ import annotations

from pathlib import Path

from tools.source_coverage_report import build_source_coverage_report

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_source_coverage_report_counts_active_target_refs() -> None:
    report = build_source_coverage_report(PROJECT_ROOT, minimum_refs=20)

    assert report["target_count"] >= 80
    assert report["minimum_refs"] == 20
    assert report["source_ref_total"] >= 300
    assert report["targets_below_minimum"]
    assert report["targets_below_minimum"][0]["target_id"]
    assert report["targets_below_minimum"][0]["missing"] > 0


def test_source_coverage_report_marks_france_as_ready() -> None:
    report = build_source_coverage_report(PROJECT_ROOT, minimum_refs=20)
    by_target = {item["target_id"]: item for item in report["targets"]}

    assert by_target["france"]["source_refs"] >= 20
    assert by_target["france"]["ready"] is True
