"""Admin frontend test runner configuration checks."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_admin_vitest_only_collects_src_unit_tests() -> None:
    """Vitest must not collect Playwright e2e specs."""
    config = (ROOT / "frontend" / "admin" / "vite.config.ts").read_text(encoding="utf-8")

    assert 'include: ["src/**/*.{test,spec}.{ts,tsx}"]' in config
    assert 'exclude: ["e2e/**"' in config
