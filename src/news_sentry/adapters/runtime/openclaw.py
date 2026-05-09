"""Implements: docs/spec/phase-2-runtime-carrier-alignment.md §3.3

OpenClawAdapter — stub for OpenClaw/ClawHub runtime integration (ADR-0006).
"""
from __future__ import annotations

from typing import Any


class OpenClawAdapter:
    """Stub adapter for OpenClaw Skill runtime. Full impl in Phase 2."""
    runtime_id = "openclaw"

    def __init__(self, config: dict[str, Any]) -> None:
        raise NotImplementedError("Phase 2: OpenClawAdapter.__init__")

    def trigger_run(self, target_id: str, stage: str, run_id: str | None = None) -> str:
        raise NotImplementedError("Phase 2: OpenClawAdapter.trigger_run")

    def get_run_status(self, run_id: str) -> dict[str, str]:
        raise NotImplementedError("Phase 2: OpenClawAdapter.get_run_status")

    def list_skills(self) -> list[str]:
        raise NotImplementedError("Phase 2: OpenClawAdapter.list_skills")
