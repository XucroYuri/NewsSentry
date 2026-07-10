from __future__ import annotations

from news_sentry.core.breaking_scoring import (
    BREAKING_SCORE_VERSION,
    BreakingScoreInput,
    BreakingScoreStats,
    BreakingScoreValidationError,
    calibrate_breaking_assessment,
    score_breaking_event,
    validate_llm_breaking_assessment,
)


def test_breaking_score_contract_is_v2() -> None:
    assert BREAKING_SCORE_VERSION == "breaking-v2.0"


def test_deterministic_breaking_score_separates_flash_from_routine_update() -> None:
    flash = score_breaking_event(
        BreakingScoreInput(
            target_id="france",
            source_type="official",
            credibility_label="high",
            value_score=96,
            published_age_minutes=8,
            classification_l0="politics",
            issue_tags=["international_relations", "security"],
            related_tags=["eu", "china"],
            summary="法国政府突然宣布影响欧盟安全政策的新决定。",
            recommendation_reason="这会改变跨境政策判断和后续外交安排。",
            duplicate_count=0,
        )
    )
    routine = score_breaking_event(
        BreakingScoreInput(
            target_id="france",
            source_type="rss",
            credibility_label="medium",
            value_score=75,
            published_age_minutes=360,
            classification_l0="other",
            issue_tags=["culture"],
            related_tags=[],
            summary="例行发布会重申此前政策，没有新增实质信息。",
            recommendation_reason="这只是常规更新。",
            duplicate_count=5,
            is_opinion=True,
        )
    )

    assert flash.version == BREAKING_SCORE_VERSION
    assert flash.label == "flash"
    assert flash.score >= 85
    assert flash.dimensions["urgency"] > routine.dimensions["urgency"]
    assert flash.score - routine.score >= 35
    assert routine.label == "timeline"


def test_breaking_calibration_uses_percentile_to_avoid_false_flash() -> None:
    raw = validate_llm_breaking_assessment(
        {
            "breaking_score": 88,
            "breaking_label": "flash",
            "breaking_confidence": 82,
            "breaking_reason": "事件有明显跨境影响，但同类高分事件近期较多，需要按分布校准。",
            "dimensions": {
                "impact_scope": 88,
                "urgency": 82,
                "novelty": 78,
                "source_reliability": 86,
                "actionability": 72,
                "systemic_or_cross_border": 84,
                "human_attention": 70,
                "evidence_confidence": 86,
            },
            "penalties": {
                "duplicate": 0,
                "routine": 0,
                "sensationalism": 0,
                "thin_evidence": 0,
            },
            "adversarial_checks": {
                "not_routine": True,
                "not_opinion": True,
                "not_duplicate": True,
                "not_single_source_social": True,
                "has_trustworthy_timestamp": True,
            },
        }
    )

    calibrated = calibrate_breaking_assessment(
        raw,
        BreakingScoreStats(
            scope_key="global",
            window_days=30,
            mean_score=82,
            stddev_score=8,
            p75=84,
            p90=91,
            p95=96,
            sample_count=250,
        ),
    )

    assert calibrated.raw_score == 88
    assert calibrated.percentile < 90
    assert calibrated.score < raw.score
    assert calibrated.label == "watch"


def test_llm_breaking_assessment_requires_adversarial_checks_and_distribution() -> None:
    payload = {
        "breaking_score": 88,
        "breaking_label": "breaking",
        "breaking_confidence": 82,
        "breaking_reason": "政策变化具有跨境影响，并且来自可信官方与主流媒体信号。",
        "dimensions": {
            "impact_scope": 90,
            "urgency": 80,
            "novelty": 84,
            "source_reliability": 88,
            "actionability": 76,
            "systemic_or_cross_border": 82,
            "human_attention": 72,
            "evidence_confidence": 86,
        },
        "penalties": {
            "duplicate": 0,
            "routine": 0,
            "sensationalism": 0,
            "thin_evidence": 5,
        },
        "adversarial_checks": {
            "not_routine": True,
            "not_opinion": True,
            "not_duplicate": True,
            "not_single_source_social": True,
            "has_trustworthy_timestamp": True,
        },
    }

    assessment = validate_llm_breaking_assessment(payload)

    assert assessment.score == 88
    assert assessment.label == "breaking"
    assert assessment.confidence == 82
    assert assessment.dimensions["impact_scope"] == 90


def test_llm_breaking_assessment_rejects_hype_without_evidence() -> None:
    payload = {
        "breaking_score": 91,
        "breaking_label": "flash",
        "breaking_confidence": 90,
        "breaking_reason": "看起来很爆炸。",
        "dimensions": {
            "impact_scope": 95,
            "urgency": 95,
            "novelty": 95,
            "source_reliability": 10,
            "actionability": 40,
            "systemic_or_cross_border": 30,
            "human_attention": 80,
            "evidence_confidence": 15,
        },
        "penalties": {
            "duplicate": 0,
            "routine": 0,
            "sensationalism": 45,
            "thin_evidence": 60,
        },
        "adversarial_checks": {
            "not_routine": True,
            "not_opinion": True,
            "not_duplicate": True,
            "not_single_source_social": False,
            "has_trustworthy_timestamp": False,
        },
    }

    try:
        validate_llm_breaking_assessment(payload)
    except BreakingScoreValidationError as exc:
        assert "adversarial" in str(exc) or "evidence" in str(exc)
    else:  # pragma: no cover - assertion clarity
        raise AssertionError("hype-only payload should be rejected")
