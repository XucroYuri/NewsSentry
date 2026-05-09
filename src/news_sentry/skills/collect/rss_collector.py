"""Implements: docs/spec/phase-3-kernel-mvp.md §3.4

RSSCollector — fetches and parses RSS feeds using feedparser + httpx.
Input: SourceChannel config. Output: list[NewsEvent] at stage=collected.
"""
from __future__ import annotations
from typing import Any
from news_sentry.models.newsevent import NewsEvent


class RSSCollector:
    """Collects NewsEvents from RSS feeds. ADR-0012 (Python), ADR-0013 (skills layer)."""

    def __init__(self, config: dict[str, Any], sandbox_enforcer: Any) -> None:
        raise NotImplementedError("Phase 3: RSSCollector.__init__")

    def collect(self, run_id: str) -> list[NewsEvent]:
        """Fetch RSS feed, parse entries, return NewsEvent list at stage=collected."""
        raise NotImplementedError("Phase 3: RSSCollector.collect")
