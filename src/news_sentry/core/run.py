"""Implements: docs/spec/phase-3-kernel-mvp.md §3.1

bounded_run — the core run lifecycle manager.
Entry point for: news-sentry run --target <id> --stage <stage> (ADR-0016).
"""
from __future__ import annotations
from typing import TYPE_CHECKING
from news_sentry.models.newsevent import PipelineStage
from news_sentry.models.pipeline_context import PipelineContext

if TYPE_CHECKING:
    from news_sentry.core.config import ResolvedConfig


def bounded_run(
    target_id: str,
    stage: PipelineStage | str,
    run_id: str | None = None,
    dry_run: bool = False,
    config_dir: str | None = None,
) -> PipelineContext:
    """Execute a single bounded run for one target + stage.

    Generates run_id if not provided, loads config, dispatches to skill(s),
    writes run log. Never runs indefinitely — bounded by config.budget_policy.

    Exit codes (for CLI): 0=success, 1=partial failure, 2=config error, 3=sandbox blocked.
    """
    raise NotImplementedError("Phase 3: bounded_run lifecycle")
