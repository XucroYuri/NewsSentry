"""Implements: docs/spec/phase-4-tool-skill-registry-opencli.md §3.3

OpenCLIToolAdapter — wraps OpenCLI subprocess calls per ADR-0008 and ADR-0011.
"""
from __future__ import annotations
from typing import Any
from news_sentry.adapters.tools.base import ToolRunResult


class OpenCLIToolAdapter:
    """Executes opencli commands as subprocess. ADR-0008: install, don't vendor."""
    tool_id = "opencli"

    def __init__(self, manifest: dict[str, Any], sandbox_enforcer: Any) -> None:
        raise NotImplementedError("Phase 4: OpenCLIToolAdapter.__init__")

    def execute(self, validated_args: dict[str, Any], run_id: str) -> ToolRunResult:
        raise NotImplementedError("Phase 4: OpenCLIToolAdapter.execute")

    def _build_command(self, tool_id: str, args: dict[str, Any]) -> list[str]:
        raise NotImplementedError("Phase 4: OpenCLIToolAdapter._build_command")
