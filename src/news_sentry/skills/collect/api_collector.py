"""Implements: docs/spec/phase-3-kernel-mvp.md §3.4

APICollector — fetches JSON API endpoints using httpx.
"""
from __future__ import annotations
from typing import Any
from news_sentry.models.newsevent import NewsEvent


class APICollector:
    def __init__(self, config: dict[str, Any], sandbox_enforcer: Any) -> None:
        raise NotImplementedError("Phase 3: APICollector.__init__")

    def collect(self, run_id: str) -> list[NewsEvent]:
        raise NotImplementedError("Phase 3: APICollector.collect")
