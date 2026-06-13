"""Regression tests for the expanded Japan target source coverage."""

from __future__ import annotations

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_japan_target_keeps_broader_public_source_coverage() -> None:
    """Japan target should keep the round-5 live-source cleanup and replacements."""
    target_path = PROJECT_ROOT / "config" / "targets" / "japan.yaml"
    target = yaml.safe_load(target_path.read_text(encoding="utf-8"))
    refs = target["source_channel_refs"]

    assert "japantimes-topstories" in refs
    assert "asahi-headlines" in refs
    assert "yomiuri-politics" not in refs
    assert "yomiuri-social" not in refs
    assert "mainichi-politics" not in refs
    assert "mainichi-social" not in refs
    assert "nikkei" not in refs
    assert "nikkei-xtech" not in refs
    assert "mofa-japan" not in refs
    assert "mod-japan" not in refs
    assert "env-go-jp" not in refs
    assert "moj-immigration" not in refs
    assert "reuters-jp" not in refs
    assert len(refs) >= 13
    assert (
        PROJECT_ROOT / "config" / "sources" / "japan" / "japantimes-topstories.yaml"
    ).is_file()
    assert (PROJECT_ROOT / "config" / "sources" / "japan" / "asahi-headlines.yaml").is_file()
