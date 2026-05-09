"""Implements: docs/spec/phase-3-kernel-mvp.md §3.3

ConfigLoader — loads and deep-merges config YAML files per ADR-0015.
Load order: target → source → sandbox (target has highest priority).
"""
from __future__ import annotations
from pathlib import Path
from typing import Any


class ResolvedConfig:
    """Fully resolved configuration for one target + run."""
    def __init__(self, *, target: dict[str, Any], sources: list[dict[str, Any]],
                 filters: dict[str, Any], classification: dict[str, Any],
                 sandbox: dict[str, Any], provider: dict[str, Any],
                 output: dict[str, Any]) -> None:
        raise NotImplementedError("Phase 3: ResolvedConfig initialization")

    @property
    def target_id(self) -> str:
        raise NotImplementedError("Phase 3: target_id property")


class ConfigLoader:
    """Loads and validates configuration files per ADR-0014 (JSON Schema) and ADR-0015 (merge priority)."""

    def __init__(self, config_dir: Path | None = None) -> None:
        raise NotImplementedError("Phase 3: ConfigLoader.__init__")

    def load_target(self, target_id: str) -> ResolvedConfig:
        """Load and deep-merge all config for a target.

        Order: load_yaml(targets/{id}.yaml) → resolve source refs
               → resolve filters → classification → sandbox → provider → output
        Schema validation via jsonschema per ADR-0014.
        """
        raise NotImplementedError("Phase 3: ConfigLoader.load_target")

    def _deep_merge(self, base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        """Deep merge two dicts. Lists in override REPLACE (not extend) base lists per ADR-0015."""
        raise NotImplementedError("Phase 3: ConfigLoader._deep_merge")

    def _validate_against_schema(self, data: dict[str, Any], schema_name: str) -> None:
        """Validate data dict against schemas/{schema_name}.schema.json per ADR-0014."""
        raise NotImplementedError("Phase 3: ConfigLoader._validate_against_schema")
