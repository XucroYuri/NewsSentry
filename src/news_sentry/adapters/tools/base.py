"""Implements: docs/spec/phase-4-tool-skill-registry-opencli.md §3.1

ToolAdapter — abstract protocol for external tool execution.
"""
from __future__ import annotations

from typing import Any, Protocol


class ToolRunResult:
    """Result of a tool execution. Schema: schemas/toolrunresult.schema.json"""
    def __init__(self, *, tool_id: str, run_id: str, success: bool,
                 exit_code: int | None, stdout: str | None, stderr: str | None,
                 duration_ms: int, error: dict[str, str] | None = None) -> None:
        raise NotImplementedError("Phase 4: ToolRunResult.__init__")


class ToolAdapter(Protocol):
    """Protocol for tool adapters."""
    tool_id: str

    def execute(self, validated_args: dict[str, Any], run_id: str) -> ToolRunResult:
        """Execute tool with validated args. SandboxEnforcer check happens before this."""
        ...
