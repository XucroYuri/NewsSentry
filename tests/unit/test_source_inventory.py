"""Tests for target source inventory reconciliation."""

from __future__ import annotations

from pathlib import Path

import yaml

from news_sentry.core.source_inventory import SourceInventoryService


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def test_source_inventory_reconciles_refs_files_social_and_health(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path / "config" / "targets" / "italy.yaml",
        {
            "target_id": "italy",
            "display_name": "意大利新闻监控",
            "language_scope": {"primary": "it"},
            "source_channel_refs": [
                "ansa",
                "api/gnews",
                "missing-source",
                "social/twitter/politics",
            ],
        },
    )
    _write_yaml(
        tmp_path / "config" / "sources" / "italy" / "ansa.yaml",
        {
            "source_id": "ansa",
            "display_name": "ANSA",
            "type": "rss",
            "url": "https://example.com/ansa.xml",
            "enabled": True,
        },
    )
    _write_yaml(
        tmp_path / "config" / "sources" / "italy" / "api" / "gnews.yaml",
        {
            "source_id": "gnews",
            "display_name": "GNews",
            "type": "api",
            "endpoint": {"url": "https://example.com/gnews"},
            "enabled": False,
            "deprecated": True,
            "deprecated_reason": "quota",
        },
    )
    _write_yaml(
        tmp_path / "config" / "sources" / "italy" / "orphan.yaml",
        {
            "source_id": "orphan",
            "display_name": "Orphan",
            "type": "rss",
            "url": "https://example.com/orphan.xml",
            "enabled": True,
        },
    )
    _write_yaml(
        tmp_path / "config" / "sources" / "italy" / "social" / "twitter" / "politics.yaml",
        {
            "platform": "twitter",
            "dimension": "politics",
            "collect_mode": "opencli_bridge",
            "accounts": [
                {"handle": "@active", "monitor_mode": "active"},
                {"handle": "@archived", "monitor_mode": "archived"},
            ],
        },
    )
    _write_yaml(
        tmp_path / "data" / "italy" / "memory" / "source_health.yaml",
        {
            "ansa": {"last_success_at": "2026-05-29T00:00:00+00:00", "total_runs": 2},
            "gnews": {
                "last_failure_at": "2026-05-29T01:00:00+00:00",
                "consecutive_failures": 4,
                "total_runs": 4,
                "total_failures": 4,
            },
            "ghost": {"consecutive_failures": 11, "total_runs": 11, "total_failures": 11},
        },
    )

    inventory = SourceInventoryService(tmp_path, tmp_path / "data").build_target_inventory("italy")

    assert inventory["target"]["target_id"] == "italy"
    assert inventory["summary"] == {
        "refs_total": 4,
        "files_total": 4,
        "standard_sources": 3,
        "social_dimensions": 1,
        "social_accounts": 2,
        "active_sources": 3,
        "archived_sources": 1,
        "missing_refs": 1,
        "unreferenced_files": 1,
        "duplicate_source_ids": 0,
        "health_records": 3,
        "health_matched": 2,
        "health_unmatched": 1,
    }
    by_ref = {item["source_ref"]: item for item in inventory["sources"]}
    assert by_ref["ansa"]["health"]["status"] == "healthy"
    assert by_ref["api/gnews"]["health"]["status"] == "degraded"
    assert by_ref["api/gnews"]["archived"] is True
    assert by_ref["missing-source"]["missing_file"] is True
    assert by_ref["orphan"]["unreferenced"] is True
    assert by_ref["social/twitter/politics"]["account_count"] == 2
    assert by_ref["social/twitter/politics"]["archived_account_count"] == 1
    assert inventory["diagnostics"]["unmatched_health"][0]["source_id"] == "ghost"
