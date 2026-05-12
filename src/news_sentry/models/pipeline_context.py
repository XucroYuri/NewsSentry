"""Implements: docs/spec/phase-3-kernel-mvp.md §3.2

PipelineContext carries run-level state across skill invocations.
Schema: schemas/pipelinecontext.schema.json
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from news_sentry.models.newsevent import PipelineStage


class PipelineContext(BaseModel):
    run_id: str
    target_id: str
    stage: PipelineStage
    started_at: str
    config_snapshot: dict[str, Any] = Field(default_factory=dict)
    profile_id: str = "local-workstation"
    errors_count: int = 0
    run_log_path: str | None = None
    events_collected: int = 0
    events_filtered: int = 0
    events_judged: int = 0
    events_output: int = 0
