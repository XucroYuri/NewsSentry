"""D1 backfill SQL generator tests."""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest
import tools.cloudflare_d1_public_translation_backfill as public_translation_backfill
from tools.cloudflare_d1_backfill import collect_backfill_plan, generate_backfill_sql
from tools.cloudflare_d1_public_translation_backfill import (
    DEFAULT_BACKFILL_TARGETS,
    collect_translation_patches,
    d1_candidate_query,
    generate_missing_public_translations,
    generate_missing_public_translations_from_d1_rows,
    generate_translation_backfill_sql,
    limit_patches_by_targets,
    parse_target_list,
    parse_wrangler_d1_json_output,
)

from news_sentry.core import collector_config_utils
from news_sentry.core.async_store import AsyncStore
from news_sentry.models.newsevent import Language, NewsEvent, PipelineStage

ROOT = Path(__file__).resolve().parents[2]


def _event(event_id: str) -> NewsEvent:
    now = datetime.now(UTC).isoformat()
    return NewsEvent(
        id=event_id,
        run_id="run-cloudflare-d1-backfill",
        source_id="lemonde",
        url=f"https://example.com/{event_id}",
        title_original="La France annonce un nouveau prêt européen",
        content_original="La mesure pourrait affecter les achats publics et les fournisseurs.",
        language=Language.FR,
        published_at=now,
        collected_at=now,
        pipeline_stage=PipelineStage.OUTPUTTED,
        news_value_score=88,
        china_relevance=60,
        metadata={"classification": {"l0": "politics"}},
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
        "source_channel_refs:\n"
        "  - ansa\n"
        "language_scope:\n"
        "  primary: it\n",
        encoding="utf-8",
    )
    (targets_dir / "japan.yaml").write_text(
        "target_id: japan\n"
        "display_name: 日本新闻监控\n"
        "source_channel_refs:\n"
        "  - nhk\n",
        encoding="utf-8",
    )
    _make_state_db(data_dir / "italy" / "state.db")

    plan = collect_backfill_plan(data_dir=data_dir, targets_dir=targets_dir)

    assert [event.event_id for event in plan.events] == ["draft-1"]
    assert plan.events[0].published_at == "2026-05-29T23:45:00Z"
    assert plan.events[0].classification == {"l0": "politics"}
    targets = {target.target_id: target for target in plan.targets}
    assert targets["italy"].event_count == 1
    assert targets["italy"].cloudflare_collect_enabled == 1
    assert targets["japan"].event_count == 0
    assert targets["japan"].cloudflare_collect_enabled == 1
    assert {source.source_id for source in plan.sources} == {"ansa", "nhk"}


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
    assert "'{\"l0\":\"politics\"}'" in sql
    assert "classification=excluded.classification" in sql
    assert "reviewed-1" not in sql
    assert "INSERT INTO targets" in sql
    assert "cloudflare_collect_enabled" in sql
    assert "INSERT INTO sources" in sql


def test_generated_backfill_sql_executes_against_d1_schema(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    targets_dir = tmp_path / "config" / "targets"
    targets_dir.mkdir(parents=True)
    (targets_dir / "italy.yaml").write_text("target_id: italy\n", encoding="utf-8")
    _make_state_db(data_dir / "italy" / "state.db")

    sql = generate_backfill_sql(collect_backfill_plan(data_dir=data_dir, targets_dir=targets_dir))

    with closing(sqlite3.connect(tmp_path / "d1.sqlite")) as db:
        db.executescript((ROOT / "frontend/cloudflare/db/schema.sql").read_text(encoding="utf-8"))
        db.executescript(sql)
        row = db.execute(
            "SELECT event_id, pipeline_stage, classification FROM events"
        ).fetchone()

    assert row == ("draft-1", "drafts", '{"l0":"politics"}')


def test_backfill_preserves_existing_public_translation_fields(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    targets_dir = tmp_path / "config" / "targets"
    targets_dir.mkdir(parents=True)
    (targets_dir / "italy.yaml").write_text("target_id: italy\n", encoding="utf-8")
    _make_state_db(data_dir / "italy" / "state.db")

    sql = generate_backfill_sql(collect_backfill_plan(data_dir=data_dir, targets_dir=targets_dir))

    with closing(sqlite3.connect(tmp_path / "d1.sqlite")) as db:
        db.executescript((ROOT / "frontend/cloudflare/db/schema.sql").read_text(encoding="utf-8"))
        db.execute(
            """
            INSERT INTO events (
              event_id, target_id, target_label, region_id, source_id, source_name,
              published_at, collected_at, title, original_title, summary,
              recommendation_reason, tags, issue_tags, related_tags, region_tags,
              language, pipeline_stage, value_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "draft-1",
                "italy",
                "意大利新闻监控",
                "italy",
                "ansa",
                "ansa",
                "2026-05-29T23:45:00Z",
                "2026-06-25T01:01:00+00:00",
                "意大利政府推进能源补贴调整",
                "Draft story",
                "意大利政府计划调整能源补贴，以应对财政压力和家庭用能成本。",
                "这项政策会影响家庭能源账单和财政支出，值得持续跟踪。",
                '["能源","涉欧","意大利"]',
                '["能源"]',
                '["涉欧"]',
                '["意大利"]',
                "zh",
                "drafts",
                75,
            ),
        )
        db.executescript(sql)
        row = db.execute(
            """
            SELECT title, summary, recommendation_reason, tags, issue_tags,
                   related_tags, region_tags, language, value_score
            FROM events WHERE event_id = 'draft-1'
            """
        ).fetchone()

    assert row == (
        "意大利政府推进能源补贴调整",
        "意大利政府计划调整能源补贴，以应对财政压力和家庭用能成本。",
        "这项政策会影响家庭能源账单和财政支出，值得持续跟踪。",
        '["能源","涉欧","意大利"]',
        '["能源"]',
        '["涉欧"]',
        '["意大利"]',
        "zh",
        80,
    )


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


def test_public_translation_backfill_target_and_daily_limits(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _make_state_db(data_dir / "italy" / "state.db")
    _make_state_db(data_dir / "france" / "state.db")
    ready_metadata = {
        "translation": {
            "title_pre": "法国政府推进能源补贴调整",
            "summary_pre": "法国政府计划调整能源补贴，以应对财政压力和家庭用能成本。",
        },
        "publication": {
            "one_line_summary": "法国调整能源补贴安排。",
            "recommendation_reason": "这项政策会影响家庭能源账单和财政支出，值得持续跟踪。",
            "issue_tags": ["能源"],
            "related_tags": ["涉欧"],
            "region_tags": ["法国"],
        },
    }
    for target in ("italy", "france"):
        with closing(sqlite3.connect(data_dir / target / "state.db")) as db:
            db.execute(
                "UPDATE event_index "
                "SET target_id = ?, metadata_json = ?, public_translation_ready = 1 "
                "WHERE event_id = 'draft-1'",
                (target, json_dump(ready_metadata)),
            )
            db.commit()

    patches = collect_translation_patches(data_dir=data_dir)
    selected = limit_patches_by_targets(
        patches,
        targets=parse_target_list("france,italy"),
        daily_limit=1,
        per_target_limit=1,
    )

    assert DEFAULT_BACKFILL_TARGETS[:2] == ("france", "south-korea")
    assert [patch.target_id for patch in selected] == ["france"]
    assert parse_target_list(" france, italy ,, ") == ("france", "italy")


@pytest.mark.asyncio
async def test_public_translation_generation_dry_run_counts_target_candidates(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    store = AsyncStore(data_dir / "france" / "state.db")
    await store.initialize()
    try:
        await store.index_event(_event("france-candidate"), "france", "drafts")
    finally:
        await store.close()

    result = await generate_missing_public_translations(
        data_dir=data_dir,
        targets=("france", "south-korea"),
        limit=200,
        per_target_limit=100,
        dry_run=True,
    )

    assert result.status == "dry_run"
    assert result.total_candidates == 1
    assert result.target_results == [
        {"target_id": "france", "candidates": 1},
        {"target_id": "south-korea", "candidates": 0},
    ]


def test_d1_candidate_query_targets_missing_public_fields() -> None:
    sql = d1_candidate_query(targets=("france", "south-korea"), limit=25)

    assert "FROM events" in sql
    assert "pipeline_stage = 'drafts'" in sql
    assert "target_id IN ('france', 'south-korea')" in sql
    assert "summary IS NULL" in sql
    assert "recommendation_reason IS NULL" in sql
    assert "CASE target_id WHEN 'france' THEN 0 WHEN 'south-korea' THEN 1" in sql
    assert "LIMIT 25" in sql


def test_d1_candidate_row_keeps_language_for_provider_source_lang() -> None:
    row = {
        "event_id": "fr-row-1",
        "target_id": "france",
        "source_id": "lemonde",
        "source_name": "Le Monde",
        "title": "La France annonce un nouveau prêt européen",
        "original_title": None,
        "summary": "La mesure pourrait affecter les achats publics.",
        "recommendation_reason": None,
        "full_content": "La mesure pourrait affecter les achats publics.",
        "original_url": "https://example.com/fr-row-1",
        "published_at": "2026-06-29T00:00:00+00:00",
        "collected_at": "2026-06-29T00:01:00+00:00",
        "value_score": 88,
        "classification": "{\"l0\":\"politics\"}",
        "issue_tags": "[]",
        "related_tags": "[]",
        "region_tags": "[]",
        "language": "fr",
    }

    mapped = public_translation_backfill._d1_row_to_translation_row(row)

    assert mapped["language"] == "fr"
    assert mapped["title_original"] == "La France annonce un nouveau prêt européen"


def test_parse_wrangler_d1_json_output_extracts_result_rows() -> None:
    output = json_dump(
        [
            {"success": True, "results": [{"event_id": "fr-1"}, {"event_id": "kr-1"}]},
            {"success": True, "results": []},
        ]
    )

    rows = parse_wrangler_d1_json_output(output)

    assert [row["event_id"] for row in rows] == ["fr-1", "kr-1"]


@pytest.mark.asyncio
async def test_d1_public_translation_generation_dry_run_counts_remote_candidates() -> None:
    rows = [
        {
            "event_id": "fr-d1-candidate",
            "target_id": "france",
            "source_id": "lemonde",
            "source_name": "Le Monde",
            "published_at": "2026-06-28T07:07:58+00:00",
            "collected_at": "2026-06-28T07:08:00+00:00",
            "title": "France announces a new industrial policy",
            "original_title": "France announces a new industrial policy",
            "summary": None,
            "recommendation_reason": None,
            "full_content": "The measure could affect public procurement and suppliers.",
            "original_url": "https://example.com/fr",
            "value_score": 88,
            "classification": "{\"l0\":\"politics\"}",
            "issue_tags": "[]",
            "related_tags": "[]",
            "region_tags": "[]",
            "language": "en",
        },
        {
            "event_id": "de-ignored",
            "target_id": "germany",
            "source_id": "dw",
            "source_name": "DW",
            "published_at": "2026-06-28T07:07:58+00:00",
            "title": "Germany item",
            "original_title": "Germany item",
            "summary": None,
            "recommendation_reason": None,
            "classification": "{\"l0\":\"politics\"}",
            "language": "en",
        },
    ]

    result = await generate_missing_public_translations_from_d1_rows(
        rows=rows,
        targets=("france", "south-korea"),
        limit=200,
        per_target_limit=100,
        dry_run=True,
    )

    assert result.status == "dry_run"
    assert result.total_candidates == 1
    assert result.target_results == [
        {"target_id": "france", "candidates": 1},
        {"target_id": "south-korea", "candidates": 0},
    ]


@pytest.mark.asyncio
async def test_d1_public_translation_generation_times_out_single_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        {
            "event_id": "fr-d1-candidate",
            "target_id": "france",
            "source_id": "lemonde",
            "source_name": "Le Monde",
            "published_at": "2026-06-28T07:07:58+00:00",
            "collected_at": "2026-06-28T07:08:00+00:00",
            "title": "France announces a new industrial policy",
            "original_title": "France announces a new industrial policy",
            "summary": None,
            "recommendation_reason": None,
            "full_content": "The measure could affect public procurement and suppliers.",
            "original_url": "https://example.com/fr",
            "value_score": 88,
            "classification": "{\"l0\":\"politics\"}",
            "issue_tags": "[]",
            "related_tags": "[]",
            "region_tags": "[]",
            "language": "en",
        }
    ]

    async def slow_patch(
        *_: object,
        **__: object,
    ) -> public_translation_backfill.PublicTranslationPatch:
        await asyncio.sleep(0.05)
        raise AssertionError("timeout should interrupt this candidate")

    monkeypatch.setattr(collector_config_utils, "_create_ai_provider_router", lambda: object())
    monkeypatch.setattr(
        collector_config_utils,
        "_build_ai_provider_factory",
        lambda: lambda _: object(),
    )
    monkeypatch.setattr(public_translation_backfill, "_d1_row_to_patch", slow_patch)

    result = await generate_missing_public_translations_from_d1_rows(
        rows=rows,
        targets=("france",),
        limit=1,
        per_target_limit=1,
        event_timeout_seconds=0.01,
    )

    assert result.status == "retrying"
    assert result.failed == 1
    assert result.updated == 0
    assert result.target_results == [
        {
            "target_id": "france",
            "status": "retrying",
            "updated": 0,
            "failed": 1,
            "error": "event translation timed out after 0.01s",
        }
    ]


def json_dump(value: object) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)
