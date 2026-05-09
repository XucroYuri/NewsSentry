"""Implements: docs/spec/phase-2-runtime-carrier-alignment.md §3.2

HermesAdapter — stub for Hermes runtime integration (ADR-0006).
"""
from __future__ import annotations

from typing import Any


class HermesAdapter:
    """Stub adapter for Hermes Agent runtime. Full impl in Phase 2."""
    runtime_id = "hermes"

    def __init__(self, config: dict[str, Any]) -> None:
        raise NotImplementedError("Phase 2: HermesAdapter.__init__")

    def trigger_run(self, target_id: str, stage: str, run_id: str | None = None) -> str:
        raise NotImplementedError("Phase 2: HermesAdapter.trigger_run")

    def get_run_status(self, run_id: str) -> dict[str, str]:
        raise NotImplementedError("Phase 2: HermesAdapter.get_run_status")

    def list_skills(self) -> list[str]:
        raise NotImplementedError("Phase 2: HermesAdapter.list_skills")
