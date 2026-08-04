from __future__ import annotations

from news_sentry.core.latent_value_model import (
    BacktestItem,
    LatentValueFeatures,
    RankingConstraints,
    annotate_event_with_latent_value,
    annotate_ranked_events,
    evaluate_backtest,
    features_from_event_metadata,
    rank_news_values,
    score_news_event,
)
from news_sentry.models.newsevent import Language, NewsEvent, PipelineStage


def _event(
    event_id: str,
    title: str,
    *,
    source_id: str = "wire",
    domain: str = "politics",
    cluster_id: str | None = None,
) -> NewsEvent:
    return NewsEvent(
        id=event_id,
        run_id="run-latent",
        source_id=source_id,
        url=f"https://example.com/{event_id}",
        title_original=title,
        content_original=f"{title} summary",
        language=Language.EN,
        published_at="2026-07-03T06:00:00+00:00",
        collected_at="2026-07-03T06:02:00+00:00",
        pipeline_stage=PipelineStage.FILTERED,
        cluster_id=cluster_id,
        metadata={"classification": {"l0": domain}},
    )


def test_score_card_separates_propagation_from_structural_impact() -> None:
    viral_weak = score_news_event(
        _event("ne-viral-weak", "Viral rumor spreads across social platforms", domain="society"),
        LatentValueFeatures(
            novelty=88,
            urgency=92,
            entity_prominence=68,
            impact_scale=54,
            irreversibility=30,
            cross_domain_spread=72,
            evidence_reliability=28,
            long_term_significance=22,
            duplicate_similarity=15,
            propagation_velocity=96,
        ),
    )
    structural_policy = score_news_event(
        _event(
            "ne-policy",
            "Central bank opens new cross-border settlement regime",
            domain="economy",
        ),
        LatentValueFeatures(
            novelty=73,
            urgency=48,
            entity_prominence=88,
            impact_scale=92,
            irreversibility=84,
            cross_domain_spread=76,
            evidence_reliability=94,
            long_term_significance=95,
            duplicate_similarity=0,
            propagation_velocity=45,
        ),
    )

    assert viral_weak.propagation_potential > viral_weak.impact_potential
    assert "thin_evidence" in viral_weak.failure_flags
    assert viral_weak.breaking_score < 70
    assert structural_policy.impact_potential > structural_policy.propagation_potential
    assert structural_policy.long_value_score >= 85
    assert structural_policy.evidence_quality == 94


def test_dual_rankings_apply_domain_percentiles_and_redundancy_constraints() -> None:
    events = [
        _event(
            "ne-breaking-1",
            "President announces emergency security measure",
            domain="politics",
            cluster_id="story-a",
        ),
        _event(
            "ne-breaking-dup",
            "Emergency security measure live update",
            domain="politics",
            cluster_id="story-a",
        ),
        _event(
            "ne-routine",
            "Parliament releases routine weekly agenda",
            domain="politics",
            cluster_id="story-routine",
        ),
        _event(
            "ne-long",
            "New semiconductor export rule reshapes supply chains",
            domain="tech",
            cluster_id="story-tech",
        ),
        _event(
            "ne-market",
            "Market regulator freezes major exchange",
            domain="economy",
            cluster_id="story-market",
        ),
    ]
    features = {
        "ne-breaking-1": LatentValueFeatures(95, 96, 90, 88, 72, 86, 91, 62, 0, 84),
        "ne-breaking-dup": LatentValueFeatures(94, 95, 89, 86, 70, 84, 90, 60, 90, 82),
        "ne-routine": LatentValueFeatures(28, 30, 45, 38, 20, 30, 80, 25, 10, 25),
        "ne-long": LatentValueFeatures(78, 42, 92, 91, 86, 88, 89, 96, 0, 55),
        "ne-market": LatentValueFeatures(84, 82, 80, 85, 64, 76, 84, 68, 0, 80),
    }

    result = rank_news_values(
        events,
        features,
        constraints=RankingConstraints(top_n=3, max_per_domain=2, max_per_source=3),
    )

    breaking_ids = [card.event_id for card in result.breaking_top]
    potential_ids = [card.event_id for card in result.potential_top]
    candidate_by_id = {card.event_id: card for card in result.candidate_cards}

    assert breaking_ids[0] == "ne-breaking-1"
    assert "ne-breaking-dup" not in breaking_ids
    assert "ne-long" in potential_ids
    assert candidate_by_id["ne-breaking-1"].domain_percentile == 100
    assert candidate_by_id["ne-routine"].domain_percentile == 0
    assert len({card.redundancy_cluster for card in result.breaking_top}) == len(
        result.breaking_top
    )


def test_backtest_metrics_cover_top_k_calibration_and_slow_burn_recall() -> None:
    metrics = evaluate_backtest(
        [
            BacktestItem(
                "a",
                predicted_score=95,
                predicted_probability=90,
                actual_relevance=3,
                actual_label=1,
            ),
            BacktestItem(
                "b",
                predicted_score=88,
                predicted_probability=75,
                actual_relevance=2,
                actual_label=1,
            ),
            BacktestItem(
                "c",
                predicted_score=60,
                predicted_probability=70,
                actual_relevance=0,
                actual_label=0,
            ),
            BacktestItem(
                "d",
                predicted_score=42,
                predicted_probability=35,
                actual_relevance=3,
                actual_label=1,
                is_slow_burn=True,
            ),
        ],
        k=3,
    )

    assert metrics.precision_at_k == 2 / 3
    assert metrics.recall_at_k == 2 / 3
    assert 0 < metrics.ndcg_at_k <= 1
    assert 0 <= metrics.brier_score <= 1
    assert 0 <= metrics.expected_calibration_error <= 1
    assert metrics.slow_burn_recall_at_k == 0


def test_features_from_metadata_clamps_llm_feature_namespace() -> None:
    event = _event("ne-meta", "Metadata features", domain="tech")
    event.metadata["latent_value"] = {
        "features": {
            "novelty": 140,
            "urgency": 72,
            "entity_prominence": 65,
            "impact_scale": 58,
            "irreversibility": 44,
            "cross_domain_spread": 52,
            "evidence_reliability": -10,
            "long_term_significance": 80,
            "duplicate_similarity": 15,
        }
    }

    features = features_from_event_metadata(event)

    normalized = features.normalized()
    assert normalized["novelty"] == 100
    assert normalized["evidence_reliability"] == 0
    assert normalized["propagation_velocity"] == 50


def test_annotate_event_writes_latent_metadata_without_top_level_score_mutation() -> None:
    event = _event("ne-annotate", "Official long horizon policy", domain="economy")
    event.news_value_score = 42
    event.metadata["latent_value"] = {
        "features": {
            "novelty": 76,
            "urgency": 42,
            "entity_prominence": 88,
            "impact_scale": 90,
            "irreversibility": 86,
            "cross_domain_spread": 82,
            "evidence_reliability": 94,
            "long_term_significance": 96,
            "duplicate_similarity": 0,
            "propagation_velocity": 48,
        }
    }

    annotated = annotate_event_with_latent_value(event)

    latent = annotated.metadata["latent_value"]
    assert annotated.news_value_score == 42
    assert latent["version"] == "latent-value-v1.0"
    assert latent["score_card"]["event_id"] == "ne-annotate"
    assert latent["score_card"]["impact_potential"] > latent["score_card"]["propagation_potential"]
    assert latent["score_card"]["long_value_score"] >= 85
    assert latent["features"]["evidence_reliability"] == 94


def test_annotate_ranked_events_writes_dual_rank_metadata() -> None:
    events = [
        _event("ne-fast", "Government declares national emergency", cluster_id="story-fast"),
        _event("ne-fast-copy", "National emergency live blog", cluster_id="story-fast"),
        _event("ne-deep", "AI chip export controls reshape supply chain", domain="tech"),
    ]
    features = {
        "ne-fast": LatentValueFeatures(96, 98, 90, 88, 76, 86, 92, 65, 0, 85),
        "ne-fast-copy": LatentValueFeatures(95, 97, 88, 86, 74, 84, 92, 63, 90, 84),
        "ne-deep": LatentValueFeatures(80, 44, 92, 91, 88, 90, 90, 97, 0, 58),
    }

    ranking = annotate_ranked_events(
        events,
        features,
        constraints=RankingConstraints(top_n=2, max_per_domain=2, max_per_source=3),
    )

    assert [card.event_id for card in ranking.breaking_top] == ["ne-fast", "ne-deep"]
    assert events[0].metadata["latent_value"]["rankings"]["breaking_top_rank"] == 1
    assert "breaking_top_rank" not in events[1].metadata["latent_value"]["rankings"]
    assert events[2].metadata["latent_value"]["rankings"]["potential_top_rank"] == 1
