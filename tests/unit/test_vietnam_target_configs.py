"""Regression tests for the Vietnam target configuration."""

from __future__ import annotations

from pathlib import Path

import yaml

from news_sentry.core.memory import Memory
from news_sentry.models.newsevent import Language, NewsEvent, PipelineStage
from news_sentry.skills.filter.rules_filter import RulesFilter

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _event(title: str) -> NewsEvent:
    return NewsEvent(
        id="ne-test-vietnam-target-20260612-00000000",
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
    path = PROJECT_ROOT / "config" / "filters" / "vietnam" / "default.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_vietnam_filter_covers_trade_diplomacy_and_energy_signals(tmp_path: Path) -> None:
    """Vietnam target should retain current high-signal trade and diplomacy headlines."""
    config = _filter_config()
    rules_filter = RulesFilter(config, Memory(tmp_path))
    threshold = int(config["score_threshold"])

    samples = [
        "Vietnam expects trade deal progress as tariff pressure tests exporters in Hanoi",
        "Pham Minh Chinh pushes semiconductor and data center investment for Vietnam supply chains",
        "Hanoi and Beijing resume South China Sea talks alongside ASEAN diplomacy",
        "Vietnam expands LNG and offshore wind projects under revised national power plan",
    ]

    scores = [
        rules_filter._score_event(_event(title), config["keyword_rules"]) for title in samples
    ]

    assert scores == [score for score in scores if score >= threshold]


def test_vietnam_target_has_minimum_public_source_coverage() -> None:
    """Vietnam target should launch with enough verified public RSS sources."""
    target_path = PROJECT_ROOT / "config" / "targets" / "vietnam.yaml"
    target = yaml.safe_load(target_path.read_text(encoding="utf-8"))
    refs = target["source_channel_refs"]

    assert len(refs) >= 5
    for ref in refs:
        assert (PROJECT_ROOT / "config" / "sources" / "vietnam" / f"{ref}.yaml").is_file()
