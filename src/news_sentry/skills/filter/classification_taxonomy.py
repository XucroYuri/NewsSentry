"""Taxonomy compatibility helpers for rule-based classification."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

CANONICAL_L0: set[str] = {
    "politics",
    "economy",
    "society",
    "public-safety",
    "environment",
    "tech",
    "international-relations",
    "china-related",
    "culture",
    "sports",
    "health",
    "uncategorized",
}

LEGACY_L0_ALIASES: dict[str, str] = {
    "economics": "economy",
    "security": "public-safety",
    "international": "international-relations",
    "culture_society": "society",
    "environment_energy": "environment",
    "china_related": "china-related",
    "political": "politics",
    "technology": "tech",
    "energy": "environment",
    "breaking_news": "uncategorized",
    "other": "uncategorized",
}

PUBLIC_CHANNEL_TERMS: dict[str, set[str]] = {
    "policy": {
        "politics",
        "parliament",
        "cabinet",
        "coalition",
        "eu-affairs",
        "migration-policy",
        "justice-reform",
    },
    "industry": {
        "economy",
        "trade",
        "energy",
        "labor-market",
        "financial-markets",
        "corporate",
        "infrastructure",
        "environment",
    },
    "risk": {
        "international-relations",
        "public-safety",
        "disaster",
        "sanctions",
        "russia-ukraine",
        "nato",
        "terrorism",
    },
    "tech": {
        "tech",
        "ai",
        "semiconductor",
        "digital-policy",
        "cybersecurity",
        "research",
        "tech-industry",
    },
    "china": {
        "china-related",
        "china-italy-bilateral",
        "bri-italy",
        "chinese-investment",
        "china-eu-policy",
        "chinese-community",
    },
}


def canonical_l0(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return "uncategorized"
    return LEGACY_L0_ALIASES.get(raw, raw)


def is_canonical_l0(value: str | None) -> bool:
    return canonical_l0(value) in CANONICAL_L0 and str(value or "").strip().lower() in CANONICAL_L0


def l0_query_values(value: str | None) -> set[str]:
    raw = str(value or "").strip().lower()
    canonical = canonical_l0(raw)
    values = {canonical}
    if raw:
        values.add(raw)
    values.update(alias for alias, target in LEGACY_L0_ALIASES.items() if target == canonical)
    return values


def normalize_classification(classification: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(classification, dict):
        return {}
    normalized = dict(classification)
    normalized["l0"] = canonical_l0(_term_text(classification.get("l0")))
    return normalized


def _term_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("code", "name", "label", "title"):
            if value.get(key):
                return str(value[key]).strip().lower()
        return ""
    return str(value).strip().lower()


def classification_terms(classification: dict[str, Any] | None) -> list[str]:
    if not isinstance(classification, dict):
        return []

    terms: list[str] = []
    l0 = canonical_l0(_term_text(classification.get("l0")))
    if l0 and l0 != "uncategorized":
        terms.append(l0)

    l1 = classification.get("l1") or []
    if not isinstance(l1, list):
        l1 = [l1]
    for item in l1:
        text = _term_text(item)
        if text:
            terms.append(text)

    return list(dict.fromkeys(terms))


def public_channel_for_terms(terms: Iterable[str]) -> str | None:
    normalized = {canonical_l0(term) for term in terms if term}
    for channel, channel_terms in PUBLIC_CHANNEL_TERMS.items():
        if normalized & channel_terms:
            return channel
    return None
