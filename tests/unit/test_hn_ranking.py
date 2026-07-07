"""Tests for ``news_sentry.core.hn_ranking``.

Covers the canonical HN ranking formula, points derivation, age calculation,
event-level scoring, and stable ranking sort.

Property: this module MUST produce identical output to the TypeScript port in
``frontend/public/src/lib/hn-rank.ts`` for the same inputs.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from news_sentry.core.hn_ranking import (
    DEFAULT_GRAVITY,
    age_hours_from_published,
    compute_hn_score,
    hn_score_for_event,
    points_from_value_score,
    rank_public_items,
)

# ── compute_hn_score ────────────────────────────────────────────────────────


class TestComputeHnScore:
    """Reference values verified against the published HN formula."""

    def test_canonical_formula_known_values(self) -> None:
        # HN FAQ: score = (p - 1)^0.8 / (t + 2)^1.8
        # votes=100, age=1h: (99)^0.8 / (3)^1.8 ≈ 39.51 / 7.22 ≈ 5.47
        assert compute_hn_score(100, 1.0) == pytest.approx(5.47, rel=0.02)
        # votes=10, age=10h: (9)^0.8 / (12)^1.8 ≈ 5.80 / 87.64 ≈ 0.0662
        assert compute_hn_score(10, 10.0) == pytest.approx(0.0662, rel=0.02)

    def test_zero_points_returns_zero(self) -> None:
        # points=0 → base = max(0 - 1, 0) = 0 → 0^0.8 = 0
        assert compute_hn_score(0, 1.0) == 0.0

    def test_one_point_returns_zero(self) -> None:
        # points=1 → base = max(0, 0) = 0 → 0^0.8 = 0
        assert compute_hn_score(1, 1.0) == 0.0

    def test_two_points_minimum_positive(self) -> None:
        # points=2 → base = 1, age=0 → 1^0.8 / 2^1.8
        expected = 1.0 / (2.0 ** DEFAULT_GRAVITY)
        assert compute_hn_score(2, 0.0) == pytest.approx(expected)

    def test_higher_points_higher_score(self) -> None:
        # Monotonic in points for fixed age.
        a = compute_hn_score(5, 1.0)
        b = compute_hn_score(50, 1.0)
        assert b > a > 0

    def test_older_age_lower_score(self) -> None:
        # Monotonic decreasing in age for fixed points.
        fresh = compute_hn_score(20, 0.5)
        stale = compute_hn_score(20, 24.0)
        assert fresh > stale > 0

    def test_higher_gravity_decays_faster(self) -> None:
        fresh = compute_hn_score(10, 1.0, gravity=1.0)
        stale_with_high_gravity = compute_hn_score(10, 12.0, gravity=1.0)
        fresh_high_gravity = compute_hn_score(10, 1.0, gravity=2.5)
        stale_high_gravity = compute_hn_score(10, 12.0, gravity=2.5)

        # Higher gravity: bigger ratio between fresh and stale.
        normal_ratio = fresh / stale_with_high_gravity
        high_gravity_ratio = fresh_high_gravity / stale_high_gravity
        assert high_gravity_ratio > normal_ratio

    def test_negative_age_clamped_to_zero(self) -> None:
        # Future-dated items get no boost — treated as age=0.
        assert compute_hn_score(10, -5.0) == compute_hn_score(10, 0.0)

    def test_nan_points_returns_zero(self) -> None:
        assert compute_hn_score(float("nan"), 1.0) == 0.0

    def test_inf_age_returns_zero(self) -> None:
        assert compute_hn_score(10, float("inf")) == 0.0

    def test_negative_gravity_returns_zero(self) -> None:
        assert compute_hn_score(10, 1.0, gravity=-1.0) == 0.0

    def test_zero_gravity_returns_zero(self) -> None:
        assert compute_hn_score(10, 1.0, gravity=0.0) == 0.0


# ── points_from_value_score ─────────────────────────────────────────────────


class TestPointsFromValueScore:
    def test_none_returns_zero(self) -> None:
        assert points_from_value_score(None) == 0.0

    def test_typical_value_score(self) -> None:
        # value_score=80, divisor=10 → points=8.0
        assert points_from_value_score(80) == 8.0

    def test_max_value_score(self) -> None:
        assert points_from_value_score(100) == 10.0

    def test_zero_value_score(self) -> None:
        assert points_from_value_score(0) == 0.0

    def test_negative_clamped_to_zero(self) -> None:
        assert points_from_value_score(-50) == 0.0

    def test_bool_treated_as_invalid(self) -> None:
        # bool is subclass of int — must be guarded.
        assert points_from_value_score(True) == 0.0
        assert points_from_value_score(False) == 0.0

    def test_nan_returns_zero(self) -> None:
        assert points_from_value_score(float("nan")) == 0.0

    def test_inf_returns_zero(self) -> None:
        assert points_from_value_score(float("inf")) == 0.0

    def test_string_returns_zero(self) -> None:
        assert points_from_value_score("80") == 0.0  # type: ignore[arg-type]

    def test_custom_divisor(self) -> None:
        assert points_from_value_score(80, divisor=20) == 4.0

    def test_zero_divisor_falls_back_to_default(self) -> None:
        assert points_from_value_score(80, divisor=0) == 8.0

    def test_with_vote_count(self) -> None:
        # Phase 2 preview: vote_count added on top of value-derived base.
        assert points_from_value_score(80, vote_count=5) == 13.0

    def test_negative_vote_count_ignored(self) -> None:
        assert points_from_value_score(80, vote_count=-3) == 8.0


# ── age_hours_from_published ────────────────────────────────────────────────


class TestAgeHoursFromPublished:
    def test_none_returns_zero(self) -> None:
        assert age_hours_from_published(None) == 0.0

    def test_invalid_string_returns_zero(self) -> None:
        assert age_hours_from_published("not-a-date") == 0.0

    def test_empty_string_returns_zero(self) -> None:
        assert age_hours_from_published("") == 0.0

    def test_iso_with_z_suffix(self) -> None:
        now = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
        published = "2026-07-07T10:00:00Z"
        assert age_hours_from_published(published, now=now) == 2.0

    def test_iso_with_offset(self) -> None:
        now = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
        published = "2026-07-07T10:00:00+00:00"
        assert age_hours_from_published(published, now=now) == 2.0

    def test_naive_datetime_treated_as_utc(self) -> None:
        now = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
        published_dt = datetime(2026, 7, 7, 10, 0, 0)  # naive
        assert age_hours_from_published(published_dt, now=now) == 2.0

    def test_aware_datetime(self) -> None:
        now = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
        published_dt = datetime(2026, 7, 7, 10, 0, 0, tzinfo=UTC)
        assert age_hours_from_published(published_dt, now=now) == 2.0

    def test_future_published_returns_zero(self) -> None:
        now = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
        future = now + timedelta(hours=5)
        assert age_hours_from_published(future, now=now) == 0.0

    def test_one_day_old(self) -> None:
        now = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
        published = "2026-07-06T12:00:00Z"
        assert age_hours_from_published(published, now=now) == pytest.approx(24.0)

    def test_date_only_format(self) -> None:
        # Accepts yyyy-mm-dd as midnight UTC.
        now = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
        published = "2026-07-06"
        assert age_hours_from_published(published, now=now) == pytest.approx(36.0)

    def test_naive_now_treated_as_utc(self) -> None:
        # Both naive → both treated as UTC.
        published_dt = datetime(2026, 7, 7, 10, 0, 0)
        now_naive = datetime(2026, 7, 7, 12, 0, 0)
        assert age_hours_from_published(published_dt, now=now_naive) == 2.0


# ── hn_score_for_event ──────────────────────────────────────────────────────


class TestHnScoreForEvent:
    def test_typical_event(self) -> None:
        now = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
        event = {
            "news_value_score": 80,
            "published_at": "2026-07-07T10:00:00Z",
        }
        score, points, age = hn_score_for_event(event, now=now)
        assert points == 8.0
        assert age == 2.0
        # (8 - 1)^0.8 / (2 + 2)^1.8
        expected = (7.0 ** 0.8) / (4.0 ** DEFAULT_GRAVITY)
        assert score == pytest.approx(expected)

    def test_fallback_to_importance_score(self) -> None:
        now = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
        event = {
            "importance_score": 60,
            "published_at": "2026-07-07T10:00:00Z",
        }
        _score, points, _age = hn_score_for_event(event, now=now)
        assert points == 6.0

    def test_missing_score_returns_zero_points(self) -> None:
        now = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
        event = {"published_at": "2026-07-07T10:00:00Z"}
        score, points, _age = hn_score_for_event(event, now=now)
        assert points == 0.0
        assert score == 0.0  # points=0 → score=0

    def test_missing_published_at_treated_as_now(self) -> None:
        now = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
        event = {"news_value_score": 70}
        score, points, age = hn_score_for_event(event, now=now)
        assert points == 7.0
        assert age == 0.0
        expected = (6.0 ** 0.8) / (2.0 ** DEFAULT_GRAVITY)
        assert score == pytest.approx(expected)

    def test_with_vote_count(self) -> None:
        now = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
        event = {
            "news_value_score": 80,
            "published_at": "2026-07-07T10:00:00Z",
        }
        _score, points, _age = hn_score_for_event(event, now=now, vote_count=2)
        assert points == 10.0  # 8 from value_score + 2 votes


# ── rank_public_items ───────────────────────────────────────────────────────


class TestRankPublicItems:
    def test_sorts_by_score_descending(self) -> None:
        items = [
            {"id": "a", "score": 0.5},
            {"id": "b", "score": 2.0},
            {"id": "c", "score": 1.0},
        ]
        ranked = rank_public_items(items, hn_score_getter=lambda x: x["score"])
        assert [item["id"] for item in ranked] == ["b", "c", "a"]

    def test_ties_preserve_insertion_order(self) -> None:
        # Stability check — equal scores preserve original order.
        items = [
            {"id": "first", "score": 1.0},
            {"id": "second", "score": 1.0},
            {"id": "third", "score": 1.0},
        ]
        ranked = rank_public_items(items, hn_score_getter=lambda x: x["score"])
        assert [item["id"] for item in ranked] == ["first", "second", "third"]

    def test_empty_list(self) -> None:
        ranked = rank_public_items([], hn_score_getter=lambda x: 0)
        assert ranked == []

    def test_single_item(self) -> None:
        items = [{"id": "solo", "score": 5.0}]
        ranked = rank_public_items(items, hn_score_getter=lambda x: x["score"])
        assert ranked == items

    def test_zero_score_items_kept_in_order(self) -> None:
        items = [
            {"id": "a", "score": 0.0},
            {"id": "b", "score": 0.0},
        ]
        ranked = rank_public_items(items, hn_score_getter=lambda x: x["score"])
        assert [item["id"] for item in ranked] == ["a", "b"]

    def test_negative_scores_supported(self) -> None:
        items = [
            {"id": "neg", "score": -1.0},
            {"id": "zero", "score": 0.0},
        ]
        ranked = rank_public_items(items, hn_score_getter=lambda x: x["score"])
        assert [item["id"] for item in ranked] == ["zero", "neg"]

    def test_does_not_mutate_input(self) -> None:
        items = [
            {"id": "a", "score": 1.0},
            {"id": "b", "score": 2.0},
        ]
        original_order = [item["id"] for item in items]
        rank_public_items(items, hn_score_getter=lambda x: x["score"])
        assert [item["id"] for item in items] == original_order


# ── Cross-module consistency (parity with TS port) ──────────────────────────


class TestParityContract:
    """Lock-step parity with frontend/public/src/lib/hn-rank.ts.

    Each test documents a value that must match exactly between Python and TS.
    If this test changes, the TS port must change too.
    """

    @pytest.mark.parametrize(
        ("points", "age_hours"),
        [
            (10, 1.0),
            (50, 5.0),
            (8, 2.0),
            (3, 24.0),
            (1, 0.0),
        ],
    )
    def test_parity_compute_hn_score(self, points: float, age_hours: float) -> None:
        # Document expected values; if Python changes, TS port is out of sync.
        actual = compute_hn_score(points, age_hours)
        # Re-derive independently to catch accidental formula changes.
        expected = (
            (max(points - 1.0, 0.0)) ** 0.8
        ) / ((age_hours + 2.0) ** DEFAULT_GRAVITY)
        if max(points - 1.0, 0.0) == 0.0:
            expected = 0.0
        assert math.isfinite(actual)
        assert actual == pytest.approx(expected, rel=1e-9)
