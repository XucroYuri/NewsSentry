"""Implements: docs/spec/phase-3-kernel-mvp.md §3.7

RunLog — writes structured run log per bounded run.
Output: {target}/logs/run-{run_id}.json
"""
from __future__ import annotations
from pathlib import Path
from news_sentry.models.pipeline_context import PipelineContext


class RunLog:
    def __init__(self, log_dir: Path) -> None:
        raise NotImplementedError("Phase 3: RunLog.__init__")

    def write(self, context: PipelineContext, status: str, error: str | None = None) -> Path:
        """Write final run log JSON. Returns written path."""
        raise NotImplementedError("Phase 3: RunLog.write")
