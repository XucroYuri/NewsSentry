"""Implements: docs/spec/phase-2-runtime-carrier-alignment.md §3.1

RuntimeHostAdapter — abstract protocol for Hermes/OpenClaw runtime integration.
Concrete implementations in hermes.py and openclaw.py.
"""
from __future__ import annotations
from typing import Protocol, runtime_checkable


@runtime_checkable
class RuntimeHostAdapter(Protocol):
    """Protocol for runtime host adapters. Implements: docs/contracts-canonical.md §3."""

    runtime_id: str

    def trigger_run(self, target_id: str, stage: str, run_id: str | None = None) -> str:
        """Trigger a bounded run. Returns run_id."""
        ...

    def get_run_status(self, run_id: str) -> dict[str, str]:
        """Get status of a run by run_id. Returns {'status': 'running'|'done'|'failed'}."""
        ...

    def list_skills(self) -> list[str]:
        """List registered skill_ids available in this runtime."""
        ...
