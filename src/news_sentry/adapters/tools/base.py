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

    @classmethod
    def from_subprocess(
        cls,
        *,
        tool_id: str,
        run_id: str,
        completed: Any,  # noqa: ANN401 — subprocess.CompletedProcess not importable at type-check time
        duration_ms: int,
        exit_code_map: dict[int, str] | None = None,
    ) -> ToolRunResult:
        """从 subprocess.CompletedProcess 构造 ToolRunResult。

        Args:
            tool_id: ToolManifest tool_id。
            run_id: 本次 bounded run ID。
            completed: subprocess.run() 返回的 CompletedProcess。
            duration_ms: 执行耗时（毫秒）。
            exit_code_map: 退出码 → error.type 映射表。
                来自 ToolManifest.exit_codes。None 时使用默认映射。

        Returns:
            填充完整的 ToolRunResult。
        """
        exit_code = completed.returncode
        success = exit_code == 0
        error: dict[str, str] | None = None

        if not success:
            if exit_code_map is None:
                exit_code_map = {}
            error_type = exit_code_map.get(exit_code, "unknown")
            stderr_text = (completed.stderr or "")[:500]
            error = {
                "type": error_type,
                "message": stderr_text or f"exit code {exit_code}",
            }

        return cls(
            tool_id=tool_id,
            run_id=run_id,
            success=success,
            exit_code=exit_code,
            stdout=(completed.stdout or "")[:100_000],
            stderr=(completed.stderr or "")[:10_000],
            duration_ms=duration_ms,
            error=error,
        )


class ToolAdapter(Protocol):
    """Protocol for tool adapters."""

    tool_id: str

    def execute(self, validated_args: dict[str, Any], run_id: str) -> ToolRunResult:
        """Execute tool with validated args. SandboxEnforcer check happens before this."""
        ...
