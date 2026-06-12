"""Regression tests for the New Zealand target configuration."""

from __future__ import annotations

from pathlib import Path

import yaml

from news_sentry.core.memory import Memory
from news_sentry.models.newsevent import Language, NewsEvent, PipelineStage
from news_sentry.skills.filter.rules_filter import RulesFilter

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _event(title: str) -> NewsEvent:
    return NewsEvent(
        id="ne-test-new-zealand-target-20260613-00000000",
        run_id="test-run",
        source_id="fixture",
        url="https://example.com/news",
        title_original=title,
        content_original="",
        language=Language.EN,
        published_at="2026-06-13T00:00:00+00:00",
        collected_at="2026-06-13T00:05:00+00:00",
        pipeline_stage=PipelineStage.COLLECTED,
    )


def _filter_config() -> dict:
    path = PROJECT_ROOT / "config" / "filters" / "new-zealand" / "default.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_new_zealand_filter_covers_budget_trade_and_security_signals(tmp_path: Path) -> None:
    """New Zealand target should retain current high-signal budget, China, and security headlines."""
    config = _filter_config()
    rules_filter = RulesFilter(config, Memory(tmp_path))
    threshold = int(config["score_threshold"])

    samples = [
        "New Zealand budget sharpens spending cuts as Wellington pushes growth and fiscal repair",
        "Christopher Luxon says trade resilience and dairy exports matter as US tariff risks mount",
        "Wellington raises concerns with Beijing after lawmakers face Hong Kong entry bans",
        "New Zealand expands defence and Pacific security cooperation while watching China ties",
    ]

    scores = [
        rules_filter._score_event(_event(title), config["keyword_rules"]) for title in samples
    ]

    assert scores == [score for score in scores if score >= threshold]


def test_new_zealand_target_has_minimum_public_source_coverage() -> None:
    """New Zealand target should launch with enough verified public RSS sources."""
    target_path = PROJECT_ROOT / "config" / "targets" / "new-zealand.yaml"
    target = yaml.safe_load(target_path.read_text(encoding="utf-8"))
    refs = target["source_channel_refs"]

    assert len(refs) >= 6
    for ref in refs:
        assert (PROJECT_ROOT / "config" / "sources" / "new-zealand" / f"{ref}.yaml").is_file()
