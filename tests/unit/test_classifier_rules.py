"""Tests for skills/filter/classifier_rules.py — L0/L1/L2 rule-based classification."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from news_sentry.core.config import ConfigLoader
from news_sentry.models.newsevent import Language, NewsEvent, PipelineStage
from news_sentry.skills.filter.classification_taxonomy import (
    canonical_l0,
    public_channel_for_terms,
)
from news_sentry.skills.filter.classifier_rules import ClassifierRules

# ── helpers ────────────────────────────────────────────────────


def _make_event(
    title: str = "Governo Meloni discute riforme",
    content: str = "Il governo italiano ha presentato nuove riforme.",
    title_translated: str | None = None,
    content_translated: str | None = None,
    language: Language = Language.IT,
) -> NewsEvent:
    return NewsEvent(
        id="ne-italy-ansa-20260509-a1b2c3d4",
        run_id="run-001",
        source_id="ansa",
        url="https://example.com/1",
        title_original=title,
        title_translated=title_translated,
        content_original=content,
        content_translated=content_translated,
        language=language,
        published_at=datetime.now(UTC).isoformat(),
        collected_at=datetime.now(UTC).isoformat(),
        pipeline_stage=PipelineStage.FILTERED,
    )


def _make_classification_config(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "rules_version": "1.0.0",
        "l0_domains": [
            {
                "code": "politics",
                "keywords_it": ["governo", "parlamento", "elezioni"],
                "keywords_en": ["government", "parliament", "election"],
                "keywords_zh": ["政府", "议会", "选举"],
            },
            {
                "code": "economics",
                "keywords_it": ["economia", "PIL", "banca"],
                "keywords_en": ["economy", "GDP", "bank"],
                "keywords_zh": ["经济"],
            },
            {
                "code": "security",
                "keywords_it": ["mafia", "polizia", "arresto"],
                "keywords_en": ["mafia", "police", "arrest"],
                "keywords_zh": [],
            },
        ],
        "l1_topics": [
            {
                "code": "govt_coalition",
                "l0_domain": "politics",
                "keywords_it": ["coalizione", "governo", "maggioranza"],
                "keywords_en": ["coalition", "government"],
                "keywords_zh": [],
            },
            {
                "code": "eu_policy",
                "l0_domain": "politics",
                "keywords_it": ["Bruxelles", "regolamento"],
                "keywords_en": ["Brussels", "regulation"],
                "keywords_zh": [],
            },
            {
                "code": "fiscal_policy",
                "l0_domain": "economics",
                "keywords_it": ["debito", "manovra", "bilancio"],
                "keywords_en": ["deficit", "budget"],
                "keywords_zh": [],
            },
            {
                "code": "organized_crime",
                "l0_domain": "security",
                "keywords_it": ["mafia", "camorra", "ndrangheta"],
                "keywords_en": ["mafia"],
                "keywords_zh": [],
            },
            {
                "code": "china_italy_bilateral",
                "l0_domain": "politics",
                "keywords_it": ["Cina", "Pechino"],
                "keywords_en": ["China", "Beijing"],
                "keywords_zh": ["中国"],
            },
        ],
        "country_axes": {
            "politics": {
                "enabled": True,
                "sub_axes": ["govt_coalition", "eu_policy", "china_italy_bilateral"],
            },
            "economics": {
                "enabled": True,
                "sub_axes": ["fiscal_policy"],
            },
            "crime": {
                "enabled": True,
                "sub_axes": ["organized_crime"],
            },
            "china_italy_relations": {
                "enabled": True,
                "sub_axes": ["china_italy_bilateral"],
            },
            "sports": {
                "enabled": False,
                "sub_axes": [],
            },
        },
    }
    data.update(overrides)
    return data


# ── __init__ tests ─────────────────────────────────────────────


def test_init_parses_config() -> None:
    cfg = _make_classification_config()
    cr = ClassifierRules(cfg)
    assert len(cr._l0_domains) == 3
    assert len(cr._l1_topics) == 5
    assert len(cr._country_axes) == 5


def test_init_empty_config() -> None:
    cr = ClassifierRules({})
    assert cr._l0_domains == []
    assert cr._l1_topics == []
    assert cr._country_axes == {}


# ── L0 domain classification tests ─────────────────────────────


def test_l0_classifies_politics() -> None:
    event = _make_event(
        title="Il governo e il parlamento discutono elezioni",
        content="Nuove elezioni regionali previste.",
    )
    cr = ClassifierRules(_make_classification_config())
    result = cr.classify(event)
    c = result.metadata["classification"]
    assert c["l0"] == "politics"
    assert c["confidence"] > 0


def test_l0_classifies_economics() -> None:
    event = _make_event(
        title="Aumenta il PIL italiano",
        content="L'economia cresce del 2% secondo la banca centrale.",
    )
    cr = ClassifierRules(_make_classification_config())
    result = cr.classify(event)
    c = result.metadata["classification"]
    assert c["l0"] == "economy"


def test_l0_classifies_security() -> None:
    event = _make_event(
        title="Arrestato boss mafioso",
        content="La polizia ha arrestato un latitante della mafia.",
    )
    cr = ClassifierRules(_make_classification_config())
    result = cr.classify(event)
    c = result.metadata["classification"]
    assert c["l0"] == "public-safety"


def test_l0_uncategorized_when_no_match() -> None:
    event = _make_event(title="Oggi bel tempo", content="Sole e mare per tutto il weekend.")
    cr = ClassifierRules(_make_classification_config())
    result = cr.classify(event)
    c = result.metadata["classification"]
    assert c["l0"] == "uncategorized"
    assert c["confidence"] == 0


def test_l0_uncategorized_when_no_domains() -> None:
    event = _make_event(title="Test", content="data")
    cr = ClassifierRules({"l0_domains": []})
    result = cr.classify(event)
    c = result.metadata["classification"]
    assert c["l0"] == "uncategorized"
    assert c["confidence"] == 0


def test_l0_matches_translated_text() -> None:
    """L0 也应在翻译文本中查找关键词。"""
    event = _make_event(
        title="Nice weather today",
        content="Nothing important.",
        title_translated="政府讨论新政策",
        content_translated="议会投票通过法案",
    )
    cr = ClassifierRules(_make_classification_config())
    result = cr.classify(event)
    c = result.metadata["classification"]
    # "政府", "议会", "选举" all match in translated text → politics
    assert c["l0"] == "politics"


def test_l0_case_insensitive() -> None:
    event = _make_event(title="IL GOVERNO E IL PARLAMENTO", content="ELEZIONI")
    cr = ClassifierRules(_make_classification_config())
    result = cr.classify(event)
    c = result.metadata["classification"]
    assert c["l0"] == "politics"


# ── L1 topic classification tests ──────────────────────────────


def test_l1_matches_topic_in_domain() -> None:
    event = _make_event(
        title="La coalizione di governo si rafforza",
        content="La maggioranza parlamentare ha votato la fiducia.",
    )
    cr = ClassifierRules(_make_classification_config())
    result = cr.classify(event)
    c = result.metadata["classification"]
    assert c["l0"] == "politics"
    topics = c["l1"]
    topic_codes = {t["code"] for t in topics}
    assert "govt_coalition" in topic_codes
    for t in topics:
        assert 0 < t["confidence"] <= 100


def test_l1_only_matches_in_l0_domain() -> None:
    """L1 只匹配属于当前 L0 域的主题，不跨域匹配。"""
    event = _make_event(
        title="L'economia e il debito pubblico",
        content="La manovra economica con il PIL in crescita.",
    )
    cr = ClassifierRules(_make_classification_config())
    result = cr.classify(event)
    c = result.metadata["classification"]
    assert c["l0"] == "economy"
    topics = c["l1"]
    topic_codes = {t["code"] for t in topics}
    # "fiscal_policy" is L0=economics, should match
    # "govt_coalition" is L0=politics, should NOT match even if text contains governo-like words
    assert "fiscal_policy" in topic_codes
    assert "govt_coalition" not in topic_codes


def test_l1_no_matches_returns_empty() -> None:
    event = _make_event(title="Sole e mare", content="Weekend al mare.")
    cr = ClassifierRules(_make_classification_config())
    result = cr.classify(event)
    c = result.metadata["classification"]
    assert c["l1"] == []


def test_canonical_l0_maps_legacy_runtime_labels() -> None:
    assert canonical_l0("economics") == "economy"
    assert canonical_l0("security") == "public-safety"
    assert canonical_l0("international") == "international-relations"
    assert canonical_l0("culture_society") == "society"
    assert canonical_l0("environment_energy") == "environment"
    assert canonical_l0("political") == "politics"
    assert canonical_l0("technology") == "tech"
    assert canonical_l0("energy") == "environment"
    assert canonical_l0("china_related") == "china-related"
    assert canonical_l0("breaking_news") == "uncategorized"
    assert canonical_l0("other") == "uncategorized"


def test_public_channel_for_terms_uses_canonical_taxonomy() -> None:
    assert public_channel_for_terms(["economy", "energy"]) == "industry"
    assert public_channel_for_terms(["international-relations", "sanctions"]) == "risk"
    assert public_channel_for_terms(["tech", "ai"]) == "tech"
    assert public_channel_for_terms(["china-related"]) == "china"


def test_classifier_outputs_canonical_l0_and_candidates() -> None:
    cfg = {
        "l0_domains": [
            {"code": "economics", "keywords_en": ["market", "trade"]},
            {"code": "tech", "keywords_en": ["semiconductor", "ai"]},
        ],
        "l1_topics": [
            {"code": "trade", "l0_domain": "economy", "keywords_en": ["trade"]},
            {"code": "semiconductor", "l0_domain": "tech", "keywords_en": ["semiconductor"]},
        ],
        "country_axes": {},
    }
    event = _make_event(title="Semiconductor trade market pressure", content="")
    result = ClassifierRules(cfg).classify(event)
    classification = result.metadata["classification"]
    assert classification["l0"] == "economy"
    assert classification["candidates"][0]["code"] == "economy"
    assert classification["candidates"][0]["hits"] >= 1


# ── L2 country axes tests ──────────────────────────────────────


def test_l2_activates_china_axis_via_l1() -> None:
    event = _make_event(
        title="Cina e Pechino firmano accordo",
        content="Relazioni bilaterali tra Cina e Italia.",
    )
    cr = ClassifierRules(
        _make_classification_config(
            l0_domains=[
                {
                    "code": "politics",
                    "keywords_it": ["governo", "parlamento", "Cina", "Pechino"],
                    "keywords_en": ["government", "China"],
                    "keywords_zh": [],
                },
                {
                    "code": "economics",
                    "keywords_it": ["economia", "PIL"],
                    "keywords_en": ["economy"],
                    "keywords_zh": [],
                },
                {
                    "code": "security",
                    "keywords_it": ["mafia"],
                    "keywords_en": ["mafia"],
                    "keywords_zh": [],
                },
            ],
        )
    )
    result = cr.classify(event)
    c = result.metadata["classification"]
    axes = c["l2"]
    axis_codes = {a["code"] for a in axes}
    assert "china_italy_relations" in axis_codes


def test_l2_skips_disabled_axes() -> None:
    event = _make_event(title="Sole e mare", content="niente")
    cfg = _make_classification_config()
    cr = ClassifierRules(cfg)
    result = cr.classify(event)
    c = result.metadata["classification"]
    axes = c["l2"]
    # sports axis is disabled, should never appear
    assert all(a["code"] != "sports" for a in axes)


def test_l2_no_axes_when_no_l1_match() -> None:
    event = _make_event(title="Unknown topic", content="nothing relevant")
    cr = ClassifierRules(_make_classification_config())
    result = cr.classify(event)
    c = result.metadata["classification"]
    assert c["l2"] == []


# ── metadata structure tests ───────────────────────────────────


def test_classification_structure_is_correct() -> None:
    event = _make_event(
        title="Il governo discute riforme con Bruxelles",
        content="La commissione ha approvato il regolamento.",
    )
    cr = ClassifierRules(_make_classification_config())
    result = cr.classify(event)
    c = result.metadata["classification"]
    assert c["l0"] == "politics"
    assert isinstance(c["confidence"], int)
    assert 0 <= c["confidence"] <= 100
    assert isinstance(c["l1"], list)
    assert isinstance(c["l2"], list)
    assert c["l3"] == []
    assert c["classifier_version"] == "rules-v1"


def test_classify_does_not_modify_scores() -> None:
    event = _make_event(title="Governo riforme", content="discussione")
    event.news_value_score = 75
    cr = ClassifierRules(_make_classification_config())
    result = cr.classify(event)
    assert result.news_value_score == 75
    assert result.pipeline_stage == PipelineStage.FILTERED


def test_classify_returns_same_instance() -> None:
    event = _make_event(title="Governo riforme", content="discussione")
    cr = ClassifierRules(_make_classification_config())
    result = cr.classify(event)
    assert result is event


def test_real_japan_rules_classify_japanese_disaster_event() -> None:
    config = ConfigLoader(Path(".")).load_target("japan")
    event = _make_event(
        title="【台風6号】沖縄・奄美に接近 九州から関東甲信で大雨も",
        content="猛烈な風が吹き、大雨になるおそれがあります。",
        language=Language.JA,
    )

    result = ClassifierRules(config.classification_rules).classify(event)

    assert result.metadata["classification"]["l0"] == "disaster"
