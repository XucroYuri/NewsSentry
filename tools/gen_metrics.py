#!/usr/bin/env python3
"""L0 真相层：从仓库内容生成确定性事实基线。

本脚本产出 `docs/generated/metrics.json`，它是文档中一切规模数字的唯一来源。

三条不可违反的设计约束：

1. **不写挂钟时间** —— 否则生成物永远无法与提交物保持一致（`git diff` 恒非空）。
2. **不写 HEAD commit** —— 否则每次提交都会让生成物自我失效（自引用悖论）。
3. **不臆造环境相关事实** —— 依赖运行环境才能得到的事实（如可执行用例数、覆盖率、
   node_modules 体积）一律记为 `null` 并附原因，绝不猜测。

用法：
    python tools/gen_metrics.py                # 生成
    python tools/gen_metrics.py --check        # 校验生成物与工作区一致（CI 门禁）
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "docs" / "generated" / "metrics.json"
SCHEMA_VERSION = "news-sentry.metrics.v1"

# 补源达标线：与 docs/breaking-intelligence.md 的 source_coverage_report.py 口径一致
COVERAGE_THRESHOLD = 20
# 契约文档 §10.2 明文声称的 schema 份数（用于暴露文档与磁盘的差异）
CANONICAL_CLAIMED_SCHEMAS = 18

TEST_FUNCTION_RE = re.compile(r"^\s*(?:async\s+)?def\s+test_", re.MULTILINE)
WORKER_TEST_CASE_RE = re.compile(r"\btest\s*\(")


def _iter_yaml(root: Path) -> list[Path]:
    """列出配置 YAML，跳过以下划线开头的模板文件。"""
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*.yaml") if not p.name.startswith("_"))


def _read_frontmatter_field(path: Path, field: str) -> str | None:
    """从 YAML 首部读取顶层标量字段，避免为统计引入 YAML 依赖。"""
    prefix = f"{field}:"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(prefix):
            value = line[len(prefix) :].split("#", 1)[0].strip().strip("'\"")
            return value or None
    return None


def collect_targets(root: Path) -> dict[str, Any]:
    """统计 config/targets 下的 target 数量与监控类型分布。"""
    target_files = _iter_yaml(root / "config" / "targets")
    by_scope: dict[str, int] = {}
    for path in target_files:
        scope = _read_frontmatter_field(path, "monitoring_type") or "unknown"
        by_scope[scope] = by_scope.get(scope, 0) + 1
    return {
        "total": len(target_files),
        "by_scope": dict(sorted(by_scope.items())),
    }


def collect_sources(root: Path) -> dict[str, Any]:
    """统计信源规模，并复用项目自身的覆盖工具产出 canonical 覆盖事实。

    覆盖口径**不在本脚本重新实现**：它直接调用
    `tools/source_coverage_report.py:170 build_source_coverage_report`，
    以避免在同一仓库内出现第三套"达标"定义。

    该工具的判据是：`valid_source_refs >= minimum_refs`，其中 valid 指
    **文件存在 + 通过 sourcechannel.schema.json 校验 + URL 不重复**。
    """
    sources_root = root / "config" / "sources"
    by_type: dict[str, int] = {}
    directory_counts: dict[str, int] = {}
    total = 0

    if sources_root.is_dir():
        for target_dir in sorted(p for p in sources_root.iterdir() if p.is_dir()):
            files = _iter_yaml(target_dir)
            if not files:
                continue
            directory_counts[target_dir.name] = len(files)
            total += len(files)
            for path in files:
                source_type = _read_frontmatter_field(path, "type") or "unknown"
                by_type[source_type] = by_type.get(source_type, 0) + 1

    return {
        "total": total,
        "by_type": dict(sorted(by_type.items())),
        "targets_with_sources": len(directory_counts),
        "coverage": _canonical_coverage(root),
    }


def _canonical_coverage(root: Path) -> dict[str, Any]:
    """调用项目自身的覆盖工具，返回 canonical 覆盖事实。"""
    tools_dir = str(Path(__file__).resolve().parent)
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    from source_coverage_report import build_source_coverage_report  # noqa: PLC0415

    report = build_source_coverage_report(root, minimum_refs=COVERAGE_THRESHOLD)
    below = report.get("targets_below_minimum") or []
    return {
        "criterion": "文件存在 + 通过 sourcechannel.schema.json 校验 + URL 不重复，且数量 >= 阈值",
        "source": "tools/source_coverage_report.py:170",
        "minimum_refs": report["minimum_refs"],
        "target_count": report["target_count"],
        "ready_targets": report["ready_targets"],
        "source_ref_total": report["source_ref_total"],
        "valid_source_ref_total": report["valid_source_ref_total"],
        "targets_below_minimum": [
            {
                "target_id": item["target_id"],
                "source_refs": item["source_refs"],
                "valid_source_refs": item["valid_source_refs"],
                "missing": item["missing"],
            }
            for item in below
        ],
    }


def collect_tests(root: Path) -> dict[str, Any]:
    """统计测试资产规模（纯静态，不依赖运行环境）。"""
    py_files = sorted((root / "tests").rglob("test_*.py")) if (root / "tests").is_dir() else []
    py_functions = sum(
        len(TEST_FUNCTION_RE.findall(path.read_text(encoding="utf-8", errors="replace")))
        for path in py_files
    )

    worker_dir = root / "frontend" / "cloudflare" / "tests"
    worker_files = sorted(worker_dir.glob("*.test.mts")) if worker_dir.is_dir() else []
    worker_cases = sum(
        len(WORKER_TEST_CASE_RE.findall(path.read_text(encoding="utf-8", errors="replace")))
        for path in worker_files
    )

    js_dir = root / "tests" / "js"
    js_files = sorted(js_dir.glob("*.mjs")) if js_dir.is_dir() else []

    return {
        "python": {
            "files": len(py_files),
            "functions": py_functions,
            "criteria": "tests/**/test_*.py 文件中以 def test_ 开头的函数（含类方法）",
        },
        "worker": {
            "files": len(worker_files),
            "cases": worker_cases,
            "criteria": "frontend/cloudflare/tests/*.test.mts 中 test( 调用数",
        },
        "js": {"files": len(js_files), "criteria": "tests/js/*.mjs"},
        "collected": None,
        "collected_reason": "可执行用例数依赖运行环境，由 CI 汇总，不写入仓库",
        "coverage": None,
        "coverage_reason": "仓库中不存在 --cov-fail-under 门禁，因此不发布覆盖率数字",
    }


def _count_lines(paths: list[Path]) -> int:
    total = 0
    for path in paths:
        total += len(path.read_text(encoding="utf-8", errors="replace").splitlines())
    return total


def collect_code(root: Path) -> dict[str, Any]:
    """统计源码规模。"""
    src_files = (
        sorted((root / "src" / "news_sentry").rglob("*.py")) if (root / "src").is_dir() else []
    )
    workers_dir = root / "frontend" / "cloudflare" / "workers"
    worker_files = sorted(workers_dir.rglob("*.ts")) if workers_dir.is_dir() else []
    return {
        "python": {"files": len(src_files), "loc": _count_lines(src_files)},
        "worker_ts": {"files": len(worker_files), "loc": _count_lines(worker_files)},
    }


def collect_contracts(root: Path) -> dict[str, Any]:
    """统计 schema 与 ADR 数量，并暴露与契约文档声称值的差异。"""
    schema_files = sorted((root / "schemas").glob("*.json")) if (root / "schemas").is_dir() else []
    adr_dir = root / "docs" / "adr"
    adr_files = (
        sorted(p for p in adr_dir.glob("*.md") if p.name != "README.md") if adr_dir.is_dir() else []
    )
    return {
        "schemas": {
            "total": len(schema_files),
            "canonical_claimed": CANONICAL_CLAIMED_SCHEMAS,
            "matches_canonical_claim": len(schema_files) == CANONICAL_CLAIMED_SCHEMAS,
            "files": [p.name for p in schema_files],
        },
        "adr": {"total": len(adr_files), "files": [p.name for p in adr_files]},
    }


def collect_eval_sets(root: Path) -> dict[str, Any]:
    """统计评测集规模。"""
    sets: list[dict[str, Any]] = []
    eval_dir = root / "data" / "eval"
    if eval_dir.is_dir():
        for path in sorted(eval_dir.glob("eval-set-*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                items = len(payload.get("examples", []))
            except (OSError, json.JSONDecodeError, AttributeError):
                items = None
            sets.append({"name": path.stem, "file": path.name, "items": items})
    return {"sets": sets}


def collect_dev_artifacts(root: Path) -> dict[str, Any]:
    """统计开发期产物（node_modules）体积；缺失时记为 null。"""
    workspaces = ["frontend/public", "frontend/admin", "frontend/cloudflare", "backend"]
    sizes: dict[str, int | None] = {}
    for workspace in workspaces:
        path = root / workspace / "node_modules"
        sizes[workspace] = _du_bytes(path) if path.is_dir() else None
    present = [v for v in sizes.values() if v is not None]
    return {
        "node_modules_bytes": sizes,
        "node_modules_total_bytes": sum(present) if present else None,
        "note": "开发期产物，不入库；缺失时该项为 null",
    }


def _du_bytes(path: Path) -> int | None:
    """用 du 统计目录体积（比 Python 遍历快得多）。"""
    try:
        result = subprocess.run(
            ["du", "-sb", str(path)],
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    first = result.stdout.split("\t", 1)[0].strip()
    return int(first) if first.isdigit() else None


def collect_package_version(root: Path) -> str | None:
    """从 pyproject.toml 读取项目版本。"""
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return None
    match = re.search(
        r'^version\s*=\s*"([^"]+)"',
        pyproject.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    return match.group(1) if match else None


def build_metrics(root: Path) -> dict[str, Any]:
    """组装完整事实基线。"""
    return {
        "schema_version": SCHEMA_VERSION,
        "generator": "tools/gen_metrics.py",
        "project_version": collect_package_version(root),
        "targets": collect_targets(root),
        "sources": collect_sources(root),
        "tests": collect_tests(root),
        "code": collect_code(root),
        "contracts": collect_contracts(root),
        "eval": collect_eval_sets(root),
        "dev_artifacts": collect_dev_artifacts(root),
    }


def dump(metrics: dict[str, Any]) -> str:
    """序列化为稳定文本（键排序 + 末尾换行）。"""
    return json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="校验生成物与工作区一致")
    parser.add_argument("--print", dest="print_only", action="store_true", help="输出到 stdout")
    args = parser.parse_args(argv)

    rendered = dump(build_metrics(PROJECT_ROOT))

    if args.print_only:
        sys.stdout.write(rendered)
        return 0

    if args.check:
        if not args.output.is_file():
            print(f"FAIL: 缺少生成物 {args.output.relative_to(PROJECT_ROOT)}")
            return 1
        if args.output.read_text(encoding="utf-8") != rendered:
            print("FAIL: 生成物与工作区不一致，请运行 python tools/gen_metrics.py")
            return 1
        print("OK: 生成物与工作区一致")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(f"写入 {args.output.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
