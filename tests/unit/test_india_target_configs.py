"""Regression tests for the India target configuration."""

from __future__ import annotations

from pathlib import Path

import yaml

from news_sentry.core.memory import Memory
from news_sentry.models.newsevent import Language, NewsEvent, PipelineStage
from news_sentry.skills.filter.rules_filter import RulesFilter

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _event(title: str) -> NewsEvent:
    return NewsEvent(
        id="ne-test-india-target-20260612-00000000",
        run_id="test-run",
        source_id="fixture",
        url="https://example.com/news",
        title_original=title,
        content_original="",
        language=Language.EN,
        published_at="2026-06-12T00:00:00+00:00",
        collected_at="2026-06-12T00:05:00+00:00",
        pipeline_stage=PipelineStage.COLLECTED,
    )


def _filter_config() -> dict:
    path = PROJECT_ROOT / "config" / "filters" / "india" / "default.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_india_filter_covers_diplomacy_economy_and_security_signals(tmp_path: Path) -> None:
    """India target should retain current high-signal India and China-linked headlines."""
    config = _filter_config()
    rules_filter = RulesFilter(config, Memory(tmp_path))
    threshold = int(config["score_threshold"])

    samples = [
        "India and China resume border talks ahead of BRICS summit in New Delhi",
        (
            "Modi government expands semiconductor manufacturing incentives "
            "for India supply chain push"
        ),
        "Indian Navy issues maritime security alert after tanker attack near Oman",
        "RBI warns rupee volatility may keep inflation risks elevated this quarter",
    ]

    scores = [
        rules_filter._score_event(_event(title), config["keyword_rules"]) for title in samples
    ]

    assert scores == [score for score in scores if score >= threshold]


def test_india_target_has_minimum_public_source_coverage() -> None:
    """India target should start with enough verified public RSS sources to avoid empty runs."""
    target_path = PROJECT_ROOT / "config" / "targets" / "india.yaml"
    target = yaml.safe_load(target_path.read_text(encoding="utf-8"))
    refs = target["source_channel_refs"]

    assert len(refs) >= 5
    for ref in refs:
        assert (PROJECT_ROOT / "config" / "sources" / "india" / f"{ref}.yaml").is_file()
