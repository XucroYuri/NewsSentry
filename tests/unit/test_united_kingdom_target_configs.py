"""Regression tests for the United Kingdom target configuration."""

from __future__ import annotations

from pathlib import Path

import yaml

from news_sentry.core.memory import Memory
from news_sentry.models.newsevent import Language, NewsEvent, PipelineStage
from news_sentry.skills.filter.rules_filter import RulesFilter

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _event(title: str) -> NewsEvent:
    return NewsEvent(
        id="ne-test-united-kingdom-target-20260613-00000000",
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
    path = PROJECT_ROOT / "config" / "filters" / "united-kingdom" / "default.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_united_kingdom_filter_covers_governance_defence_and_fiscal_signals(
    tmp_path: Path,
) -> None:
    """UK target should retain current cabinet, defence, and Treasury signals."""
    config = _filter_config()
    rules_filter = RulesFilter(config, Memory(tmp_path))
    threshold = int(config["score_threshold"])

    samples = [
        (
            "Downing Street confirms Keir Starmer cabinet changes as Westminster "
            "debates defence spending and security priorities"
        ),
        (
            "HM Treasury and the Bank of England weigh inflation, growth and the "
            "cost of living as Britain eyes its next budget decisions"
        ),
        (
            "The Ministry of Defence expands drone testing while the UK tightens "
            "sanctions and trade restrictions linked to Russian fuel routes"
        ),
        (
            "British migration and border policy stays in focus as public "
            "services and housing pressures rise"
        ),
    ]

    scores = [
        rules_filter._score_event(_event(title), config["keyword_rules"]) for title in samples
    ]

    assert scores == [score for score in scores if score >= threshold]


def test_united_kingdom_target_has_minimum_public_source_coverage() -> None:
    """UK target should launch with enough verified public RSS and Atom sources."""
    target_path = PROJECT_ROOT / "config" / "targets" / "united-kingdom.yaml"
    target = yaml.safe_load(target_path.read_text(encoding="utf-8"))
    refs = target["source_channel_refs"]

    assert len(refs) >= 6
    for ref in refs:
        assert (PROJECT_ROOT / "config" / "sources" / "united-kingdom" / f"{ref}.yaml").is_file()
