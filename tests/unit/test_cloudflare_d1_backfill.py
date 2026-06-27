"""D1 backfill SQL generator tests."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from tools.cloudflare_d1_backfill import collect_backfill_plan, generate_backfill_sql


def _make_state_db(path: Path) -> None:
    path.parent.mkdir(parents=True)
    with closing(sqlite3.connect(path)) as db:
        db.execute(
            """
            CREATE TABLE event_index (
              event_id TEXT PRIMARY KEY,
              target_id TEXT NOT NULL,
              stage TEXT NOT NULL,
              source_id TEXT,
              news_value_score INTEGER,
              china_relevance INTEGER,
              classification_l0 TEXT,
              title_original TEXT,
              url TEXT,
              published_at TEXT,
              file_path TEXT,
              metadata_json TEXT,
              sentiment TEXT,
              entity_names TEXT,
              topic_tags TEXT,
              created_at TEXT NOT NULL,
              public_translation_ready INTEGER NOT NULL DEFAULT 0,
              gid TEXT
            )
            """
        )
        db.executemany(
            """
            INSERT INTO event_index (
              event_id, target_id, stage, source_id, news_value_score,
              china_relevance, classification_l0, title_original, url,
              published_at, created_at, topic_tags, entity_names
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "draft-1",
                    "italy",
                    "drafts",
                    "ansa",
                    80,
                    60,
                    "politics",
                    "Draft story",
                    "https://example.com/draft",
                    "2026-06-25T01:00:00+00:00",
                    "2026-06-25T01:01:00+00:00",
                    "politics,italy",
                    "Rome,EU",
                ),
                (
                    "reviewed-1",
                    "italy",
                    "reviewed",
                    "ansa",
                    90,
                    70,
                    "economy",
                    "Reviewed story",
                    "https://example.com/reviewed",
                    "2026-06-25T02:00:00+00:00",
                    "2026-06-25T02:01:00+00:00",
                    "economy",
                    "Milan",
                ),
            ],
        )
        db.commit()


def test_collect_backfill_plan_uses_only_drafts_and_counts_targets(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    targets_dir = tmp_path / "config" / "targets"
    targets_dir.mkdir(parents=True)
    (targets_dir / "italy.yaml").write_text(
        "target_id: italy\n"
        "display_name: 意大利新闻监控\n"
        "region_type: country\n"
        "language_scope:\n"
        "  primary: it\n",
        encoding="utf-8",
    )
    _make_state_db(data_dir / "italy" / "state.db")

    plan = collect_backfill_plan(data_dir=data_dir, targets_dir=targets_dir)

    assert [event.event_id for event in plan.events] == ["draft-1"]
    assert plan.targets[0].target_id == "italy"
    assert plan.targets[0].event_count == 1
    assert plan.sources[0].source_id == "ansa"


def test_generate_backfill_sql_is_idempotent_and_preserves_drafts_stage(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    targets_dir = tmp_path / "config" / "targets"
    targets_dir.mkdir(parents=True)
    (targets_dir / "italy.yaml").write_text("target_id: italy\n", encoding="utf-8")
    _make_state_db(data_dir / "italy" / "state.db")

    sql = generate_backfill_sql(collect_backfill_plan(data_dir=data_dir, targets_dir=targets_dir))

    assert "INSERT INTO events" in sql
    assert "ON CONFLICT(event_id) DO UPDATE" in sql
    assert "'drafts'" in sql
    assert "reviewed-1" not in sql
    assert "INSERT INTO targets" in sql
    assert "INSERT INTO sources" in sql
