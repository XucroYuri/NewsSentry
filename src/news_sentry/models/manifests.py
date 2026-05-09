"""Implements: docs/spec/phase-4-tool-skill-registry-opencli.md §3.1

SkillManifest and ToolManifest data models.
Schemas: schemas/skillmanifest.schema.json, schemas/toolmanifest.schema.json
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class RuntimeCompatibility(StrEnum):
    HERMES = "hermes"
    OPENCLAW = "openclaw"
    CLI = "cli"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ExecutionType(StrEnum):
    SUBPROCESS = "subprocess"
    HTTP = "http"
    PYTHON = "python"


class ToolPermissions(BaseModel):
    risk_level: RiskLevel
    network: dict[str, list[str]] = Field(default_factory=dict)
    filesystem: dict[str, list[str]] = Field(default_factory=dict)
    browser: dict[str, bool] = Field(default_factory=dict)
    credentials: dict[str, list[str]] = Field(default_factory=dict)


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


class ToolManifest(BaseModel):
    tool_id: str
    display_name: str
    version: str
    execution_type: ExecutionType
    command_template: str | None = None
    parameters_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    exit_codes: dict[str, str] = Field(default_factory=dict)
    permissions: ToolPermissions
