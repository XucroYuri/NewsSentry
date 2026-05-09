"""Implements: docs/spec/phase-3-kernel-mvp.md §3.5

ClassifierRules — rule-based L0/L1/L2/L3 classification (Phase 3, no AI).
Phase 5 will add LLM-based classifier (classify.primary route).
"""
from __future__ import annotations
from typing import Any
from news_sentry.models.newsevent import NewsEvent


class ClassifierRules:
    def __init__(self, classification_config: dict[str, Any]) -> None:
        raise NotImplementedError("Phase 3: ClassifierRules.__init__")

    def classify(self, event: NewsEvent) -> NewsEvent:
        """Add metadata.classification to event. Returns enriched event."""
        raise NotImplementedError("Phase 3: ClassifierRules.classify — keyword matching L0/L1")
