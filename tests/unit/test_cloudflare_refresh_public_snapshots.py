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
