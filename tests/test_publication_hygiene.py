from __future__ import annotations

import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from check_publication_hygiene import find_violations  # noqa: E402


def test_publication_hygiene_allows_public_assets() -> None:
    paths = [
        ".env.example",
        "config/session-profiles/italy/.gitkeep",
        "data/eval/eval-set-v1.json",
        "data/eval/eval-set-v3.json",
    ]

    assert find_violations(paths) == []


def test_publication_hygiene_blocks_local_artifacts() -> None:
    paths = [
        ".cursor/rules/local.mdc",
        ".env.local",
        "data/eval/report-v3-rules-v2.json",
        "memory/session-profiles/twitter.yaml",
        "prd.json",
        "progress.txt",
    ]

    violations = dict(find_violations(paths))

    assert set(violations) == set(paths)
