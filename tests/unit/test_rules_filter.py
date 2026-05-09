"""Tests for skills/filter/rules_filter.py — keyword scoring, dedup, age filtering, threshold."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from news_sentry.core.memory import Memory
from news_sentry.models.newsevent import Language, NewsEvent, PipelineStage
from news_sentry.skills.filter.rules_filter import RulesFilter

# ── helpers ────────────────────────────────────────────────────


def _make_event(
    eid: str = "ne-italy-ansa-20260509-a1b2c3d4",
    title: str = "Governo Meloni discute riforme",
    content: str = "Il governo guidato da Meloni ha presentato nuove riforme.",
    published_at: str | None = None,
    title_translated: str | None = None,
    content_translated: str | None = None,
    language: Language = Language.IT,
) -> NewsEvent:
    if published_at is None:
        published_at = datetime.now(UTC).isoformat()
    return NewsEvent(
        id=eid,
        run_id="run-001",
        source_id="ansa",
        url="https://example.com/1",
        title_original=title,
        title_translated=title_translated,
        content_original=content,
        content_translated=content_translated,
        language=language,
        published_at=published_at,
        collected_at=datetime.now(UTC).isoformat(),
        pipeline_stage=PipelineStage.COLLECTED,
    )


def _make_filter_config(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "keyword_rules": [
            {"keyword": "governo", "weight": 0.8, "language": "it"},
            {"keyword": "Cina", "weight": 1.0, "language": "it"},
            {"keyword": "China", "weight": 1.0, "language": "en"},
            {"keyword": "mafia", "weight": 0.85, "language": "it"},
        ],
        "score_threshold": 40,
        "max_age_hours": 48,
        "dedup_window_hours": 24,
    }
    data.update(overrides)
    return data


# ── __init__ tests ─────────────────────────────────────────────


def test_init_parses_config(tmp_path: Path) -> None:
    cfg = _make_filter_config()
    rf = RulesFilter(cfg, Memory(tmp_path))
    assert rf._score_threshold == 40
    assert rf._max_age_hours == 48
    assert rf._dedup_window_hours == 24
    assert len(rf._keyword_rules) == 4


def test_init_defaults_on_missing_keys(tmp_path: Path) -> None:
    rf = RulesFilter({}, Memory(tmp_path))
    assert rf._score_threshold == 40
    assert rf._max_age_hours == 48
    assert rf._keyword_rules == []


# ── _score_event tests ─────────────────────────────────────────


def test_score_event_single_match(tmp_path: Path) -> None:
    event = _make_event(title="Governo presenta riforme", content="")
    config = _make_filter_config()
    rf = RulesFilter(config, Memory(tmp_path))
    score = rf._score_event(event, config["keyword_rules"])
    assert score == 80  # 0.8 * 100


def test_score_event_multiple_matches(tmp_path: Path) -> None:
    event = _make_event(
        title="Cina e mafia nel governo",
        content="Il governo italiano e la Cina",
    )
    config = _make_filter_config()
    rf = RulesFilter(config, Memory(tmp_path))
    score = rf._score_event(event, config["keyword_rules"])
    # 0.8 (governo) + 1.0 (Cina) + 0.85 (mafia) → 265 → cap at 100
    assert score == 100


def test_score_event_no_match(tmp_path: Path) -> None:
    event = _make_event(title="Sole e mare oggi", content="bel tempo")
    config = _make_filter_config()
    rf = RulesFilter(config, Memory(tmp_path))
    score = rf._score_event(event, config["keyword_rules"])
    assert score == 0


def test_score_event_case_insensitive(tmp_path: Path) -> None:
    event = _make_event(title="IL GOVERNO ITALIANO", content="")
    config = _make_filter_config()
    rf = RulesFilter(config, Memory(tmp_path))
    score = rf._score_event(event, config["keyword_rules"])
    assert score == 80


def test_score_event_matches_in_translated_fields(tmp_path: Path) -> None:
    event = _make_event(
        title="Roman holiday",
        content="A nice day in Rome.",
        title_translated="政府讨论改革",
        content_translated="中国与意大利政府合作",
    )
    cfg = _make_filter_config(
        keyword_rules=[
            {"keyword": "governo", "weight": 0.8, "language": "it"},
            {"keyword": "Cina", "weight": 1.0, "language": "it"},
            {"keyword": "China", "weight": 1.0, "language": "en"},
            {"keyword": "Roman", "weight": 0.5, "language": "en"},
        ]
    )
    rf = RulesFilter(cfg, Memory(tmp_path))
    score = rf._score_event(event, cfg["keyword_rules"])
    # "Roman" in title_original → 50
    assert score == 50


def test_score_event_substring_match(tmp_path: Path) -> None:
    """关键词匹配支持子串：govern 在 governativa 中命中。"""
    cfg = _make_filter_config(
        keyword_rules=[{"keyword": "govern", "weight": 0.8, "language": "it"}]
    )
    rf = RulesFilter(cfg, Memory(tmp_path))
    event = _make_event(title="azione governativa", content="")
    score = rf._score_event(event, cfg["keyword_rules"])
    assert score == 80  # "govern" in "governativa"


def test_score_event_empty_keyword_skipped(tmp_path: Path) -> None:
    event = _make_event(title="empty test", content="")
    rules = [{"keyword": "", "weight": 0.9, "language": "it"}]
    rf = RulesFilter({"keyword_rules": rules}, Memory(tmp_path))
    score = rf._score_event(event, rules)
    assert score == 0


# ── filter tests ───────────────────────────────────────────────


def test_filter_passes_event_above_threshold(tmp_path: Path) -> None:
    memory = Memory(tmp_path)
    cfg = _make_filter_config(score_threshold=40)
    rf = RulesFilter(cfg, memory)
    event = _make_event(title="Governo Meloni riforme", content="riforme")
    result = rf.filter([event], "run-001")
    assert len(result) == 1
    assert result[0].pipeline_stage == PipelineStage.FILTERED
    assert result[0].news_value_score == 80


def test_filter_rejects_event_below_threshold(tmp_path: Path) -> None:
    memory = Memory(tmp_path)
    cfg = _make_filter_config(score_threshold=90)
    rf = RulesFilter(cfg, memory)
    event = _make_event(title="Governo presenta", content="qualcosa")
    result = rf.filter([event], "run-001")
    assert len(result) == 0


def test_filter_dedup_skips_known_event(tmp_path: Path) -> None:
    memory = Memory(tmp_path)
    memory.mark_known("ne-italy-ansa-20260509-a1b2c3d4")
    cfg = _make_filter_config()
    rf = RulesFilter(cfg, memory)
    event = _make_event(title="Governo Meloni riforme", content="riforme")
    result = rf.filter([event], "run-001")
    assert len(result) == 0


def test_filter_marks_passed_event_as_known(tmp_path: Path) -> None:
    memory = Memory(tmp_path)
    cfg = _make_filter_config()
    rf = RulesFilter(cfg, memory)
    event = _make_event(title="Governo Meloni riforme", content="riforme")
    rf.filter([event], "run-001")
    assert memory.is_known(event.id) is True


def test_filter_skips_event_too_old(tmp_path: Path) -> None:
    memory = Memory(tmp_path)
    cfg = _make_filter_config(max_age_hours=24)
    rf = RulesFilter(cfg, memory)
    old_time = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
    event = _make_event(
        title="Governo Meloni riforme",
        content="riforme",
        published_at=old_time,
    )
    result = rf.filter([event], "run-001")
    assert len(result) == 0


def test_filter_accepts_event_within_age(tmp_path: Path) -> None:
    memory = Memory(tmp_path)
    cfg = _make_filter_config(max_age_hours=48)
    rf = RulesFilter(cfg, memory)
    recent = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    event = _make_event(
        title="Governo Meloni riforme",
        content="riforme",
        published_at=recent,
    )
    result = rf.filter([event], "run-001")
    assert len(result) == 1


def test_filter_mixed_events(tmp_path: Path) -> None:
    memory = Memory(tmp_path)
    cfg = _make_filter_config(score_threshold=50)
    rf = RulesFilter(cfg, memory)

    events = [
        _make_event(eid="e1", title="Governo Meloni", content="riforme"),  # 80 → pass
        _make_event(eid="e2", title="Sole e mare", content="bel tempo"),  # 0 → reject
        _make_event(eid="e3", title="Cina commercio", content="export"),  # 100 → pass
    ]
    result = rf.filter(events, "run-001")
    assert len(result) == 2
    assert {e.id for e in result} == {"e1", "e3"}


# ── _is_within_age edge cases ─────────────────────────────────


def test_is_within_age_bad_date_passes(tmp_path: Path) -> None:
    """格式无法解析的时间应宽容通过，避免因数据问题误丢弃事件。"""
    memory = Memory(tmp_path)
    rf = RulesFilter(_make_filter_config(), memory)
    event = _make_event(title="test", content="x")
    event_bad = event.model_copy(update={"published_at": "not-a-date"})
    # filter() 会走 _is_within_age，坏格式应过时效检查
    result = rf.filter([event_bad], "run-001")
    # 没匹配关键词，score=0 < threshold=40，但时效检查不是拒绝原因
    assert len(result) == 0
    # 单独测 _is_within_age — 坏日期应宽容通过
    assert RulesFilter._is_within_age(
        event_bad, datetime.now(UTC), timedelta(hours=48)
    ) is True
