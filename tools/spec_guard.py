#!/usr/bin/env python3
"""SPEC 体系守卫：结构、状态一致性、旧体系冻结清单。

本工具让三件事从"声明"变成"门禁"：

1. **结构完整**：`docs/spec/` 的必需文件与阶段文档的必需章节存在。
2. **状态单一来源**：阶段状态只写在 `phases/*.md` 首部；
   `03-phase-plan.md` 的矩阵由本工具生成，手改即失败。
3. **旧体系硬冻结**：历史文档树的内容由 SHA-256 清单锁定，
   新增、删除、修改任一文件都会失败。

用法：
    python tools/spec_guard.py --check                    # 全部校验（CI 门禁）
    python tools/spec_guard.py --render                   # 重写阶段状态矩阵
    python tools/spec_guard.py --update-legacy-manifest   # 显式更新冻结清单

更新冻结清单是**有意的破窗动作**：必须在 commit message 中写明理由。
正确的做法通常是"把内容搬进 docs/spec/"，而不是改冻结文档。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPEC_DIR = PROJECT_ROOT / "docs" / "spec"
PHASES_DIR = SPEC_DIR / "phases"
PHASE_PLAN = SPEC_DIR / "03-phase-plan.md"
MANIFEST = SPEC_DIR / "legacy-manifest.json"
MATRIX_MARKER = "phase-matrix"
MANIFEST_SCHEMA = "news-sentry.spec-legacy-manifest.v1"

REQUIRED_FILES = (
    "README.md",
    "00-constitution.md",
    "01-product-baseline.md",
    "02-engineering-baseline.md",
    "03-phase-plan.md",
    "LEGACY.md",
)

# 阶段文档必须按顺序包含 §1..§6（标题文字不限）
REQUIRED_SECTION_NUMBERS = (1, 2, 3, 4, 5, 6)

VALID_STATUSES = {
    "DRAFT",
    "DECIDED",
    "IN-PROGRESS",
    "DONE",
    "BLOCKED",
    "SUPERSEDED",
}

# 冻结的历史文档树（相对仓库根）
FROZEN_TREES = (
    "docs/specs",
    "docs/plans",
    "docs/superpowers",
    "docs/roadmap",
    "docs/audits",
    "docs/deployment",
    "docs/design",
    "docs/research",
    "docs/seo-geo",
)

# 顶层 docs/*.md 中**仍然可编辑**的例外（见 README §4 权威顺序第 5、6 位）
LIVING_TOP_LEVEL = {
    "docs/contracts-canonical.md",  # 数据口径权威（ADR-0014）
    "docs/status.md",  # 运行时事实
    "docs/architecture.md",  # 架构总览，含生成区间
}

# 冻结树内部仍然可编辑的例外。
#
# 判据（LEGACY.md §3.1）：**内容被测试硬断言的文档，按定义是活契约，不是历史。**
# 把它们冻结会造成死锁：改测试期望需要改冻结件，而改冻结件会让本门禁失败。
LIVING_IN_FROZEN_TREES = {
    "docs/github-discoverability.md",  # tests/js/github_discoverability_test.mjs 断言其内容
    # tests/unit/test_cloudflare_native_config.py:856 断言其中 5 个字符串
    "docs/deployment/cloudflare-native-vps-removal.md",
}

LIVING_PATHS = LIVING_TOP_LEVEL | LIVING_IN_FROZEN_TREES

STATUS_RE = re.compile(r"^> \*\*状态\*\*：`([A-Z-]+)`", re.MULTILINE)
DEPENDS_RE = re.compile(r"^> \*\*依赖\*\*：(.*)$", re.MULTILINE)
BLOCKED_RE = re.compile(r"^> \*\*阻塞\*\*：(.*)$", re.MULTILINE)
TITLE_RE = re.compile(r"^# (L\d+) · ([^（(]+)", re.MULTILINE)


class GuardError(RuntimeError):
    """SPEC 体系校验失败。"""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _frozen_files(root: Path) -> list[Path]:
    """列出全部被冻结的文件（排除了 LIVING 例外）。"""
    found: list[Path] = []
    for tree in FROZEN_TREES:
        directory = root / tree
        if directory.is_dir():
            found.extend(
                p
                for p in directory.rglob("*")
                if p.is_file() and p.relative_to(root).as_posix() not in LIVING_PATHS
            )
    for path in (root / "docs").glob("*.md"):
        relative = path.relative_to(root).as_posix()
        if relative not in LIVING_PATHS:
            found.append(path)
    return sorted(found)


def build_manifest(root: Path) -> dict[str, Any]:
    files = _frozen_files(root)
    return {
        "schema_version": MANIFEST_SCHEMA,
        "note": (
            "旧文档体系的冻结清单。新增/删除/修改任一文件都会使 spec_guard --check 失败。"
            "如需变更，请运行 --update-legacy-manifest 并在 commit message 中写明理由；"
            "正确做法通常是先把内容搬进 docs/spec/。"
        ),
        "frozen_trees": list(FROZEN_TREES),
        "living_paths": sorted(LIVING_PATHS),
        "file_count": len(files),
        "files": {p.relative_to(root).as_posix(): _sha256(p) for p in files},
    }


def discover_phases() -> list[tuple[str, str, str, str, str]]:
    """返回 (阶段 id, 名称, 状态, 依赖, 阻塞)，按阶段 id 排序。"""
    phases: list[tuple[str, str, str, str, str]] = []
    for path in sorted(PHASES_DIR.glob("L*.md")):
        text = path.read_text(encoding="utf-8")
        title = TITLE_RE.search(text)
        if not title:
            raise GuardError(f"{path.name}: 缺少 '# L<n> · <名称>' 形式的标题")
        phase_id, name = title.group(1), title.group(2).strip()

        status = STATUS_RE.search(text)
        if not status or status.group(1) not in VALID_STATUSES:
            raise GuardError(f"{path.name}: 缺少合法状态行 '> **状态**：`X`'")
        depends = DEPENDS_RE.search(text)
        blocked = BLOCKED_RE.search(text)

        phases.append(
            (
                phase_id,
                name,
                status.group(1),
                (depends.group(1).strip() if depends else "未声明"),
                (blocked.group(1).strip() if blocked else "未声明"),
            )
        )
    if not phases:
        raise GuardError("phases/ 下未发现任何阶段文档")
    return phases


def render_matrix() -> str:
    rows = [
        "| 阶段 | 名称 | 状态 | 依赖 | 阻塞 |",
        "|------|------|------|------|------|",
    ]
    for phase_id, name, status, depends, blocked in discover_phases():
        rows.append(f"| {phase_id} | {name} | `{status}` | {depends} | {blocked} |")
    return "\n".join(rows)


def _replace_marker_block(text: str, name: str, body: str) -> tuple[str, bool]:
    begin = f"<!-- GENERATED:{name} BEGIN -->"
    end = f"<!-- GENERATED:{name} END -->"
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.DOTALL)
    if not pattern.search(text):
        raise GuardError(f"缺少生成区间标记: {name}")
    replacement = f"{begin}\n{body.rstrip()}\n{end}"
    updated = pattern.sub(lambda _: replacement, text, count=1)
    return updated, updated != text


def check_structure(root: Path) -> list[str]:
    problems: list[str] = []
    for name in REQUIRED_FILES:
        if not (SPEC_DIR / name).is_file():
            problems.append(f"缺少必需文件 docs/spec/{name}")
    if not PHASES_DIR.is_dir():
        problems.append("缺少目录 docs/spec/phases/")

    for path in sorted(PHASES_DIR.glob("L*.md")):
        text = path.read_text(encoding="utf-8")
        for number in REQUIRED_SECTION_NUMBERS:
            if not re.search(rf"^## §{number} ", text, re.MULTILINE):
                problems.append(f"{path.name}: 缺少章节 '## §{number} ...'")
    return problems


def check_matrix() -> list[str]:
    if not PHASE_PLAN.is_file():
        return ["缺少 docs/spec/03-phase-plan.md"]
    text = PHASE_PLAN.read_text(encoding="utf-8")
    try:
        _, changed = _replace_marker_block(text, MATRIX_MARKER, render_matrix())
    except GuardError as error:
        return [str(error)]
    if changed:
        return [
            "阶段状态矩阵与 phases/*.md 不一致："
            "请运行 python tools/spec_guard.py --render"
        ]
    return []


def check_manifest(root: Path) -> list[str]:
    if not MANIFEST.is_file():
        return ["缺少 docs/spec/legacy-manifest.json（运行 --update-legacy-manifest 生成）"]
    recorded = json.loads(MANIFEST.read_text(encoding="utf-8"))
    expected: dict[str, str] = recorded.get("files", {})
    actual = {p.relative_to(root).as_posix(): _sha256(p) for p in _frozen_files(root)}

    problems: list[str] = []
    added = sorted(set(actual) - set(expected))
    removed = sorted(set(expected) - set(actual))
    modified = sorted(
        path for path in set(actual) & set(expected) if actual[path] != expected[path]
    )

    for path in added:
        problems.append(f"冻结树出现新文件: {path}（新文档请放进 docs/spec/）")
    for path in removed:
        problems.append(f"冻结树文件被删除: {path}")
    for path in modified:
        problems.append(f"冻结树文件被修改: {path}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="全部校验")
    parser.add_argument("--render", action="store_true", help="重写阶段状态矩阵")
    parser.add_argument(
        "--update-legacy-manifest",
        action="store_true",
        help="显式更新冻结清单（需在 commit message 中写明理由）",
    )
    args = parser.parse_args(argv)

    if args.render:
        text = PHASE_PLAN.read_text(encoding="utf-8")
        updated, changed = _replace_marker_block(text, MATRIX_MARKER, render_matrix())
        if changed:
            PHASE_PLAN.write_text(updated, encoding="utf-8")
            print("已重写阶段状态矩阵")
        else:
            print("阶段状态矩阵已是最新")
        return 0

    if args.update_legacy_manifest:
        manifest = build_manifest(PROJECT_ROOT)
        MANIFEST.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"已更新冻结清单：{manifest['file_count']} 个文件")
        return 0

    problems = [*check_structure(PROJECT_ROOT), *check_matrix(), *check_manifest(PROJECT_ROOT)]
    if problems:
        print("SPEC 体系校验失败：")
        for item in problems:
            print(f"  - {item}")
        return 1
    print("OK: SPEC 体系结构、状态矩阵、冻结清单全部一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
