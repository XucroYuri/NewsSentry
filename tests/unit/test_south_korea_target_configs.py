"""Regression tests for the South Korea target configuration."""

from __future__ import annotations

from pathlib import Path

import yaml

from news_sentry.core.memory import Memory
from news_sentry.models.newsevent import Language, NewsEvent, PipelineStage
from news_sentry.skills.filter.rules_filter import RulesFilter

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _event(title: str) -> NewsEvent:
    return NewsEvent(
        id="ne-test-south-korea-target-20260612-00000000",
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
    path = PROJECT_ROOT / "config" / "filters" / "south-korea" / "default.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_south_korea_filter_covers_politics_security_and_industry_signals(
    tmp_path: Path,
) -> None:
    """South Korea target should retain current domestic, peninsula, and chip headlines."""
    config = _filter_config()
    rules_filter = RulesFilter(config, Memory(tmp_path))
    threshold = int(config["score_threshold"])

    samples = [
        "South Korea local election setback pushes Lee Jae Myung cabinet into reset mode",
        "Seoul seeks inter-Korean dialogue after North Korea missile warning escalates",
        "Samsung and SK Hynix brace for semiconductor tariff shock in China-linked supply chains",
        "South Korea and Japan expand shipbuilding and LNG energy security cooperation",
    ]

    scores = [
        rules_filter._score_event(_event(title), config["keyword_rules"]) for title in samples
    ]

    assert scores == [score for score in scores if score >= threshold]


def test_south_korea_target_has_minimum_public_source_coverage() -> None:
    """South Korea target should launch with enough verified public RSS sources."""
    target_path = PROJECT_ROOT / "config" / "targets" / "south-korea.yaml"
    target = yaml.safe_load(target_path.read_text(encoding="utf-8"))
    refs = target["source_channel_refs"]

    assert len(refs) >= 5
    for ref in refs:
        assert (PROJECT_ROOT / "config" / "sources" / "south-korea" / f"{ref}.yaml").is_file()
