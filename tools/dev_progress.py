#!/usr/bin/env python3
"""Report local vs remote repository sync and roadmap phase status."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_INDEX = ROOT / "docs" / "spec" / "README.md"
PHASE_ROW = re.compile(
    r"^\|\s*Phase\s+(\d+)\s*\|[^|]+\|[^|]+\|\s*(.+?)\s*\|\s*$"
)


def run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def git_available() -> bool:
    try:
        run_git("rev-parse", "--is-inside-work-tree")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return True


def fetch_remote(remote: str) -> None:
    subprocess.run(
        ["git", "fetch", remote],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def local_git_state() -> dict[str, object]:
    branch = run_git("branch", "--show-current")
    commit = run_git("rev-parse", "HEAD")
    short = run_git("rev-parse", "--short", "HEAD")
    dirty = bool(run_git("status", "--porcelain"))
    return {
        "branch": branch,
        "commit": commit,
        "short": short,
        "dirty": dirty,
    }


def remote_git_state(remote: str, branch: str) -> dict[str, object]:
    ref = f"{remote}/{branch}"
    try:
        commit = run_git("rev-parse", ref)
        short = run_git("rev-parse", "--short", ref)
        reachable = True
    except subprocess.CalledProcessError:
        return {"ref": ref, "reachable": False}

    ahead = 0
    behind = 0
    counts = run_git("rev-list", "--left-right", "--count", f"HEAD...{ref}")
    if counts:
        behind_s, ahead_s = counts.split()
        behind = int(behind_s)
        ahead = int(ahead_s)

    return {
        "ref": ref,
        "reachable": reachable,
        "commit": commit,
        "short": short,
        "ahead": ahead,
        "behind": behind,
        "synced": ahead == 0 and behind == 0,
    }


def load_phase_status() -> list[dict[str, str]]:
    if not SPEC_INDEX.is_file():
        return []

    phases: list[dict[str, str]] = []
    for line in SPEC_INDEX.read_text(encoding="utf-8").splitlines():
        match = PHASE_ROW.match(line)
        if not match:
            continue
        phases.append(
            {
                "phase": match.group(1),
                "status": match.group(2).strip(),
            }
        )
    return phases


def collect_test_metrics() -> dict[str, object] | None:
    venv_python = ROOT / ".venv" / "bin" / "python"
    if not venv_python.is_file():
        return None

    result = subprocess.run(
        [str(venv_python), "-m", "pytest", "tests/", "--collect-only", "-q"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None

    for line in reversed(result.stdout.splitlines()):
        if "tests collected" in line:
            count = int(line.split()[0])
            return {"collected": count, "source": "pytest --collect-only"}
    return None


def build_report(*, remote: str, fetch: bool) -> dict[str, object]:
    if not git_available():
        raise RuntimeError("当前目录不是 Git 仓库，无法计算本地/远端进度。")

    if fetch:
        fetch_remote(remote)

    local = local_git_state()
    branch = str(local["branch"])
    remote_state = remote_git_state(remote, branch)
    phases = load_phase_status()
    metrics = collect_test_metrics()

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "local": local,
        "remote": remote_state,
        "phases": phases,
        "metrics": metrics,
    }


def format_text(report: dict[str, object]) -> str:
    local = report["local"]
    remote = report["remote"]
    lines = [
        "News Sentry 开发进度",
        f"生成时间: {report['generated_at']}",
        "",
        "Git 同步",
        f"  本地: {local['branch']} @ {local['short']}"
        f"{' (dirty)' if local['dirty'] else ''}",
    ]

    if remote.get("reachable"):
        lines.append(f"  远端: {remote['ref']} @ {remote['short']}")
        lines.append(
            f"  差异: ahead {remote['ahead']}, behind {remote['behind']}"
        )
        lines.append(
            "  状态: "
            + ("已同步" if remote.get("synced") else "未同步")
        )
    else:
        lines.append(f"  远端: {remote['ref']} 不可达（先 git fetch）")

    lines.extend(["", "路线图阶段"])
    for phase in report["phases"]:
        lines.append(f"  Phase {phase['phase']}: {phase['status']}")

    metrics = report.get("metrics")
    if metrics:
        lines.extend(
            [
                "",
                "测试（本地 .venv）",
                f"  收集: {metrics['collected']} tests",
            ]
        )

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="输出本地/远端 Git 同步与路线图阶段进度。",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 输出报告",
    )
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="不执行 git fetch",
    )
    parser.add_argument(
        "--remote",
        default="origin",
        help="远端名称（默认 origin）",
    )
    args = parser.parse_args(argv)

    try:
        report = build_report(remote=args.remote, fetch=not args.no_fetch)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
