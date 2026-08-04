"""Latent news value scoring and dual-list ranking primitives.

The module keeps LLM output subordinate to calibrated numeric features: callers
may supply semantic features extracted by an LLM, but ranking is deterministic
and bounded by evidence, redundancy, and domain-relative calibration.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from news_sentry.models.newsevent import NewsEvent
from news_sentry.skills.filter.classification_taxonomy import canonical_l0

LATENT_VALUE_MODEL_VERSION = "latent-value-v1.0"


@dataclass(frozen=True)
class LatentValueFeatures:
    """0-100 semantic feature vector for one news event."""

    novelty: int | float
    urgency: int | float
    entity_prominence: int | float
    impact_scale: int | float
    irreversibility: int | float
    cross_domain_spread: int | float
    evidence_reliability: int | float
    long_term_significance: int | float
    duplicate_similarity: int | float
    propagation_velocity: int | float = 50

    @classmethod
    def neutral(cls) -> LatentValueFeatures:
        return cls(
            novelty=50,
            urgency=50,
            entity_prominence=50,
            impact_scale=50,
            irreversibility=50,
            cross_domain_spread=50,
            evidence_reliability=50,
            long_term_significance=50,
            duplicate_similarity=0,
            propagation_velocity=50,
        )

    def normalized(self) -> dict[str, int]:
        return {
            "novelty": _clamp_score(self.novelty),
            "urgency": _clamp_score(self.urgency),
            "entity_prominence": _clamp_score(self.entity_prominence),
            "impact_scale": _clamp_score(self.impact_scale),
            "irreversibility": _clamp_score(self.irreversibility),
            "cross_domain_spread": _clamp_score(self.cross_domain_spread),
            "evidence_reliability": _clamp_score(self.evidence_reliability),
            "long_term_significance": _clamp_score(self.long_term_significance),
            "duplicate_similarity": _clamp_score(self.duplicate_similarity),
            "propagation_velocity": _clamp_score(self.propagation_velocity),
        }


@dataclass(frozen=True)
class NewsValueScoreCard:
    event_id: str
    domain: str
    source_id: str
    breaking_score: int
    short_value_score: int
    mid_value_score: int
    long_value_score: int
    propagation_potential: int
    impact_potential: int
    confidence: int
    uncertainty: int
    domain_percentile: int
    redundancy_cluster: str
    evidence_quality: int
    potential_score: int
    explanation: str
    failure_flags: list[str]
    model_version: str = LATENT_VALUE_MODEL_VERSION


@dataclass(frozen=True)
class RankingConstraints:
    top_n: int = 10
    max_per_domain: int = 4
    max_per_source: int = 4


@dataclass(frozen=True)
class DualNewsRanking:
    breaking_top: list[NewsValueScoreCard]
    potential_top: list[NewsValueScoreCard]
    candidate_cards: list[NewsValueScoreCard]


@dataclass(frozen=True)
class BacktestItem:
    event_id: str
    predicted_score: int | float
    predicted_probability: int | float
    actual_relevance: int | float
    actual_label: int
    is_slow_burn: bool = False
    domain: str | None = None
    redundancy_cluster: str | None = None


@dataclass(frozen=True)
class BacktestMetrics:
    precision_at_k: float
    recall_at_k: float
    ndcg_at_k: float
    brier_score: float
    expected_calibration_error: float
    duplicate_rate_at_k: float
    domain_diversity_at_k: float
    slow_burn_recall_at_k: float


PairwiseJudge = Callable[[NewsValueScoreCard, NewsValueScoreCard], str | None]


def score_news_event(
    event: NewsEvent,
    features: LatentValueFeatures | Mapping[str, int | float],
) -> NewsValueScoreCard:
    """Score one event into a calibrated card without mutating NewsEvent."""
    feature_values = _normalize_features(features)
    propagation = _weighted_score(
        feature_values,
        {
            "propagation_velocity": 0.35,
            "urgency": 0.25,
            "novelty": 0.20,
            "entity_prominence": 0.20,
        },
    )
    impact = _weighted_score(
        feature_values,
        {
            "impact_scale": 0.30,
            "irreversibility": 0.25,
            "long_term_significance": 0.25,
            "cross_domain_spread": 0.10,
            "entity_prominence": 0.10,
        },
    )
    duplicate = feature_values["duplicate_similarity"]
    evidence = feature_values["evidence_reliability"]

    short_value = _weighted_score(
        feature_values,
        {
            "urgency": 0.34,
            "propagation_velocity": 0.25,
            "impact_scale": 0.20,
            "novelty": 0.13,
            "entity_prominence": 0.08,
        },
        penalty=duplicate * 0.18,
    )
    mid_value = _weighted_score(
        feature_values,
        {
            "impact_scale": 0.30,
            "cross_domain_spread": 0.22,
            "entity_prominence": 0.18,
            "propagation_velocity": 0.15,
            "novelty": 0.15,
        },
        penalty=duplicate * 0.16,
    )
    long_value = _weighted_score(
        feature_values,
        {
            "long_term_significance": 0.36,
            "irreversibility": 0.25,
            "impact_scale": 0.18,
            "cross_domain_spread": 0.12,
            "evidence_reliability": 0.09,
        },
        penalty=duplicate * 0.10,
    )
    breaking = _weighted_score(
        feature_values,
        {
            "urgency": 0.22,
            "novelty": 0.18,
            "impact_scale": 0.16,
            "entity_prominence": 0.12,
            "cross_domain_spread": 0.12,
            "evidence_reliability": 0.10,
            "propagation_velocity": 0.10,
        },
        penalty=duplicate * 0.22,
    )

    failure_flags = _failure_flags(feature_values, propagation, impact)
    uncertainty = _uncertainty(
        evidence=evidence,
        duplicate=duplicate,
        propagation=propagation,
        impact=impact,
    )
    confidence = _clamp_score(evidence * 0.70 + (100 - uncertainty) * 0.30)

    if evidence < 40:
        breaking = min(breaking, 59)
        short_value = min(short_value, 64)
        mid_value = min(mid_value, 64)
        long_value = min(long_value, 69)
    if duplicate >= 80:
        breaking = min(breaking, 62)

    potential_score = _clamp_score(
        short_value * 0.15
        + mid_value * 0.35
        + long_value * 0.50
        - uncertainty * 0.18
        - duplicate * 0.22
    )
    return NewsValueScoreCard(
        event_id=event.id,
        domain=_event_domain(event),
        source_id=event.source_id,
        breaking_score=breaking,
        short_value_score=short_value,
        mid_value_score=mid_value,
        long_value_score=long_value,
        propagation_potential=propagation,
        impact_potential=impact,
        confidence=confidence,
        uncertainty=uncertainty,
        domain_percentile=50,
        redundancy_cluster=event.story_id or event.cluster_id or event.id,
        evidence_quality=evidence,
        potential_score=potential_score,
        explanation=_explanation(breaking, potential_score, propagation, impact, failure_flags),
        failure_flags=failure_flags,
    )


def rank_news_values(
    events: Sequence[NewsEvent],
    features_by_event_id: Mapping[str, LatentValueFeatures | Mapping[str, int | float]],
    *,
    constraints: RankingConstraints | None = None,
    pairwise_judge: PairwiseJudge | None = None,
) -> DualNewsRanking:
    """Return Breaking and Potential ranked lists from a batch of events."""
    ranking_constraints = constraints or RankingConstraints()
    cards = [
        score_news_event(event, features_by_event_id.get(event.id, LatentValueFeatures.neutral()))
        for event in events
    ]
    calibrated = _with_domain_percentiles(cards)
    breaking_order = _ordered_cards(
        calibrated,
        lambda card: card.breaking_score * 0.80 + card.domain_percentile * 0.20,
        pairwise_judge,
    )
    potential_order = _ordered_cards(
        calibrated,
        lambda card: card.potential_score * 0.75 + card.domain_percentile * 0.25,
        pairwise_judge,
    )
    return DualNewsRanking(
        breaking_top=_select_with_constraints(breaking_order, ranking_constraints),
        potential_top=_select_with_constraints(potential_order, ranking_constraints),
        candidate_cards=calibrated,
    )


def features_from_event_metadata(event: NewsEvent) -> LatentValueFeatures:
    """Read semantic features from ``metadata["latent_value"]["features"]``.

    Missing values fall back to the neutral 50-point baseline. Values remain
    bounded to the canonical 0-100 score scale.
    """
    raw = event.metadata.get("latent_value")
    raw_features: Any = None
    if isinstance(raw, dict):
        raw_features = raw.get("features")
    if not isinstance(raw_features, dict):
        legacy_features = event.metadata.get("latent_value_features")
        raw_features = legacy_features if isinstance(legacy_features, dict) else {}

    normalized = _normalize_features(raw_features)
    return _features_from_normalized(normalized)


def score_card_to_metadata(card: NewsValueScoreCard) -> dict[str, Any]:
    """Return a JSON-serializable score-card payload for event metadata."""
    return {
        "event_id": card.event_id,
        "domain": card.domain,
        "source_id": card.source_id,
        "breaking_score": card.breaking_score,
        "short_value_score": card.short_value_score,
        "mid_value_score": card.mid_value_score,
        "long_value_score": card.long_value_score,
        "propagation_potential": card.propagation_potential,
        "impact_potential": card.impact_potential,
        "confidence": card.confidence,
        "uncertainty": card.uncertainty,
        "domain_percentile": card.domain_percentile,
        "redundancy_cluster": card.redundancy_cluster,
        "evidence_quality": card.evidence_quality,
        "potential_score": card.potential_score,
        "explanation": card.explanation,
        "failure_flags": list(card.failure_flags),
        "version": card.model_version,
    }


def annotate_event_with_latent_value(
    event: NewsEvent,
    features: LatentValueFeatures | Mapping[str, int | float] | None = None,
) -> NewsEvent:
    """Write one event's latent score-card into ``metadata["latent_value"]``."""
    feature_input = features if features is not None else features_from_event_metadata(event)
    card = score_news_event(event, feature_input)
    _write_latent_metadata(event, feature_input, card, rankings={})
    return event


def annotate_ranked_events(
    events: Sequence[NewsEvent],
    features_by_event_id: Mapping[str, LatentValueFeatures | Mapping[str, int | float]],
    *,
    constraints: RankingConstraints | None = None,
    pairwise_judge: PairwiseJudge | None = None,
) -> DualNewsRanking:
    """Rank a batch and attach score-card/rank metadata to each event."""
    ranking = rank_news_values(
        events,
        features_by_event_id,
        constraints=constraints,
        pairwise_judge=pairwise_judge,
    )
    cards_by_id = {card.event_id: card for card in ranking.candidate_cards}
    rankings_by_id: dict[str, dict[str, int]] = defaultdict(dict)
    for index, card in enumerate(ranking.breaking_top, start=1):
        rankings_by_id[card.event_id]["breaking_top_rank"] = index
    for index, card in enumerate(ranking.potential_top, start=1):
        rankings_by_id[card.event_id]["potential_top_rank"] = index

    for event in events:
        candidate_card = cards_by_id.get(event.id)
        if candidate_card is None:
            continue
        feature_input = features_by_event_id.get(event.id, LatentValueFeatures.neutral())
        _write_latent_metadata(
            event,
            feature_input,
            candidate_card,
            rankings=rankings_by_id.get(event.id, {}),
        )
    return ranking


def evaluate_backtest(items: Sequence[BacktestItem], *, k: int = 10) -> BacktestMetrics:
    """Compute top-k ranking and calibration metrics for historical replay."""
    ordered = sorted(items, key=lambda item: float(item.predicted_score), reverse=True)
    top = ordered[: max(0, k)]
    relevant_total = sum(1 for item in items if item.actual_label == 1)
    relevant_top = sum(1 for item in top if item.actual_label == 1)
    precision = relevant_top / len(top) if top else 0.0
    recall = relevant_top / relevant_total if relevant_total else 0.0
    slow_burn_total = sum(1 for item in items if item.is_slow_burn and item.actual_label == 1)
    slow_burn_top = sum(1 for item in top if item.is_slow_burn and item.actual_label == 1)
    duplicate_rate = _duplicate_rate(top)
    domain_diversity = len({item.domain for item in top if item.domain}) / len(top) if top else 0.0
    return BacktestMetrics(
        precision_at_k=precision,
        recall_at_k=recall,
        ndcg_at_k=_ndcg_at_k(ordered, k),
        brier_score=_brier_score(items),
        expected_calibration_error=_expected_calibration_error(items),
        duplicate_rate_at_k=duplicate_rate,
        domain_diversity_at_k=domain_diversity,
        slow_burn_recall_at_k=slow_burn_top / slow_burn_total if slow_burn_total else 0.0,
    )


def _normalize_features(
    features: LatentValueFeatures | Mapping[str, int | float],
) -> dict[str, int]:
    if isinstance(features, LatentValueFeatures):
        return features.normalized()
    neutral = LatentValueFeatures.neutral().normalized()
    for key in neutral:
        if key in features:
            neutral[key] = _clamp_score(features[key])
    return neutral


def _features_from_normalized(values: Mapping[str, int]) -> LatentValueFeatures:
    return LatentValueFeatures(
        novelty=values["novelty"],
        urgency=values["urgency"],
        entity_prominence=values["entity_prominence"],
        impact_scale=values["impact_scale"],
        irreversibility=values["irreversibility"],
        cross_domain_spread=values["cross_domain_spread"],
        evidence_reliability=values["evidence_reliability"],
        long_term_significance=values["long_term_significance"],
        duplicate_similarity=values["duplicate_similarity"],
        propagation_velocity=values["propagation_velocity"],
    )


def _write_latent_metadata(
    event: NewsEvent,
    features: LatentValueFeatures | Mapping[str, int | float],
    card: NewsValueScoreCard,
    *,
    rankings: Mapping[str, int],
) -> None:
    raw = event.metadata.get("latent_value")
    latent = dict(raw) if isinstance(raw, dict) else {}
    existing_rankings = latent.get("rankings")
    merged_rankings = dict(existing_rankings) if isinstance(existing_rankings, dict) else {}
    merged_rankings.update(rankings)
    latent.update(
        {
            "version": LATENT_VALUE_MODEL_VERSION,
            "features": _normalize_features(features),
            "score_card": score_card_to_metadata(card),
            "rankings": merged_rankings,
        }
    )
    event.metadata["latent_value"] = latent


def _weighted_score(
    values: Mapping[str, int],
    weights: Mapping[str, float],
    *,
    penalty: float = 0.0,
) -> int:
    weighted_sum = sum(values[key] * weight for key, weight in weights.items())
    total_weight = sum(weights.values())
    return _clamp_score((weighted_sum / total_weight) - penalty)


def _with_domain_percentiles(cards: Sequence[NewsValueScoreCard]) -> list[NewsValueScoreCard]:
    by_domain: dict[str, list[NewsValueScoreCard]] = defaultdict(list)
    for card in cards:
        by_domain[card.domain].append(card)

    percentile_by_id: dict[str, int] = {}
    for domain_cards in by_domain.values():
        ordered = sorted(domain_cards, key=lambda card: card.potential_score, reverse=True)
        if len(ordered) == 1:
            percentile_by_id[ordered[0].event_id] = 100
            continue
        denominator = len(ordered) - 1
        for index, card in enumerate(ordered):
            percentile_by_id[card.event_id] = _clamp_score(
                100 * (denominator - index) / denominator
            )

    return [
        replace(card, domain_percentile=percentile_by_id.get(card.event_id, 50))
        for card in cards
    ]


def _ordered_cards(
    cards: Sequence[NewsValueScoreCard],
    score_fn: Callable[[NewsValueScoreCard], float],
    pairwise_judge: PairwiseJudge | None,
) -> list[NewsValueScoreCard]:
    ordered = sorted(cards, key=lambda card: (score_fn(card), card.confidence), reverse=True)
    if pairwise_judge is None or len(ordered) < 2:
        return ordered

    adjusted = list(ordered)
    for index in range(len(adjusted) - 1):
        left = adjusted[index]
        right = adjusted[index + 1]
        if abs(score_fn(left) - score_fn(right)) > 3:
            continue
        preferred = pairwise_judge(left, right)
        if preferred == right.event_id:
            adjusted[index], adjusted[index + 1] = right, left
    return adjusted


def _select_with_constraints(
    ordered_cards: Sequence[NewsValueScoreCard],
    constraints: RankingConstraints,
) -> list[NewsValueScoreCard]:
    selected: list[NewsValueScoreCard] = []
    domain_counts: dict[str, int] = defaultdict(int)
    source_counts: dict[str, int] = defaultdict(int)
    clusters: set[str] = set()
    top_n = max(0, constraints.top_n)

    for card in ordered_cards:
        if len(selected) >= top_n:
            break
        if card.redundancy_cluster in clusters:
            continue
        if domain_counts[card.domain] >= constraints.max_per_domain:
            continue
        if source_counts[card.source_id] >= constraints.max_per_source:
            continue
        selected.append(card)
        domain_counts[card.domain] += 1
        source_counts[card.source_id] += 1
        clusters.add(card.redundancy_cluster)
    return selected


def _event_domain(event: NewsEvent) -> str:
    classification = event.metadata.get("classification")
    if not isinstance(classification, dict):
        return "uncategorized"
    return canonical_l0(str(classification.get("l0", "")))


def _uncertainty(*, evidence: int, duplicate: int, propagation: int, impact: int) -> int:
    disagreement = abs(propagation - impact)
    return _clamp_score((100 - evidence) * 0.65 + disagreement * 0.25 + duplicate * 0.10)


def _failure_flags(
    values: Mapping[str, int],
    propagation: int,
    impact: int,
) -> list[str]:
    flags: list[str] = []
    if values["evidence_reliability"] < 40:
        flags.append("thin_evidence")
    if values["duplicate_similarity"] >= 70:
        flags.append("redundant_story")
    if values["novelty"] < 35 and values["urgency"] < 35:
        flags.append("routine_update")
    if propagation - impact >= 35:
        flags.append("propagation_without_impact")
    if values["cross_domain_spread"] >= 75 and values["impact_scale"] >= 75:
        flags.append("cross_domain_impact")
    return flags


def _explanation(
    breaking_score: int,
    potential_score: int,
    propagation: int,
    impact: int,
    flags: Sequence[str],
) -> str:
    relation = "传播势能高于影响估计" if propagation > impact else "影响估计高于传播势能"
    caution = f"；风险标记: {', '.join(flags)}" if flags else ""
    return (
        f"Breaking {breaking_score}/100；潜在价值 {potential_score}/100；"
        f"{relation}{caution}"
    )


def _ndcg_at_k(items: Sequence[BacktestItem], k: int) -> float:
    top = list(items[: max(0, k)])
    ideal = sorted(items, key=lambda item: float(item.actual_relevance), reverse=True)[: max(0, k)]
    ideal_dcg = _dcg(ideal)
    if ideal_dcg == 0:
        return 0.0
    return _dcg(top) / ideal_dcg


def _dcg(items: Sequence[BacktestItem]) -> float:
    return sum(
        (2 ** float(item.actual_relevance) - 1) / math.log2(index + 2)
        for index, item in enumerate(items)
    )


def _brier_score(items: Sequence[BacktestItem]) -> float:
    if not items:
        return 0.0
    errors = [
        (_probability_0_1(item.predicted_probability) - _binary_label(item.actual_label)) ** 2
        for item in items
    ]
    return sum(errors) / len(errors)


def _expected_calibration_error(items: Sequence[BacktestItem], bins: int = 10) -> float:
    if not items:
        return 0.0
    total = len(items)
    error = 0.0
    for bin_index in range(bins):
        lower = bin_index / bins
        upper = (bin_index + 1) / bins
        bucket = [
            item
            for item in items
            if lower <= _probability_0_1(item.predicted_probability) < upper
            or (bin_index == bins - 1 and _probability_0_1(item.predicted_probability) == 1.0)
        ]
        if not bucket:
            continue
        confidence = sum(
            _probability_0_1(item.predicted_probability) for item in bucket
        ) / len(bucket)
        accuracy = sum(_binary_label(item.actual_label) for item in bucket) / len(bucket)
        error += (len(bucket) / total) * abs(confidence - accuracy)
    return error


def _duplicate_rate(items: Sequence[BacktestItem]) -> float:
    clusters = [item.redundancy_cluster for item in items if item.redundancy_cluster]
    if not clusters:
        return 0.0
    return 1 - (len(set(clusters)) / len(clusters))


def _probability_0_1(value: int | float) -> float:
    return _clamp_score(value) / 100


def _binary_label(value: int) -> int:
    return 1 if value == 1 else 0


def _clamp_score(value: Any, *, default: int = 0) -> int:  # noqa: ANN401
    try:
        parsed = int(round(float(value)))
    except (TypeError, ValueError):
        parsed = default
    return max(0, min(100, parsed))
