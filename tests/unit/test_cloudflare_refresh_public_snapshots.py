"""Cloudflare public snapshot refresh tool tests."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from tools.cloudflare_refresh_public_snapshots import (
    build_snapshot_upsert_sql,
    parse_wrangler_d1_json_output,
)

ROOT = Path(__file__).resolve().parents[2]


def test_parse_wrangler_d1_json_output_reads_select_results() -> None:
    raw = """
    [
      {
        "results": [{"event_id": "e1", "title": "Story"}],
        "success": true,
        "meta": {"duration": 1}
      }
    ]
    """

    assert parse_wrangler_d1_json_output(raw) == [{"event_id": "e1", "title": "Story"}]


def test_snapshot_upsert_sql_writes_fixed_keys_to_d1_schema(tmp_path: Path) -> None:
    payloads = {
        "news:featured:v1:page_size=20": {"items": [{"id": "e1"}], "total": 1},
        "news:all:v1:page_size=20": {"items": [{"id": "e2"}], "total": 1},
        "bootstrap:featured:v1:page_size=20": {"news": {"items": [{"id": "e1"}]}},
        "facets:v1": {"regions": [{"id": "italy"}], "issues": [], "related": []},
        "regions:active:v1": {"regions": [{"region_id": "italy"}]},
    }

    sql = build_snapshot_upsert_sql(
        payloads,
        generated_at="2026-06-30T01:00:00Z",
        source_latest_public_at="2026-06-30T00:48:15Z",
    )

    assert "BEGIN TRANSACTION" not in sql
    assert "COMMIT;" not in sql

    with closing(sqlite3.connect(tmp_path / "d1.sqlite")) as db:
        db.executescript((ROOT / "frontend/cloudflare/db/schema.sql").read_text(encoding="utf-8"))
        db.executescript(sql)
        rows = db.execute(
            "SELECT key, item_count FROM public_read_snapshots ORDER BY key"
        ).fetchall()

    assert rows == [
        ("bootstrap:featured:v1:page_size=20", 1),
        ("facets:v1", 1),
        ("news:all:v1:page_size=20", 1),
        ("news:featured:v1:page_size=20", 1),
        ("regions:active:v1", 1),
    ]


def test_snapshot_tool_includes_breaking_v2_public_fields() -> None:
    from tools.cloudflare_refresh_public_snapshots import _news_item

    item = _news_item(
        {
            "event_id": "e1",
            "target_id": "france",
            "target_label": "法国",
            "source_id": "lemonde",
            "source_name": "Le Monde",
            "source_type": "rss",
            "published_at": "2026-07-02T01:00:00Z",
            "title": "France announces emergency measure",
            "detail_url": "/public-app/news/e1",
            "tags": "[]",
            "issue_tags": "[]",
            "related_tags": "[]",
            "region_tags": "[]",
            "entities": "[]",
            "related_count": 0,
            "value_label": "精选",
            "value_score": 91,
            "breaking_score": 82,
            "breaking_raw_score": 88,
            "breaking_percentile": 86.4,
            "breaking_calibrated_score": 82,
            "breaking_label": "watch",
            "breaking_reason": "分布校准后仍值得关注，但未达到 flash 阈值。",
            "breaking_confidence": 78,
            "breaking_dimensions": '{"impact_scope":88}',
            "breaking_score_version": "breaking-v2.0",
            "target_timezone": "Europe/Paris",
            "published_at_local": "2026-07-02T03:00:00+02:00",
            "china_relevance_label": "中",
        }
    )

    assert item["breakingScore"] == 82
    assert item["breakingRawScore"] == 88
    assert item["breakingPercentile"] == 86.4
    assert item["breakingCalibratedScore"] == 82
    assert item["breakingVersion"] == "breaking-v2.0"
