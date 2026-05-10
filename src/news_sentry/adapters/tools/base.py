"""Implements: docs/spec/phase-4-tool-skill-registry-opencli.md §3.1

ToolAdapter — abstract protocol for external tool execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class ToolRunResult:
    """Result of a tool execution. Schema: schemas/toolrunresult.schema.json"""
    tool_id: str
    run_id: str
    success: bool
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    error: dict[str, str] | None = None
    # error example: {"type": "timeout", "message": "subprocess timed out after 30s"}


class ToolAdapter(Protocol):
    """Protocol for tool adapters."""
    tool_id: str

    def execute(self, validated_args: dict[str, Any], run_id: str) -> ToolRunResult:
        """Execute tool with validated args. SandboxEnforcer check happens before this."""
        ...
