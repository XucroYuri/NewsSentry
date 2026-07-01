"""Regression tests for the Ireland target configuration."""

from __future__ import annotations

from pathlib import Path

import yaml

from news_sentry.core.memory import Memory
from news_sentry.models.newsevent import Language, NewsEvent, PipelineStage
from news_sentry.skills.filter.rules_filter import RulesFilter

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _source_path_for_ref(target_id: str, ref: str) -> Path:
    if ref.startswith("pool:"):
        pool_id, source_id = ref.removeprefix("pool:").split("/", 1)
        return PROJECT_ROOT / "config" / "source-pools" / pool_id / f"{source_id}.yaml"
    return PROJECT_ROOT / "config" / "sources" / target_id / f"{ref}.yaml"


def _event(title: str) -> NewsEvent:
    return NewsEvent(
        id="ne-test-ireland-target-20260613-00000000",
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
    path = PROJECT_ROOT / "config" / "filters" / "ireland" / "default.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_ireland_filter_covers_governance_migration_and_growth_signals(
    tmp_path: Path,
) -> None:
    """Ireland target should retain current governance, migration, and growth signals."""
    config = _filter_config()
    rules_filter = RulesFilter(config, Memory(tmp_path))
    threshold = int(config["score_threshold"])

    samples = [
        (
            "Ireland prepares its EU presidency as Micheál Martin and the Dáil "
            "push foreign affairs priorities"
        ),
        (
            "Dublin reviews asylum appeals and Common Travel Area safeguards "
            "as migration pact rules take effect"
        ),
        "Irish FDI and AI investment stay in focus as data centre growth and energy policy collide",
        (
            "Housing affordability and public services remain central to "
            "Ireland's cost of living debate"
        ),
    ]

    scores = [
        rules_filter._score_event(_event(title), config["keyword_rules"]) for title in samples
    ]

    assert scores == [score for score in scores if score >= threshold]


def test_ireland_target_has_minimum_public_source_coverage() -> None:
    """Ireland target should launch with enough verified public RSS sources."""
    target_path = PROJECT_ROOT / "config" / "targets" / "ireland.yaml"
    target = yaml.safe_load(target_path.read_text(encoding="utf-8"))
    refs = target["source_channel_refs"]

    assert len(refs) >= 6
    for ref in refs:
        assert _source_path_for_ref("ireland", ref).is_file()
