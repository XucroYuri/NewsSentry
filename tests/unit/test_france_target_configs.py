"""Regression tests for the expanded France target source coverage."""

from __future__ import annotations

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_france_target_keeps_broad_public_source_coverage() -> None:
    """France target should keep the newly expanded public RSS breadth."""
    target_path = PROJECT_ROOT / "config" / "targets" / "france.yaml"
    target = yaml.safe_load(target_path.read_text(encoding="utf-8"))
    refs = target["source_channel_refs"]

    assert len(refs) >= 24
    for ref in refs:
        source_path = PROJECT_ROOT / "config" / "sources" / "france" / f"{ref}.yaml"
        if ref.startswith("api/"):
            source_path = PROJECT_ROOT / "config" / "sources" / "france" / f"{ref}.yaml"
        assert source_path.is_file()
