"""Implements: docs/spec/phase-3-kernel-mvp.md §3.5

RulesFilter — keyword + score threshold filtering.
Input: list[NewsEvent] at stage=collected. Output: list[NewsEvent] at stage=filtered.
"""
from __future__ import annotations
from typing import Any
from news_sentry.models.newsevent import NewsEvent


class RulesFilter:
    def __init__(self, filter_config: dict[str, Any], memory: Any) -> None:
        raise NotImplementedError("Phase 3: RulesFilter.__init__")

    def filter(self, events: list[NewsEvent], run_id: str) -> list[NewsEvent]:
        """Apply keyword rules, dedup via memory, score threshold. Returns passing events."""
        raise NotImplementedError("Phase 3: RulesFilter.filter")

    def _score_event(self, event: NewsEvent, keyword_rules: list[dict[str, Any]]) -> int:
        """Compute news_value_score 0-100 based on keyword weights."""
        raise NotImplementedError("Phase 3: RulesFilter._score_event")
