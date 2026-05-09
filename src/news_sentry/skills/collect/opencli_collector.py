"""Implements: docs/spec/phase-4-tool-skill-registry-opencli.md §3.3

OpenCLICollector — wraps OpenCLI tool calls to collect web page content.
Uses ToolManifest entries from config/toolmanifest/opencli-baseline.yaml (ADR-0011).
"""
from __future__ import annotations
from typing import Any
from news_sentry.models.newsevent import NewsEvent


class OpenCLICollector:
    def __init__(self, config: dict[str, Any], sandbox_enforcer: Any, tool_registry: Any) -> None:
        raise NotImplementedError("Phase 4: OpenCLICollector.__init__")

    def collect(self, run_id: str) -> list[NewsEvent]:
        raise NotImplementedError("Phase 4: OpenCLICollector.collect")
