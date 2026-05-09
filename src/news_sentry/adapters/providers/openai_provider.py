"""Implements: docs/spec/phase-5-ai-provider-routing.md §3.2

OpenAIProvider — stub for OpenAI API calls (translate/judge/classify routes).
"""
from __future__ import annotations

from typing import Any


class OpenAIProvider:
    """Stub for OpenAI provider. Full impl in Phase 5."""
    provider_id = "openai"

    def __init__(self, config: dict[str, Any]) -> None:
        raise NotImplementedError("Phase 5: OpenAIProvider.__init__")

    def call(self, route_id: str, prompt: str, context: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(
            "Phase 5: OpenAIProvider.call — needs route_id table from config/provider/routes.yaml"
        )
