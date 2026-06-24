"""Implements: docs/spec/phase-4-sandbox-hardening.md §3.1

SkillManifest data model.
Schema: schemas/skillmanifest.schema.json
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class RuntimeCompatibility(StrEnum):
    CLI = "cli"
    # Hermes/OpenClaw removed per CLAUDE.md 框架中立原则:
    # 外部 Agent 框架集成放 runtime adapters，不进领域契约


class SkillManifest(BaseModel):
    skill_id: str
    display_name: str
    version: str
    stage: str
    entry_point: str
    input_schema_ref: str | None = None
    output_schema_ref: str | None = None
    tool_refs: list[str] = Field(default_factory=list)
    runtime_compatibility: list[RuntimeCompatibility] = Field(default_factory=list)
