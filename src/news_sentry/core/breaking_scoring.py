"""Breaking News scoring primitives for public News Sentry surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

BREAKING_SCORE_VERSION = "breaking-v2.0"

BREAKING_DIMENSION_WEIGHTS: dict[str, int] = {
    "impact_scope": 22,
    "urgency": 16,
    "novelty": 15,
    "source_reliability": 12,
    "actionability": 11,
    "systemic_or_cross_border": 10,
    "human_attention": 8,
    "evidence_confidence": 6,
}

BREAKING_PENALTY_WEIGHTS: dict[str, int] = {
    "duplicate": 10,
    "routine": 12,
    "sensationalism": 8,
    "thin_evidence": 10,
}

BreakingLabel = Literal["flash", "breaking", "watch", "timeline"]


class BreakingScoreValidationError(ValueError):
    """Raised when an LLM breaking assessment fails contract checks."""


@dataclass(frozen=True)
class BreakingScoreInput:
    target_id: str
    source_type: str = "unknown"
    credibility_label: str | None = None
    value_score: float | int | None = None
    published_age_minutes: int | None = None
    classification_l0: str | None = None
    issue_tags: list[str] | None = None
    related_tags: list[str] | None = None
    summary: str | None = None
    recommendation_reason: str | None = None
    duplicate_count: int = 0
    is_opinion: bool = False
    is_social_single_source: bool = False
    has_trustworthy_timestamp: bool = True


@dataclass(frozen=True)
class BreakingAssessment:
    score: int
    label: BreakingLabel
    confidence: int
    reason: str
    dimensions: dict[str, int]
    penalties: dict[str, int]
    version: str = BREAKING_SCORE_VERSION
    raw_score: int | None = None
    percentile: float | None = None
    calibrated_score: int | None = None


@dataclass(frozen=True)
class BreakingScoreStats:
    scope_key: str
    window_days: int
    mean_score: float = 0.0
    stddev_score: float = 0.0
    p50: float = 0.0
    p75: float = 0.0
    p90: float = 0.0
    p95: float = 0.0
    sample_count: int = 0


def _clamp_score(value: Any, *, default: int = 0) -> int:  # noqa: ANN401
    try:
        parsed = int(round(float(value)))
    except (TypeError, ValueError):
        parsed = default
    return max(0, min(100, parsed))


def _label_for_score(score: int, confidence: int = 80) -> BreakingLabel:
    if score >= 85 and confidence >= 70:
        return "flash"
    if score >= 72 and confidence >= 60:
        return "breaking"
    if score >= 52:
        return "watch"
    return "timeline"


def _interpolated_percentile(score: int, stats: BreakingScoreStats) -> float:
    if stats.sample_count < 30:
        return float(score)
    checkpoints = [
        (0.0, 0.0),
        (float(stats.p50 or stats.mean_score or 50), 50.0),
        (float(stats.p75 or stats.p50 or stats.mean_score or 60), 75.0),
        (float(stats.p90 or stats.p75 or stats.mean_score or 72), 90.0),
        (float(stats.p95 or stats.p90 or stats.mean_score or 85), 95.0),
        (100.0, 100.0),
    ]
    checkpoints.sort(key=lambda item: item[0])
    previous_score, previous_pct = checkpoints[0]
    for next_score, next_pct in checkpoints[1:]:
        if score <= next_score:
            span = max(1.0, next_score - previous_score)
            ratio = (score - previous_score) / span
            return max(0.0, min(100.0, previous_pct + (next_pct - previous_pct) * ratio))
        previous_score, previous_pct = next_score, next_pct
    return 100.0


def _label_for_calibrated_score(
    score: int,
    *,
    percentile: float,
    confidence: int,
) -> BreakingLabel:
    if score >= 85 and percentile >= 95 and confidence >= 70:
        return "flash"
    if score >= 72 and percentile >= 90 and confidence >= 60:
        return "breaking"
    if score >= 52 or percentile >= 75:
        return "watch"
    return "timeline"


def calibrate_breaking_assessment(
    assessment: BreakingAssessment,
    stats: BreakingScoreStats | None,
) -> BreakingAssessment:
    """Blend raw score with rolling distribution percentile for public ordering."""
    raw_score = _clamp_score(assessment.raw_score or assessment.score)
    if stats is None or stats.sample_count < 30:
        percentile = float(raw_score)
    else:
        percentile = _interpolated_percentile(raw_score, stats)
    calibrated_score = _clamp_score((raw_score * 0.7) + (percentile * 0.3))
    label = _label_for_calibrated_score(
        calibrated_score,
        percentile=percentile,
        confidence=assessment.confidence,
    )
    return BreakingAssessment(
        score=calibrated_score,
        label=label,
        confidence=assessment.confidence,
        reason=assessment.reason,
        dimensions=assessment.dimensions,
        penalties=assessment.penalties,
        version=BREAKING_SCORE_VERSION,
        raw_score=raw_score,
        percentile=round(percentile, 2),
        calibrated_score=calibrated_score,
    )


def _source_reliability(source_type: str, credibility_label: str | None) -> int:
    label = (credibility_label or "").lower()
    if label in {"high", "trusted", "official", "authority"}:
        return 90
    source = source_type.lower()
    if source == "official":
        return 92
    if source in {"api", "rss"}:
        return 78
    if source == "social":
        return 45
    return 55


def _urgency_from_age(age_minutes: int | None) -> int:
    if age_minutes is None:
        return 50
    if age_minutes <= 15:
        return 95
    if age_minutes <= 60:
        return 85
    if age_minutes <= 6 * 60:
        return 65
    if age_minutes <= 24 * 60:
        return 45
    return 20


def _impact_from_tags(input_data: BreakingScoreInput) -> int:
    base = _clamp_score(input_data.value_score, default=50)
    tags = {tag.lower() for tag in (input_data.issue_tags or []) + (input_data.related_tags or [])}
    high_impact_markers = {
        "international_relations",
        "security",
        "military",
        "finance",
        "energy",
        "public_safety",
        "supply_chain",
        "国际关系",
        "公共安全",
        "军事防务",
        "金融市场",
        "能源",
        "供应链",
    }
    if tags & high_impact_markers:
        base += 10
    if input_data.related_tags:
        base += min(8, len(input_data.related_tags) * 2)
    return _clamp_score(base)


def _novelty(input_data: BreakingScoreInput) -> int:
    score = 82
    if input_data.duplicate_count:
        score -= min(55, input_data.duplicate_count * 12)
    if (input_data.classification_l0 or "").lower() in {"other", "uncategorized", "breaking_news"}:
        score -= 20
    return _clamp_score(score)


def _actionability(input_data: BreakingScoreInput) -> int:
    text = f"{input_data.summary or ''} {input_data.recommendation_reason or ''}".lower()
    markers = (
        "policy",
        "market",
        "risk",
        "supply",
        "security",
        "监管",
        "政策",
        "市场",
        "风险",
        "供应",
        "安全",
    )
    return 78 if any(marker in text for marker in markers) else 55


def _penalties(input_data: BreakingScoreInput) -> dict[str, int]:
    routine = 0
    if (input_data.classification_l0 or "").lower() in {"other", "uncategorized"}:
        routine += 35
    if input_data.is_opinion:
        routine += 45
    thin_evidence = 0
    if not input_data.summary or not input_data.recommendation_reason:
        thin_evidence += 35
    if input_data.is_social_single_source:
        thin_evidence += 35
    if not input_data.has_trustworthy_timestamp:
        thin_evidence += 30
    return {
        "duplicate": _clamp_score(input_data.duplicate_count * 18),
        "routine": _clamp_score(routine),
        "sensationalism": 0,
        "thin_evidence": _clamp_score(thin_evidence),
    }


def score_breaking_event(input_data: BreakingScoreInput) -> BreakingAssessment:
    """Return a deterministic first-pass Breaking assessment."""
    dimensions = {
        "impact_scope": _impact_from_tags(input_data),
        "urgency": _urgency_from_age(input_data.published_age_minutes),
        "novelty": _novelty(input_data),
        "source_reliability": _source_reliability(
            input_data.source_type, input_data.credibility_label
        ),
        "actionability": _actionability(input_data),
        "systemic_or_cross_border": 78 if input_data.related_tags else 45,
        "human_attention": min(90, _impact_from_tags(input_data) + 5),
        "evidence_confidence": 85 if input_data.has_trustworthy_timestamp else 35,
    }
    penalties = _penalties(input_data)
    weighted = sum(
        dimensions[key] * weight for key, weight in BREAKING_DIMENSION_WEIGHTS.items()
    ) / sum(BREAKING_DIMENSION_WEIGHTS.values())
    penalty = sum(
        penalties[key] * weight for key, weight in BREAKING_PENALTY_WEIGHTS.items()
    ) / sum(BREAKING_PENALTY_WEIGHTS.values())
    score = _clamp_score(weighted - penalty)
    confidence = _clamp_score(
        (dimensions["source_reliability"] + dimensions["evidence_confidence"]) / 2
    )
    return BreakingAssessment(
        score=score,
        label=_label_for_score(score, confidence),
        confidence=confidence,
        reason="deterministic breaking pre-score",
        dimensions=dimensions,
        penalties=penalties,
    )


def _require_mapping(value: Any, name: str) -> dict[str, Any]:  # noqa: ANN401
    if not isinstance(value, dict):
        raise BreakingScoreValidationError(f"{name} must be an object")
    return value


def validate_llm_breaking_assessment(payload: dict[str, Any]) -> BreakingAssessment:
    """Validate an LLM-generated Breaking assessment."""
    dimensions_raw = _require_mapping(payload.get("dimensions"), "dimensions")
    penalties_raw = _require_mapping(payload.get("penalties"), "penalties")
    checks = _require_mapping(payload.get("adversarial_checks"), "adversarial_checks")
    dimensions = {
        key: _clamp_score(dimensions_raw.get(key))
        for key in BREAKING_DIMENSION_WEIGHTS
    }
    penalties = {
        key: _clamp_score(penalties_raw.get(key))
        for key in BREAKING_PENALTY_WEIGHTS
    }
    score = _clamp_score(payload.get("breaking_score"))
    confidence = _clamp_score(payload.get("breaking_confidence"))
    label = str(payload.get("breaking_label") or _label_for_score(score, confidence)).strip()
    if label not in {"flash", "breaking", "watch", "timeline"}:
        raise BreakingScoreValidationError(f"unsupported breaking label: {label}")
    required_true = (
        "not_routine",
        "not_opinion",
        "not_duplicate",
        "not_single_source_social",
        "has_trustworthy_timestamp",
    )
    failed_checks = [key for key in required_true if checks.get(key) is not True]
    if failed_checks and score >= 70:
        raise BreakingScoreValidationError(
            f"adversarial checks failed for high breaking score: {', '.join(failed_checks)}"
        )
    if dimensions["evidence_confidence"] < 40 and score >= 70:
        raise BreakingScoreValidationError("evidence confidence too low for high breaking score")
    if penalties["thin_evidence"] >= 50 and score >= 70:
        raise BreakingScoreValidationError("thin evidence penalty too high for high breaking score")
    if penalties["sensationalism"] >= 40 and score >= 70:
        raise BreakingScoreValidationError(
            "sensationalism penalty too high for high breaking score"
        )
    reason = " ".join(str(payload.get("breaking_reason") or "").split())
    if len(reason) < 12:
        raise BreakingScoreValidationError("breaking reason is too short")

    return BreakingAssessment(
        score=score,
        label=label,  # type: ignore[arg-type]
        confidence=confidence,
        reason=reason,
        dimensions=dimensions,
        penalties=penalties,
    )
