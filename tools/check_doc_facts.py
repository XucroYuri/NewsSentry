#!/usr/bin/env python3
"""文档数字与仓库现实一致性门禁。

约定（docs/audits/2026-08-01）：易变事实（测试数、版本号、计数）只允许出现
在 docs/status.md；README.md / README_en.md / AGENTS.md 必须以指针代替复制。

本脚本机械执行该约定：
  - 结构计数声明（JSON Schema 数、target 数、信源文件数）必须与实时清点一致；
  - 总测试数硬编码、rc 版本号、测试数徽章在这些文件中一律视为违规。

用法:
    python tools/check_doc_facts.py [--root PATH]

退出码: 0 = 一致；1 = 发现不一致或违规；2 = 内部错误。
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

SCAN_FILES = ("README.md", "README_en.md", "AGENTS.md")

_FENCE_RE = re.compile(r"^\s*(?:```|~~~)")
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
_NUMBER_RE = re.compile(r"[\d,]+")


def _to_int(raw: str) -> int:
    return int(raw.replace(",", ""))


def actual_counts(root: Path) -> dict[str, int]:
    """实时清点仓库结构计数。目录缺失时计 0，由调用方决定是否报错。"""
    schemas_dir = root / "schemas"
    targets_dir = root / "config" / "targets"
    sources_dir = root / "config" / "sources"

    schema_count = len(list(schemas_dir.glob("*.json"))) if schemas_dir.is_dir() else 0
    target_count = (
        len([p for p in targets_dir.glob("*.yaml") if not p.name.startswith("_")])
        if targets_dir.is_dir()
        else 0
    )
    source_count = len(list(sources_dir.rglob("*.yaml"))) if sources_dir.is_dir() else 0
    return {
        "schema_count": schema_count,
        "target_count": target_count,
        "source_count": source_count,
    }


@dataclass(frozen=True)
class ClaimRule:
    """一条声明规则：kind=count 时声明值必须等于实时计数；kind=forbidden 时命中即违规。"""

    kind: str  # "count" | "forbidden"
    label: str
    pattern: re.Pattern[str]
    actual_key: str | None  # kind=count 时必填


COUNT_RULES: tuple[ClaimRule, ...] = (
    ClaimRule(
        "count",
        "JSON Schema 文件数",
        re.compile(r"(?<![\w/])(\d[\d,]*)\s*(?:份\s*)?JSON[ \-]?Schemas?\b", re.IGNORECASE),
        "schema_count",
    ),
    ClaimRule(
        "count",
        "target 总数（中文）",
        re.compile(r"(?<![\w/])(\d[\d,]*)\s*个(?:\s*已配置)?\s*targets?\b"),
        "target_count",
    ),
    ClaimRule(
        "count",
        "target 总数（英文）",
        re.compile(r"(?<![/\w])(\d[\d,]*)\s+(?:configured\s+)?targets\b"),
        "target_count",
    ),
    ClaimRule(
        "count",
        "信源文件数（中文）",
        re.compile(r"(?<![\w/])(\d[\d,]*)\s*(?:个\s*)?源(?![\w/])"),
        "source_count",
    ),
    ClaimRule(
        "count",
        "source 文件数（英文）",
        re.compile(r"(?<![/\w])(\d[\d,]*)\s*\+?\s*sources\b"),
        "source_count",
    ),
)

# 违规类：这些事实按约定只属于 docs/status.md，出现在受扫描文件中即为失败。
FORBIDDEN_RULES: tuple[ClaimRule, ...] = (
    ClaimRule(
        "forbidden",
        "总测试数硬编码",
        re.compile(r"\b\d{3,}(?:,\d{3})*\s*\+?\s*(?:项\s*)?tests\b", re.IGNORECASE),
        None,
    ),
    ClaimRule(
        "forbidden",
        "测试数徽章",
        re.compile(r"badge/tests-(\d+)"),
        None,
    ),
    ClaimRule(
        "forbidden",
        "rc 版本号",
        re.compile(r"\bv\d+\.\d+\.\d+-rc\d+\b"),
        None,
    ),
)

ALL_RULES: tuple[ClaimRule, ...] = COUNT_RULES + FORBIDDEN_RULES


def iter_claim_lines(text: str) -> Iterator[tuple[int, str]]:
    """逐行产出 (行号, 去除行内代码后的文本)，跳过围栏代码块。"""
    in_fence = False
    for line_no, raw in enumerate(text.splitlines(), start=1):
        if _FENCE_RE.match(raw):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        yield line_no, _INLINE_CODE_RE.sub("", raw)


@dataclass(frozen=True)
class Finding:
    status: str  # "OK" | "FAIL" | "WARN"
    file: str
    line_no: int
    label: str
    detail: str


def scan_file(path: Path, counts: dict[str, int]) -> list[Finding]:
    findings: list[Finding] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [Finding("WARN", path.name, 0, "文件读取失败", str(exc))]

    display = path.name
    for line_no, line in iter_claim_lines(text):
        for rule in ALL_RULES:
            for match in rule.pattern.finditer(line):
                if rule.kind == "forbidden":
                    findings.append(
                        Finding(
                            "FAIL",
                            display,
                            line_no,
                            rule.label,
                            f"命中违规模式: {match.group(0)!r}"
                            "（该事实只允许出现在 docs/status.md）",
                        )
                    )
                    continue
                assert rule.actual_key is not None
                claimed = _to_int(match.group(1))
                reality = counts.get(rule.actual_key, 0)
                if claimed == reality:
                    findings.append(
                        Finding(
                            "OK",
                            display,
                            line_no,
                            rule.label,
                            f"claim={claimed} actual={reality}",
                        )
                    )
                else:
                    findings.append(
                        Finding(
                            "FAIL",
                            display,
                            line_no,
                            rule.label,
                            f"claim={claimed} actual={reality}",
                        )
                    )
    return findings


def run_checks(root: Path) -> tuple[list[Finding], list[str]]:
    counts = actual_counts(root)
    warnings: list[str] = []
    if counts["schema_count"] == 0:
        warnings.append("schemas/ 未找到 JSON Schema 文件（目录缺失或为空）")
    if counts["target_count"] == 0:
        warnings.append("config/targets/ 未找到 target YAML（目录缺失或为空）")

    findings: list[Finding] = []
    for name in SCAN_FILES:
        path = root / name
        if not path.is_file():
            warnings.append(f"跳过不存在的扫描目标: {name}")
            continue
        findings.extend(scan_file(path, counts))
    return findings, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="文档数字一致性门禁")
    default_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--root", type=Path, default=default_root, help="仓库根目录")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    findings, warnings = run_checks(root)

    for warning in warnings:
        print(f"[WARN] {warning}")
    for item in findings:
        marker = item.status
        location = f"{item.file}:{item.line_no}" if item.line_no else item.file
        print(f"[{marker}] {location} {item.label}: {item.detail}")

    failures = sum(1 for item in findings if item.status == "FAIL")
    ok_count = sum(1 for item in findings if item.status == "OK")
    print(f"检查完成: {ok_count} 项一致, {failures} 项失败, {len(warnings)} 条警告")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
