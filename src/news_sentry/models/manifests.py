"""Implements: docs/spec/phase-4-sandbox-hardening.md §3.1

SkillManifest data model.
Schema: schemas/skillmanifest.schema.json
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class RuntimeCompatibility(StrEnum):
    HERMES = "hermes"
    OPENCLAW = "openclaw"  # noqa: ERA001 — reserved, not yet implemented
    CLI = "cli"


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
