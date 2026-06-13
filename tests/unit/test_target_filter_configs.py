"""Regression tests for target-specific filter/source configuration."""

from __future__ import annotations

from pathlib import Path

import yaml

from news_sentry.core.memory import Memory
from news_sentry.models.newsevent import Language, NewsEvent, PipelineStage
from news_sentry.skills.filter.rules_filter import RulesFilter

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _event(title: str, *, language: Language = Language.JA) -> NewsEvent:
    return NewsEvent(
        id="ne-test-target-config-20260530-00000000",
        run_id="test-run",
        source_id="fixture",
        url="https://example.com/news",
        title_original=title,
        content_original="",
        language=language,
        published_at="2026-05-30T00:00:00+00:00",
        collected_at="2026-05-30T00:05:00+00:00",
        pipeline_stage=PipelineStage.COLLECTED,
    )


def _filter_config(target_id: str) -> dict:
    path = PROJECT_ROOT / "config" / "filters" / target_id / "default.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_japan_filter_covers_current_domestic_and_geopolitical_signals(tmp_path: Path) -> None:
    """Japan should not collect real policy/economy/security headlines then score all of them 0."""
    config = _filter_config("japan")
    rules_filter = RulesFilter(config, Memory(tmp_path))
    threshold = int(config["score_threshold"])

    samples = [
        "「維新の政治ショー」、自民で反対論相次ぐ 　「副首都」法案めぐり",
        "日本の総人口1億2305万人　前回から309万人減　国勢調査速報",
        "最新AIアクセス権、電力など「重要インフラも」　オープンAI幹部",
        "米中再接近「信頼なき安定」　協力と対立が併存、台湾の取引がリスク",
    ]

    scores = [
        rules_filter._score_event(_event(title), config["keyword_rules"]) for title in samples
    ]

    assert scores == [score for score in scores if score >= threshold]


def test_china_watch_target_has_minimum_public_source_coverage() -> None:
    """China Watch needs enough independent public sources to avoid 0/1-output oscillation."""
    target_path = PROJECT_ROOT / "config" / "targets" / "china-watch-en.yaml"
    target = yaml.safe_load(target_path.read_text(encoding="utf-8"))
    refs = target["source_channel_refs"]

    assert len(refs) >= 8
    for ref in refs:
        assert (PROJECT_ROOT / "config" / "sources" / "china-watch-en" / f"{ref}.yaml").is_file()


def test_fusion_filter_covers_commercialization_and_technical_signals(tmp_path: Path) -> None:
    """Fusion target should keep high-signal commercial, project, and engineering headlines."""
    config = _filter_config("fusion")
    rules_filter = RulesFilter(config, Memory(tmp_path))
    threshold = int(config["score_threshold"])

    samples = [
        "Commonwealth Fusion Systems raises Series B funding for SPARC and ARC commercialization",
        "Helion fusion power purchase agreement with Microsoft targets grid electricity by 2028",
        "ITER installs high-temperature superconducting magnet systems for first plasma milestone",
        "Stellarator startup announces pilot plant supply chain partnership for fusion energy",
    ]

    scores = [
        rules_filter._score_event(_event(title, language=Language.EN), config["keyword_rules"])
        for title in samples
    ]

    assert scores == [score for score in scores if score >= threshold]


def test_fusion_target_has_minimum_enabled_source_coverage() -> None:
    """fusion.codes MVP needs at least three enabled sources before adding webpage collectors."""
    target_path = PROJECT_ROOT / "config" / "targets" / "fusion.yaml"
    target = yaml.safe_load(target_path.read_text(encoding="utf-8"))
    refs = target["source_channel_refs"]
    enabled_refs = []

    for ref in refs:
        source_path = PROJECT_ROOT / "config" / "sources" / "fusion" / f"{ref}.yaml"
        assert source_path.is_file()
        source = yaml.safe_load(source_path.read_text(encoding="utf-8"))
        if source["enabled"]:
            enabled_refs.append(ref)

    assert len(enabled_refs) >= 3
