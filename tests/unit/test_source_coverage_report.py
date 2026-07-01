from __future__ import annotations

from pathlib import Path

from tools.source_coverage_report import build_source_coverage_report, write_receipts_jsonl

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_source_coverage_report_counts_active_target_refs() -> None:
    report = build_source_coverage_report(PROJECT_ROOT, minimum_refs=20)

    assert report["target_count"] >= 80
    assert report["minimum_refs"] == 20
    assert report["source_ref_total"] >= 300
    assert report["ready_targets"] == report["target_count"]
    assert report["targets_below_minimum"] == []


def test_source_coverage_report_marks_france_as_ready() -> None:
    report = build_source_coverage_report(PROJECT_ROOT, minimum_refs=20)
    by_target = {item["target_id"]: item for item in report["targets"]}

    assert by_target["france"]["source_refs"] >= 20
    assert by_target["france"]["ready"] is True


def test_source_coverage_report_resolves_source_pool_refs(tmp_path: Path) -> None:
    target_dir = tmp_path / "config" / "targets"
    pool_dir = tmp_path / "config" / "source-pools" / "global"
    target_dir.mkdir(parents=True)
    pool_dir.mkdir(parents=True)
    (target_dir / "spain.yaml").write_text(
        "\n".join(
            [
                "target_id: spain",
                "display_name: Spain",
                "source_channel_refs:",
                "  - pool:global/gdelt-geopolitics",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (pool_dir / "gdelt-geopolitics.yaml").write_text(
        "\n".join(
            [
                "source_id: gdelt-geopolitics",
                "display_name: GDELT Geopolitics",
                "type: api",
                "endpoint:",
                "  url: https://api.gdeltproject.org/api/v2/doc/doc",
                "enabled: true",
                "credibility_base: 0.7",
                "fetch_interval_minutes: 30",
                "max_items_per_run: 30",
                "timeout_seconds: 30",
                "",
            ]
        ),
        encoding="utf-8",
    )

    report = build_source_coverage_report(tmp_path, minimum_refs=1)
    spain = report["targets"][0]

    assert spain["ready"] is True
    assert spain["source_refs"] == 1
    assert spain["valid_source_refs"] == 1
    assert spain["missing_files"] == []
    assert spain["source_candidate_receipts"][0]["source_ref"] == (
        "pool:global/gdelt-geopolitics"
    )
    assert spain["source_candidate_receipts"][0]["accepted_reason"] == "static_valid"


def test_source_coverage_report_extracts_validation_evidence_from_notes(
    tmp_path: Path,
) -> None:
    target_dir = tmp_path / "config" / "targets"
    sources_dir = tmp_path / "config" / "sources" / "demo"
    target_dir.mkdir(parents=True)
    sources_dir.mkdir(parents=True)
    (target_dir / "demo.yaml").write_text(
        "\n".join(
            [
                "target_id: demo",
                "display_name: Demo",
                "source_channel_refs:",
                "  - active",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (sources_dir / "active.yaml").write_text(
        "\n".join(
            [
                "source_id: active",
                "display_name: Active",
                "type: rss",
                "url: https://example.com/rss.xml",
                "credibility_base: 0.8",
                "fetch_interval_minutes: 30",
                "max_items_per_run: 20",
                "timeout_seconds: 30",
                "enabled: true",
                (
                    "notes: '2026-07-01 source audit: HTTP 200, 12 entries, "
                    "latest 2026-07-01T00:00:00Z; validated.'"
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )

    report = build_source_coverage_report(tmp_path, minimum_refs=1)
    receipt = report["targets"][0]["source_candidate_receipts"][0]

    assert receipt["http_status"] == 200
    assert receipt["parser_entry_count"] == 12
    assert receipt["latest_entry_at"] == "2026-07-01T00:00:00Z"


def test_source_coverage_report_counts_only_enabled_non_deprecated_refs(
    tmp_path: Path,
) -> None:
    target_dir = tmp_path / "config" / "targets"
    sources_dir = tmp_path / "config" / "sources" / "demo"
    target_dir.mkdir(parents=True)
    sources_dir.mkdir(parents=True)
    (target_dir / "demo.yaml").write_text(
        "\n".join(
            [
                "target_id: demo",
                "display_name: Demo",
                "source_channel_refs:",
                "  - active",
                "  - disabled",
                "  - retired",
                "",
            ]
        ),
        encoding="utf-8",
    )
    source_template = "\n".join(
        [
            "source_id: {source_id}",
            "display_name: {source_id}",
            "type: rss",
            "url: https://example.com/{source_id}.xml",
            "credibility_base: 0.8",
            "fetch_interval_minutes: 30",
            "max_items_per_run: 20",
            "timeout_seconds: 30",
            "enabled: {enabled}",
            "{deprecated_line}",
            "",
        ]
    )
    (sources_dir / "active.yaml").write_text(
        source_template.format(source_id="active", enabled="true", deprecated_line=""),
        encoding="utf-8",
    )
    (sources_dir / "disabled.yaml").write_text(
        source_template.format(source_id="disabled", enabled="false", deprecated_line=""),
        encoding="utf-8",
    )
    (sources_dir / "retired.yaml").write_text(
        source_template.format(
            source_id="retired",
            enabled="true",
            deprecated_line="deprecated: true",
        ),
        encoding="utf-8",
    )

    report = build_source_coverage_report(tmp_path, minimum_refs=2)
    demo = report["targets"][0]

    assert demo["source_refs"] == 3
    assert demo["valid_source_refs"] == 1
    assert demo["ready"] is False
    assert demo["invalid_source_refs"] == ["disabled", "retired"]
    assert demo["source_candidate_receipts"][1]["accepted_reason"] == "disabled"
    assert demo["source_candidate_receipts"][2]["accepted_reason"] == "deprecated"


def test_write_receipts_jsonl_flattens_target_receipts(tmp_path: Path) -> None:
    report = {
        "targets": [
            {
                "target_id": "demo",
                "source_candidate_receipts": [
                    {
                        "target_id": "demo",
                        "source_ref": "active",
                        "source_id": "active",
                        "url": "https://example.com/rss.xml",
                        "type": "rss",
                        "accepted_reason": "static_valid",
                    }
                ],
            }
        ]
    }
    output = tmp_path / "receipts.jsonl"

    count = write_receipts_jsonl(report, output)

    assert count == 1
    assert output.read_text(encoding="utf-8").strip() == (
        '{"accepted_reason": "static_valid", "source_id": "active", '
        '"source_ref": "active", "target_id": "demo", "type": "rss", '
        '"url": "https://example.com/rss.xml"}'
    )
