"""D1 backfill SQL generator tests."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from tools.cloudflare_d1_backfill import collect_backfill_plan, generate_backfill_sql
from tools.cloudflare_d1_public_translation_backfill import (
    collect_translation_patches,
    generate_translation_backfill_sql,
)


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
                    "20260529T234500Z",
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
    assert plan.events[0].published_at == "2026-05-29T23:45:00Z"
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


def test_public_translation_backfill_updates_only_ready_public_fields(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _make_state_db(data_dir / "italy" / "state.db")
    ready_metadata = {
        "translation": {
            "title_pre": "意大利政府推进能源补贴调整",
            "summary_pre": "意大利政府计划调整能源补贴，以应对财政压力和家庭用能成本。",
        },
        "publication": {
            "one_line_summary": "意大利调整能源补贴安排。",
            "recommendation_reason": "这项政策会影响家庭能源账单和财政支出，值得持续跟踪。",
            "issue_tags": ["能源"],
            "related_tags": ["涉欧"],
            "region_tags": ["意大利"],
        },
    }
    not_ready_metadata = {
        "translation": {
            "title_pre": "意大利银行业利润承压",
            "summary_pre": "意大利银行业利润因利率环境变化承压。",
        }
    }
    short_title_metadata = {
        "translation": {
            "title_pre": "外国人在韩",
            "summary_pre": "5月外国在韩消费创新高",
        },
        "publication": {
            "one_line_summary": "5月外国在韩消费创新高。",
            "recommendation_reason": "韩国消费数据出现新变化，适合纳入区域经济跟踪。",
            "issue_tags": ["经济"],
            "related_tags": ["东亚"],
            "region_tags": ["韩国"],
        },
    }
    with closing(sqlite3.connect(data_dir / "italy" / "state.db")) as db:
        db.execute(
            "UPDATE event_index SET metadata_json = ?, public_translation_ready = 1 "
            "WHERE event_id = 'draft-1'",
            (json_dump(ready_metadata),),
        )
        db.execute(
            """
            INSERT INTO event_index (
              event_id, target_id, stage, source_id, title_original,
              published_at, created_at, metadata_json, public_translation_ready
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "draft-2",
                "italy",
                "drafts",
                "ansa",
                "Bank profits",
                "2026-06-25T03:00:00+00:00",
                "2026-06-25T03:01:00+00:00",
                json_dump(not_ready_metadata),
                0,
            ),
        )
        db.execute(
            """
            INSERT INTO event_index (
              event_id, target_id, stage, source_id, title_original,
              published_at, created_at, metadata_json, public_translation_ready
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "draft-short",
                "italy",
                "drafts",
                "ansa",
                "Foreign spending in Korea hits fresh high in May",
                "2026-06-25T04:00:00+00:00",
                "2026-06-25T04:01:00+00:00",
                json_dump(short_title_metadata),
                1,
            ),
        )
        db.commit()

    patches = collect_translation_patches(data_dir=data_dir)
    sql = generate_translation_backfill_sql(patches)

    assert [patch.event_id for patch in patches] == ["draft-1"]
    assert "UPDATE events SET" in sql
    assert "意大利政府推进能源补贴调整" in sql
    assert "recommendation_reason" in sql
    assert "draft-2" not in sql
    assert "draft-short" not in sql
    assert "INSERT INTO targets" not in sql


def json_dump(value: object) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)
