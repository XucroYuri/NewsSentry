"""Implements: docs/spec/phase-3-kernel-mvp.md §3.8

Memory — manages known IDs, source health, cursors, KOL state.
Storage: {target}/memory/ directory (YAML files).
"""
from __future__ import annotations
from pathlib import Path


class Memory:
    def __init__(self, memory_dir: Path) -> None:
        raise NotImplementedError("Phase 3: Memory.__init__")

    def is_known_id(self, event_id: str) -> bool:
        raise NotImplementedError("Phase 3: Memory.is_known_id")

    def mark_known(self, event_id: str) -> None:
        raise NotImplementedError("Phase 3: Memory.mark_known")

    def get_source_health(self, source_id: str) -> dict[str, int | str | None]:
        raise NotImplementedError("Phase 3: Memory.get_source_health")

    def update_source_health(self, source_id: str, success: bool) -> None:
        raise NotImplementedError("Phase 3: Memory.update_source_health")
