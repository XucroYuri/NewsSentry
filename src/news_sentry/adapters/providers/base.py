"""Implements: docs/spec/phase-5-ai-provider-routing.md §3.1

AIProvider — abstract protocol for AI provider routing (ADR-0005).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AIProvider(Protocol):
    """Protocol for AI provider adapters. Route via route_id per contracts-canonical §7."""

    provider_id: str

    def call(self, route_id: str, prompt: str, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """Call AI provider with route_id. Returns structured output matching output_schema."""
        ...

    def health_check(self) -> bool:
        """Check if the provider is available."""
        ...
