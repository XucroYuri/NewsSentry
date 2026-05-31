"""Tests for lightweight deterministic event clustering."""

from __future__ import annotations

from datetime import UTC, datetime

from news_sentry.models.newsevent import Language, NewsEvent, PipelineStage
from news_sentry.skills.filter.event_clustering import assign_lightweight_clusters


def _make_event(
    event_id: str,
    source_id: str,
    title: str,
    classification: dict[str, object] | None = None,
) -> NewsEvent:
    now = datetime(2026, 5, 29, 12, 0, tzinfo=UTC).isoformat()
    return NewsEvent(
        id=event_id,
        run_id="run-cluster-test",
        source_id=source_id,
        url=f"https://example.com/{event_id}",
        title_original=title,
        content_original=title,
        language=Language.EN,
        published_at=now,
        collected_at=now,
        pipeline_stage=PipelineStage.FILTERED,
        metadata={"classification": classification or {"l0": "international-relations"}},
    )


def test_similar_multilingual_titles_from_multiple_sources_cluster_together():
    events = [
        _make_event(
            "evt-en",
            "source-a",
            "Italian contractor killed in Ukraine",
            {"l0": "international-relations", "l1": [{"code": "russia-ukraine"}]},
        ),
        _make_event(
            "evt-it",
            "source-b",
            "Contractor italiano ucciso in Ucraina",
            {"l0": "international-relations", "l1": [{"code": "russia-ukraine"}]},
        ),
    ]

    clustered = assign_lightweight_clusters(events, target_id="italy")

    assert clustered[0].cluster_id == clustered[1].cluster_id
    assert clustered[0].story_id == clustered[1].story_id
    assert clustered[0].metadata["clustering"]["cluster_type"] == "same_event"
    assert clustered[0].metadata["clustering"]["confidence"] >= 80
    assert "source_diversity" in clustered[0].metadata["clustering"]["matched_by"]
    assert "source_diversity" in clustered[1].metadata["clustering"]["matched_by"]


def test_unrelated_events_stay_in_separate_clusters():
    events = [
        _make_event(
            "evt-economy",
            "source-a",
            "Italian exports rise after new trade agreement",
            {"l0": "economy", "l1": [{"code": "trade"}]},
        ),
        _make_event(
            "evt-security",
            "source-b",
            "Police arrest mafia fugitive near Naples",
            {"l0": "public-safety", "l1": [{"code": "organized-crime"}]},
        ),
    ]

    clustered = assign_lightweight_clusters(events, target_id="italy")

    assert clustered[0].cluster_id != clustered[1].cluster_id
    assert clustered[0].story_id != clustered[1].story_id


def test_broad_l0_and_generic_shared_phrasing_do_not_cluster():
    events = [
        _make_event(
            "evt-trade",
            "source-a",
            "Italian government approves new China trade deal",
            {"l0": "economy", "l1": [{"code": "china-trade"}]},
        ),
        _make_event(
            "evt-budget",
            "source-b",
            "Italian government approves new national budget",
            {"l0": "economy", "l1": [{"code": "fiscal-policy"}]},
        ),
    ]

    clustered = assign_lightweight_clusters(events, target_id="italy")

    assert clustered[0].cluster_id != clustered[1].cluster_id
    assert clustered[0].story_id != clustered[1].story_id


def test_existing_clustering_metadata_keys_are_preserved():
    event = _make_event(
        "evt-existing-meta",
        "source-a",
        "Italian contractor killed in Ukraine",
    )
    event.metadata["clustering"] = {"review_note": "keep this"}

    clustered = assign_lightweight_clusters([event], target_id="italy")

    assert clustered[0].metadata["clustering"]["review_note"] == "keep this"
    assert clustered[0].metadata["clustering"]["cluster_size"] == 1
    assert clustered[0].metadata["clustering"]["cluster_type"] == "single_event"


def test_malformed_clustering_metadata_is_replaced_with_diagnostics():
    event = _make_event(
        "evt-malformed-meta",
        "source-a",
        "Italian contractor killed in Ukraine",
    )
    event.metadata["clustering"] = "legacy-value"

    clustered = assign_lightweight_clusters([event], target_id="italy")

    assert clustered[0].metadata["clustering"]["cluster_size"] == 1
    assert clustered[0].metadata["clustering"]["cluster_type"] == "single_event"


def test_stable_ids_repeat_across_calls_and_input_order():
    first = [
        _make_event("evt-en", "source-a", "Italian contractor killed in Ukraine"),
        _make_event("evt-it", "source-b", "Contractor italiano ucciso in Ucraina"),
    ]
    second = [
        _make_event("evt-it", "source-b", "Contractor italiano ucciso in Ucraina"),
        _make_event("evt-en", "source-a", "Italian contractor killed in Ukraine"),
    ]

    first_by_id = {
        event.id: event for event in assign_lightweight_clusters(first, target_id="italy")
    }
    second_by_id = {
        event.id: event for event in assign_lightweight_clusters(second, target_id="italy")
    }

    assert first_by_id["evt-en"].cluster_id == second_by_id["evt-en"].cluster_id
    assert first_by_id["evt-it"].story_id == second_by_id["evt-it"].story_id
