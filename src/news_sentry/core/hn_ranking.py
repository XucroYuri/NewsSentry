"""Hacker News-style ranking algorithm for public news feed.

Implements the canonical HN ranking formula:

    score = (points - 1) ^ 0.8 / (age_hours + 2) ^ gravity

This module is the **single source of truth** for HN-style ranking in NewsSentry.
The TypeScript port in `frontend/public/src/lib/hn-rank.ts` must produce
identical numeric output for the same inputs.

Reference: https://medium.com/hacker-news-ranking-algorithm-8d23a857dda4

Design decisions (see docs/upgrades/hacker-news-style-upgrade-plan.md):

* ``points`` is derived from ``news_value_score`` (0-100) divided by 10, giving a
  0-10 float that mirrors HN's typical small-integer vote counts. Once Phase 2
  ships real anonymous voting, ``points`` will be ``(news_value_score / 10) +
  vote_count``.
* ``gravity`` defaults to 1.8 (the value HN has used since 2014). Higher gravity
  → faster decay → more churn on the front page.
* Negative or zero ``points - 1`` clamps to a tiny positive number to keep the
  power operation well-defined without producing NaN.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

__all__ = [
    "DEFAULT_GRAVITY",
    "DEFAULT_POINTS_DIVISOR",
    "MIN_POINTS_INPUT",
    "compute_hn_score",
    "points_from_value_score",
    "age_hours_from_published",
    "hn_score_for_event",
    "rank_public_items",
]

# HN default gravity. Higher = faster decay.
DEFAULT_GRAVITY: float = 1.8

# news_value_score (0-100) divisor used to derive initial ``points``.
# 100 / 10 = 10 points max from value_score alone.
DEFAULT_POINTS_DIVISOR: float = 10.0

# Lower bound for ``points - 1`` to keep the power well-defined.
# Also protects against negative base causing NaN for fractional exponents.
MIN_POINTS_INPUT: float = 0.0


def compute_hn_score(
    points: float,
    age_hours: float,
    *,
    gravity: float = DEFAULT_GRAVITY,
) -> float:
    """Return the canonical HN ranking score.

    Formula: ``(points - 1) ^ 0.8 / (age_hours + 2) ^ gravity``

    * ``points`` is the vote-like weight (HN uses upvote count; we derive from
      ``news_value_score``).
    * ``age_hours`` is hours since publication.
    * ``gravity`` defaults to ``DEFAULT_GRAVITY`` (1.8).

    The function never raises. Bad inputs (NaN, inf, negative age) yield ``0.0``
    so the item sinks to the bottom rather than poisoning the ranking.
    """
    if not _is_finite_number(points) or not _is_finite_number(age_hours):
        return 0.0
    if not _is_finite_number(gravity) or gravity <= 0:
        return 0.0
    if age_hours < 0:
        # Future-dated items get no boost.
        age_hours = 0.0
    base = max(points - 1.0, MIN_POINTS_INPUT)
    if base == 0.0:
        # 0 ^ 0.8 is well-defined (0), but ``(points - 1)`` of 0 represents a
        # brand-new item with no engagement; HN treats these as score 0.
        return 0.0
    try:
        numerator = base ** 0.8
        denominator = (age_hours + 2.0) ** gravity
    except (ValueError, OverflowError, ZeroDivisionError):
        return 0.0
    if denominator <= 0 or not math.isfinite(numerator) or not math.isfinite(denominator):
        return 0.0
    result: float = numerator / denominator
    return result


def points_from_value_score(
    value_score: int | float | None,
    *,
    divisor: float = DEFAULT_POINTS_DIVISOR,
    vote_count: int = 0,
) -> float:
    """Derive a HN-style ``points`` value from ``news_value_score``.

    Phase 1 (no votes yet): ``points = max(0, value_score) / divisor``.
    Phase 2 (anonymous voting): callers pass ``vote_count`` to add real votes.
    """
    if value_score is None:
        score = 0.0
    elif isinstance(value_score, bool):
        # bool is subclass of int — guard explicitly.
        score = 0.0
    elif isinstance(value_score, (int, float)):
        score = float(value_score)
    else:
        score = 0.0
    if not _is_finite_number(score) or score < 0:
        score = 0.0
    if divisor <= 0 or not _is_finite_number(divisor):
        divisor = DEFAULT_POINTS_DIVISOR
    if not isinstance(vote_count, int) or vote_count < 0:
        vote_count = 0
    return score / divisor + float(vote_count)


def age_hours_from_published(
    published_at: str | datetime | None,
    *,
    now: datetime | None = None,
) -> float:
    """Return age in hours between ``published_at`` and ``now`` (UTC).

    Returns ``0.0`` on parse failure or future-dated input so that the item
    receives no age-related penalty (best-effort recovery, not a ranking boost).
    """
    if published_at is None:
        return 0.0
    if isinstance(published_at, datetime):
        published = published_at
    else:
        parsed = _parse_iso_datetime(published_at)
        if parsed is None:
            return 0.0
        published = parsed
    if published.tzinfo is None:
        published = published.replace(tzinfo=UTC)
    current = now if now is not None else datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    delta_seconds = (current - published).total_seconds()
    if not _is_finite_number(delta_seconds) or delta_seconds < 0:
        return 0.0
    return delta_seconds / 3600.0


def hn_score_for_event(
    event: Mapping[str, Any],
    *,
    now: datetime | None = None,
    gravity: float = DEFAULT_GRAVITY,
    vote_count: int = 0,
) -> tuple[float, float, float]:
    """Compute ``(hn_score, points, age_hours)`` for a public news event.

    Accepts the raw event payload used inside ``public_news_utils``. Reads
    ``news_value_score`` (preferred) or ``importance_score`` as fallback.
    Reads ``published_at`` for age calculation.
    """
    raw_score = event.get("news_value_score")
    if raw_score is None:
        raw_score = event.get("importance_score")
    points = points_from_value_score(raw_score, vote_count=vote_count)
    age_hours = age_hours_from_published(event.get("published_at"), now=now)
    score = compute_hn_score(points, age_hours, gravity=gravity)
    return score, points, age_hours


def rank_public_items(
    items: list[Any],
    *,
    hn_score_getter: Any,
) -> list[Any]:
    """Stable-sort ``items`` by descending ``hn_score_getter(item)``.

    Stability matters: ties preserve insertion order so callers can pre-sort by
    secondary keys (e.g. ``breaking_score``) before invoking this.
    """
    decorated = [(hn_score_getter(item), idx, item) for idx, item in enumerate(items)]
    decorated.sort(key=lambda triple: (-triple[0], triple[1]))
    return [triple[2] for triple in decorated]


# ── Internal helpers ────────────────────────────────────────────────────────


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool):
        return True
    if not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


_ISO_FORMATS = (
    # ISO 8601 with timezone — preferred shape stored in NewsSentry.
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
)


def _parse_iso_datetime(value: str) -> datetime | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate:
        return None
    # Python's strptime %z accepts ``+0000`` and ``+00:00`` since 3.7+.
    for fmt in _ISO_FORMATS:
        try:
            parsed = datetime.strptime(candidate, fmt)
            return parsed
        except ValueError:
            continue
    # Last resort: fromisoformat handles most modern ISO shapes including
    # ``Z`` suffix via ``replace(..., timezone.utc)`` normalization.
    try:
        normalised = candidate.replace("Z", "+00:00")
        return datetime.fromisoformat(normalised)
    except ValueError:
        return None
