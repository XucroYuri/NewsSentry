"""Regression tests for the Italy target live-source cleanup."""

from __future__ import annotations

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_italy_target_replaces_blocked_sources_with_live_rss() -> None:
    """Italy target should remove blocked feeds and keep the verified replacements."""
    target_path = PROJECT_ROOT / "config" / "targets" / "italy.yaml"
    target = yaml.safe_load(target_path.read_text(encoding="utf-8"))
    refs = target["source_channel_refs"]

    assert "camera-it" not in refs
    assert "quirinale" not in refs
    assert "unhcr-italia" not in refs
    assert "ansa-politica" in refs
    assert "ansa-economia" in refs
    assert "open-online" in refs
    assert (PROJECT_ROOT / "config" / "sources" / "italy" / "ansa-politica.yaml").is_file()
    assert (PROJECT_ROOT / "config" / "sources" / "italy" / "ansa-economia.yaml").is_file()
    assert (PROJECT_ROOT / "config" / "sources" / "italy" / "open-online.yaml").is_file()
