"""Lightweight deterministic clustering for filtered news events."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from news_sentry.models.newsevent import NewsEvent
from news_sentry.skills.filter.classification_taxonomy import classification_terms

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_STOPWORDS = {
    "a",
    "after",
    "and",
    "at",
    "by",
    "for",
    "from",
    "il",
    "in",
    "la",
    "le",
    "near",
    "new",
    "of",
    "on",
    "the",
    "to",
    "with",
}

_GENERIC_EVENT_TOKENS = {
    "announce",
    "announced",
    "announces",
    "approve",
    "approved",
    "approves",
    "deal",
    "government",
    "minister",
    "ministry",
    "national",
    "news",
    "official",
    "officials",
    "report",
    "reports",
    "say",
    "says",
}

_BROAD_CLASSIFICATION_TERMS = {
    "china-related",
    "economics",
    "economy",
    "environment",
    "international",
    "international-relations",
    "politics",
    "public-safety",
    "security",
    "society",
    "tech",
}


def assign_lightweight_clusters(events: list[NewsEvent], target_id: str) -> list[NewsEvent]:
    """Assign deterministic local cluster/story identifiers to a batch of events.

    The helper intentionally uses only small text heuristics. It is meant to catch
    obvious same-event duplicates inside the current batch, not to solve broad
    semantic similarity.
    """
    if not events:
        return events

    profiles = [_event_profile(event) for event in events]
    parent = list(range(len(events)))

    for left_index in range(len(events)):
        for right_index in range(left_index + 1, len(events)):
            if _same_event(profiles[left_index], profiles[right_index]):
                _union(parent, left_index, right_index)

    components: dict[int, list[int]] = defaultdict(list)
    for index in range(len(events)):
        components[_find(parent, index)].append(index)

    clustered_at = datetime.now(UTC).isoformat()
    for indexes in components.values():
        component_profiles = [profiles[index] for index in indexes]
        cluster_id = _stable_id("cluster", target_id, component_profiles)
        story_id = _stable_id("story", target_id, component_profiles)
        sources = {events[index].source_id for index in indexes}
        is_grouped = len(indexes) > 1

        matched_by = ["title_similarity"]
        if len(sources) > 1:
            matched_by.append("source_diversity")
        if _component_terms(component_profiles):
            matched_by.append("classification_terms")

        confidence = _component_confidence(component_profiles, is_grouped)
        reason = (
            "Grouped by compatible classification and normalized title overlap."
            if is_grouped
            else "No similar batch events matched lightweight clustering thresholds."
        )

        for index in indexes:
            event = events[index]
            event.cluster_id = cluster_id
            event.story_id = story_id
            clustering = event.metadata.get("clustering")
            if not isinstance(clustering, dict):
                clustering = {}
                event.metadata["clustering"] = clustering
            clustering.update(
                {
                    "cluster_type": "same_event" if is_grouped else "single_event",
                    "cluster_size": len(indexes),
                    "confidence": confidence,
                    "matched_by": matched_by,
                    "reason": reason,
                    "clustered_at": clustered_at,
                }
            )

    return events


def _event_profile(event: NewsEvent) -> dict[str, Any]:
    title = event.title_translated or event.title_original
    tokens = _tokens(title)
    terms = set(classification_terms(event.metadata.get("classification")))
    return {
        "event_id": event.id,
        "tokens": tokens,
        "terms": terms,
        "specific_terms": terms - _BROAD_CLASSIFICATION_TERMS,
    }


def _tokens(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", text.lower())
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    tokens = set(_TOKEN_RE.findall(ascii_text))
    return {
        token
        for token in tokens
        if len(token) > 2 and token not in _STOPWORDS and token not in _GENERIC_EVENT_TOKENS
    }


def _same_event(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_terms = left["terms"]
    right_terms = right["terms"]
    if left_terms and right_terms and not left_terms.intersection(right_terms):
        return False

    left_tokens = left["tokens"]
    right_tokens = right["tokens"]
    if not left_tokens or not right_tokens:
        return False

    overlap = left_tokens.intersection(right_tokens)
    smaller = min(len(left_tokens), len(right_tokens))
    overlap_ratio = len(overlap) / smaller
    jaccard = len(overlap) / len(left_tokens.union(right_tokens))
    shared_specific_terms = left["specific_terms"].intersection(right["specific_terms"])

    if shared_specific_terms:
        return len(overlap) >= 2 and (overlap_ratio >= 0.5 or jaccard >= 0.4)

    return len(overlap) >= 4 and overlap_ratio >= 0.8 and jaccard >= 0.7


def _stable_id(prefix: str, target_id: str, profiles: list[dict[str, Any]]) -> str:
    token_parts = sorted(_component_tokens(profiles))
    term_parts = sorted(_component_terms(profiles))
    fallback_parts = sorted(str(profile["event_id"]) for profile in profiles)
    signature = "|".join([target_id, ",".join(term_parts), ",".join(token_parts or fallback_parts)])
    digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{target_id}-{digest}"


def _component_tokens(profiles: list[dict[str, Any]]) -> set[str]:
    if not profiles:
        return set()
    common = set(profiles[0]["tokens"])
    for profile in profiles[1:]:
        common &= profile["tokens"]
    if common:
        return common
    tokens: set[str] = set()
    for profile in profiles:
        tokens.update(profile["tokens"])
    return tokens


def _component_terms(profiles: list[dict[str, Any]]) -> set[str]:
    terms: set[str] = set()
    for profile in profiles:
        terms.update(profile["terms"])
    return terms


def _component_confidence(profiles: list[dict[str, Any]], is_grouped: bool) -> int:
    if not is_grouped:
        return 55
    common_tokens = _component_tokens(profiles)
    token_score = min(35, len(common_tokens) * 8)
    term_bonus = 10 if _component_terms(profiles) else 0
    return min(95, 55 + token_score + term_bonus)


def _find(parent: list[int], index: int) -> int:
    while parent[index] != index:
        parent[index] = parent[parent[index]]
        index = parent[index]
    return index


def _union(parent: list[int], left: int, right: int) -> None:
    left_root = _find(parent, left)
    right_root = _find(parent, right)
    if left_root != right_root:
        parent[right_root] = left_root
