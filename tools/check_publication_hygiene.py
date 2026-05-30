#!/usr/bin/env python3
"""Fail CI when local/runtime artifacts are tracked by Git."""

from __future__ import annotations

import fnmatch
import subprocess
import sys
from pathlib import Path

ALLOWED_EXACT = {
    ".env.example",
    "config/session-profiles/italy/.gitkeep",
}

ALLOWED_GLOBS = ("data/eval/eval-set-v*.json",)

FORBIDDEN_EXACT = {
    "CLAUDE-PROMPT.md",
    "CLAUDE.local.md",
    "prd.json",
    "progress.txt",
    "src/news_sentry/static/diagnose.html",
}

FORBIDDEN_PREFIXES = (
    ".claude/",
    ".codex/",
    ".cursor/",
    ".omc/",
    ".omx/",
    ".planning/",
    ".superpowers/",
    ".worktrees/",
    ".wrangler/",
    "memory/session-profiles/",
)

FORBIDDEN_GLOBS = (
    "*.actual.yaml",
    "*.actual.yml",
    "*.actual.json",
    "*.local.yaml",
    "*.local.yml",
    ".env.*",
    "**/.env.*",
    "**/.DS_Store",
    "**/Cookies",
    "**/Login Data",
)

FORBIDDEN_SEGMENTS = {
    "Chrome",
    "chromium",
    "chrome-profiles",
}


def tracked_paths(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
        text=False,
    )
    raw_paths = result.stdout.split(b"\0")
    return sorted(path.decode("utf-8") for path in raw_paths if path)


def is_allowed(path: str) -> bool:
    if path in ALLOWED_EXACT:
        return True
    return any(fnmatch.fnmatch(path, pattern) for pattern in ALLOWED_GLOBS)


def violation_reason(path: str) -> str | None:
    if is_allowed(path):
        return None

    if path in FORBIDDEN_EXACT:
        return "local planning/build artifact must not be tracked"

    if path == ".env" or path.startswith(".env.") or "/.env." in path:
        return "environment files must not be tracked"

    for prefix in FORBIDDEN_PREFIXES:
        if path.startswith(prefix):
            return f"local tool/runtime path is forbidden: {prefix}"

    if path.startswith("config/session-profiles/"):
        return "session profile material must stay local; keep only .gitkeep"

    if path.startswith("data/"):
        return "runtime data must not be tracked; only data/eval/eval-set-v*.json is allowed"

    parts = set(path.split("/"))
    if parts & FORBIDDEN_SEGMENTS:
        return "browser profile directory must not be tracked"

    for pattern in FORBIDDEN_GLOBS:
        if fnmatch.fnmatch(path, pattern):
            return f"forbidden tracked file pattern: {pattern}"

    return None


def find_violations(paths: list[str]) -> list[tuple[str, str]]:
    violations: list[tuple[str, str]] = []
    for path in paths:
        reason = violation_reason(path)
        if reason:
            violations.append((path, reason))
    return violations


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    violations = find_violations(tracked_paths(root))
    if not violations:
        print("PASS publication hygiene: no forbidden tracked paths")
        return 0

    print(f"FAIL publication hygiene: {len(violations)} forbidden tracked path(s)\n")
    for path, reason in violations:
        print(f"- {path}: {reason}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
