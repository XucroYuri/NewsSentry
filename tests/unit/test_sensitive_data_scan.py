"""Sensitive data scanner tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_scanner_reports_sensitive_key_without_echoing_secret(tmp_path: Path) -> None:
    """扫描器应发现敏感键名，但 CI 输出不能回显 secret 值。"""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    sample_value = "ns-test-redacted-value"
    (config_dir / "provider.yaml").write_text(
        f"api_key: {sample_value}\n",
        encoding="utf-8",
    )

    result = subprocess.run(  # noqa: S603
        [sys.executable, "tools/scan_sensitive_data.py", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    combined_output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "api_key" in combined_output
    assert sample_value not in combined_output
    assert "<redacted>" in combined_output


def test_scanner_allows_descriptive_sensitive_words(tmp_path: Path) -> None:
    """描述字段里提到 token/cookie 不应被当成实际 secret。"""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "source.yaml").write_text(
        'description: "This endpoint requires bearer token auth in production docs."\n',
        encoding="utf-8",
    )

    result = subprocess.run(  # noqa: S603
        [sys.executable, "tools/scan_sensitive_data.py", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
