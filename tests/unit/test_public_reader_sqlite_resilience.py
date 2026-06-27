from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import news_sentry.core._state as runtime_state
from news_sentry.core import public_news_utils, target_config_utils


def _ready_metadata() -> str:
    return json.dumps(
        {
            "translation": {
                "title_pre": "日本新闻标题",
                "summary_pre": "这是一条可以公开展示的中文摘要。",
            },
            "publication": {
                "one_line_summary": "这是一条公开摘要。",
                "recommendation_reason": "这条新闻值得关注。",
                "issue_tags": ["政治"],
                "related_tags": ["涉中"],
            },
        },
        ensure_ascii=False,
    )


def _write_public_state_db(data_dir: Path, target_id: str, event_id: str) -> None:
    db_path = data_dir / target_id / "state.db"
    db_path.parent.mkdir(parents=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE event_index (
                event_id TEXT,
                target_id TEXT,
                source_id TEXT,
                news_value_score INTEGER,
                china_relevance INTEGER,
                classification_l0 TEXT,
                published_at TEXT,
                file_path TEXT,
                title_original TEXT,
                sentiment TEXT,
                entity_names TEXT,
                topic_tags TEXT,
                metadata_json TEXT,
                created_at TEXT,
                public_translation_ready INTEGER,
                stage TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO event_index (
                event_id, target_id, source_id, news_value_score, china_relevance,
                classification_l0, published_at, file_path, title_original, sentiment,
                entity_names, topic_tags, metadata_json, created_at,
                public_translation_ready, stage
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                target_id,
                "source-a",
                80,
                70,
                "politics",
                "2026-06-26T06:18:00Z",
                None,
                "Original title",
                "neutral",
                "[]",
                "[]",
                _ready_metadata(),
                "2026-06-26T06:18:00Z",
                1,
                "drafts",
            ),
        )


def _write_corrupt_state_db(data_dir: Path, target_id: str) -> None:
    db_path = data_dir / target_id / "state.db"
    db_path.parent.mkdir(parents=True)
    db_path.write_bytes(b"not a sqlite database")


@pytest.mark.asyncio
async def test_public_target_counts_skip_corrupt_target_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_public_state_db(tmp_path, "japan", "evt-japan")
    _write_corrupt_state_db(tmp_path, "italy")
    monkeypatch.setattr(
        target_config_utils,
        "_public_news_target_ids",
        lambda *_: ["italy", "japan"],
    )
    monkeypatch.setattr(runtime_state, "_store", None)

    counts = await target_config_utils._public_target_event_counts(tmp_path)

    assert counts == {"japan": 1}


@pytest.mark.asyncio
async def test_public_news_candidates_skip_corrupt_target_db_without_store_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_public_state_db(tmp_path, "japan", "evt-japan")
    _write_corrupt_state_db(tmp_path, "italy")
    monkeypatch.setattr(runtime_state, "_store", None)

    async def fail_if_store_opens(target_id: str) -> None:
        raise AssertionError(f"unexpected AsyncStore fallback for {target_id}")

    monkeypatch.setattr(public_news_utils, "_get_target_store", fail_if_store_opens)

    candidates, total = await public_news_utils._public_news_candidate_events(
        tmp_path,
        ["italy", "japan"],
        limit=10,
        allow_projection_first=True,
        allow_file_fallback=False,
        featured=False,
    )

    assert total == 1
    assert [(target_id, event["event_id"]) for target_id, event in candidates] == [
        ("japan", "evt-japan")
    ]
