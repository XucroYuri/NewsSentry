#!/usr/bin/env python3
"""L0 真相层：把事实基线渲染进文档的生成区间。

文档中的规模数字不再手写。每个可生成的事实块由一对标记界定：

    <!-- GENERATED:<name> BEGIN -->
    ...由本脚本维护...
    <!-- GENERATED:<name> END -->

标界之外的内容完全由人类维护，本脚本绝不触碰。

用法：
    python tools/render_docs.py            # 就地渲染
    python tools/render_docs.py --check    # 只校验，不写入（CI 门禁）
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_METRICS = PROJECT_ROOT / "docs" / "generated" / "metrics.json"
GENERATED_NOTE = (
    "本区间由 tools/render_docs.py 生成，请勿手改；数字来源 docs/generated/metrics.json"
)

# 文档 -> 该文档声明的生成块名称
DOC_BLOCKS: dict[str, tuple[str, ...]] = {
    "README.md": ("readme-tagline", "readme-badges"),
    "AGENTS.md": ("status", "quickref"),
    "docs/architecture.md": ("architecture-tests",),
}


def _marker(name: str, edge: str) -> str:
    return f"<!-- GENERATED:{name} {edge} -->"


def _block(name: str, body: str) -> str:
    return f"{_marker(name, 'BEGIN')}\n{body.rstrip()}\n{_marker(name, 'END')}"


def _fmt(value: Any) -> str:
    return f"{value:,}" if isinstance(value, int) else str(value)


def render_readme_tagline(metrics: dict[str, Any]) -> str:
    python = metrics["tests"]["python"]
    line = (
        f"  {_fmt(python['functions'])} 个测试函数"
        f" · {_fmt(python['files'])} 个测试文件"
        f" · mypy strict · ruff zero<br>"
    )
    note = "  覆盖率不在此声明（仓库无覆盖率门禁，见 docs/generated/metrics.json）"
    return f"{line}\n{note}"


def render_readme_badges(metrics: dict[str, Any]) -> str:
    version = str(metrics.get("project_version") or "unknown").replace("-", "--")
    functions = metrics["tests"]["python"]["functions"]
    badges = [
        ("version", f"version-{version}-blue.svg"),
        ("python", "python-3.11+-3776AB.svg?logo=python&logoColor=white"),
        ("license", "license-Apache%202.0-orange.svg"),
        ("ruff", "ruff-0%20errors-success.svg"),
        ("tests", f"tests-{functions}%20functions-brightgreen.svg"),
        ("coverage", "coverage-not%20gated-lightgrey.svg"),
    ]
    return "\n".join(
        f'  <img src="https://img.shields.io/badge/{path}" alt="{alt}" />' for alt, path in badges
    )


def render_status(metrics: dict[str, Any]) -> str:
    tests = metrics["tests"]
    code = metrics["code"]
    contracts = metrics["contracts"]
    lines = [
        f"- **版本:** `{metrics.get('project_version')}`（来源 `pyproject.toml`）",
        f"- **测试资产:** {_fmt(tests['python']['files'])} 个 pytest 文件"
        f" / {_fmt(tests['python']['functions'])} 个测试函数"
        f"；Worker {_fmt(tests['worker']['files'])} 文件 / {_fmt(tests['worker']['cases'])} 用例"
        f"；JS {_fmt(tests['js']['files'])} 文件",
        f"- **代码规模:** Python {_fmt(code['python']['files'])} 文件"
        f" / {_fmt(code['python']['loc'])} 行"
        f"；Worker TS {_fmt(code['worker_ts']['files'])} 文件"
        f" / {_fmt(code['worker_ts']['loc'])} 行",
        f"- **Schema:** {_fmt(contracts['schemas']['total'])} 份"
        f"（契约文档 §10.2 原声称 {_fmt(contracts['schemas']['canonical_claimed'])} 份）",
        f"- **ADR:** {_fmt(contracts['adr']['total'])} 份",
        "- **覆盖率:** 不声明 —— 仓库内不存在 `--cov-fail-under` 门禁，发布覆盖率数字不可验证",
        "- **基线提交:** 见 `git rev-parse HEAD`（文档不固定 commit，避免自引用失效）",
        "- **生产状态:** 属运行时事实，见 `docs/status.md`，不在本文件静态声明",
    ]
    return "\n".join([*lines, "", f"> {GENERATED_NOTE}"])


def render_quickref(metrics: dict[str, Any]) -> str:
    targets = metrics["targets"]
    sources = metrics["sources"]
    coverage = sources["coverage"]
    scopes = targets["by_scope"]
    tests = metrics["tests"]["python"]
    eval_sets = " / ".join(str(item["items"]) for item in metrics["eval"]["sets"])
    lines = [
        "- **Python 版本**：3.11+ / Pydantic v2",
        f"- **测试规模**：{_fmt(tests['files'])} 个 pytest 文件"
        f" / {_fmt(tests['functions'])} 个测试函数"
        "；ruff=0, mypy=0（可执行用例数由 CI 汇总）",
        f"- **监控目标**：{_fmt(targets['total'])} targets"
        f"（{scopes.get('country', 0)} 国家 / {scopes.get('region', 0)} 区域"
        f" / {scopes.get('continent', 0)} 大洲 / {scopes.get('global', 0)} 全球）",
        f"- **信源规模**：{_fmt(sources['total'])} 个源文件"
        f"（{_fmt(sources['by_type'].get('rss', 0))} RSS"
        f" + {_fmt(sources['by_type'].get('api', 0))} API）"
        f"；canonical 覆盖 {coverage['ready_targets']}/{coverage['target_count']} target 达标"
        f"（≥{coverage['minimum_refs']} 条有效引用，共 {_fmt(coverage['source_ref_total'])} 条引用"
        f" / {_fmt(coverage['valid_source_ref_total'])} 条有效）",
        f"- **评测集**：{eval_sets}（v1/v2/v3）",
        "- **AI Provider**：内置 chain: Gemini → DeepSeek → Groq → Cloudflare Workers AI"
        " → OpenRouter → NVIDIA/Agnes/OpenCode/Reka",
        "- **部署方式**：Cloudflare Pages + Workers + D1/R2；"
        "Cloudflare Containers 承接过渡期 Python/RSS-Bridge 后台面；"
        "VPS/Tunnel 仅作 legacy rollback，不是运行依赖",
        "- **可选组件**：`[api]` FastAPI + Web UI（管理后台 + 公开新闻阅读器）",
    ]
    return "\n".join([*lines, "", f"> {GENERATED_NOTE}"])


def render_architecture_tests(metrics: dict[str, Any]) -> str:
    tests = metrics["tests"]
    summary = (
        f"**{_fmt(tests['python']['files'])} 个 pytest 文件"
        f" / {_fmt(tests['python']['functions'])} 个测试函数"
        f"；Worker {_fmt(tests['worker']['files'])} 文件"
        f" / {_fmt(tests['worker']['cases'])} 用例"
        f"；JS {_fmt(tests['js']['files'])} 文件。**"
    )
    gap = "覆盖率不在文档中声明：仓库内不存在 `--cov-fail-under` 门禁。"
    return "\n\n".join([summary, gap, f"> {GENERATED_NOTE}"])


RENDERERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "readme-tagline": render_readme_tagline,
    "readme-badges": render_readme_badges,
    "status": render_status,
    "quickref": render_quickref,
    "architecture-tests": render_architecture_tests,
}


def replace_block(text: str, name: str, body: str) -> tuple[str, bool]:
    """替换单个生成区间，返回（新文本, 是否有变化）。"""
    pattern = re.compile(
        re.escape(_marker(name, "BEGIN")) + r".*?" + re.escape(_marker(name, "END")),
        re.DOTALL,
    )
    if not pattern.search(text):
        raise KeyError(f"缺少生成区间标记: {name}")
    replacement = _block(name, body)
    updated = pattern.sub(lambda _: replacement, text)
    return updated, updated != text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--metrics", type=Path, default=DEFAULT_METRICS)
    parser.add_argument("--check", action="store_true", help="只校验，不写入")
    args = parser.parse_args(argv)

    if not args.metrics.is_file():
        print(f"FAIL: 缺少 {args.metrics.relative_to(PROJECT_ROOT)}，请先运行 tools/gen_metrics.py")
        return 1
    metrics = json.loads(args.metrics.read_text(encoding="utf-8"))

    stale: list[str] = []
    for relative, names in DOC_BLOCKS.items():
        path = PROJECT_ROOT / relative
        if not path.is_file():
            print(f"FAIL: 缺少文档 {relative}")
            return 1
        text = path.read_text(encoding="utf-8")
        for name in names:
            try:
                text, changed = replace_block(text, name, RENDERERS[name](metrics))
            except KeyError as error:
                print(f"FAIL: {relative} {error}")
                return 1
            if changed:
                stale.append(f"{relative}#{name}")
        if not args.check:
            path.write_text(text, encoding="utf-8")

    if args.check:
        if stale:
            print("FAIL: 以下生成区间与事实基线不一致，请运行 python tools/render_docs.py")
            for item in stale:
                print(f"  - {item}")
            return 1
        print("OK: 所有生成区间与事实基线一致")
        return 0

    if stale:
        print("已更新生成区间：")
        for item in stale:
            print(f"  - {item}")
    else:
        print("所有生成区间已是最新")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
