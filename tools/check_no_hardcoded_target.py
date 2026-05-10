#!/usr/bin/env python3
"""自动化硬编码检测：扫描 core/skills/adapters 目录中的意大利专有字符串。

Phase 7 验收工具：确保核心代码不含意大利硬编码，新增国家只需配置。

用法：
    python tools/check_no_hardcoded_target.py [ROOT_DIR]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# 意大利特有字符串（不应出现在 core/ 和 skills/ 目录中）
ITALY_PATTERNS = [
    (r'\bitaly\b(?!\s*["\']?\s*[:=])', "italy 出现在非配置读取场景"),
    (r'\bansa\b', "意大利 ANSA 通讯社"),
    (r'\bcorriere\b', "意大利 Corriere della Sera"),
    (r'\brepubblica\b', "意大利 La Repubblica"),
    (r'\bgiorgiam?eloni\b', "意大利政客名"),
    (r'\bmeloni\b', "意大利政客名（Meloni）"),
    (r'\bitalian[oa]?\b', "Italian 意大利语/人"),
    (r'\bgiorno\b', "意大利语 giorno"),
    (r'language\s*=\s*["\']it["\']', "硬编码语言代码 'it'"),
    (r'\bfisco\b', "意大利财政术语"),
    (r'\bbankitalia\b', "意大利央行"),
    (r'\bspread\b', "意大利金融术语 spread（需人工确认）"),
]

# 允许出现的场景（注释、docstring、类型标注）
ALLOWED_PATTERNS = [
    r'#.*$',  # 注释行
    r'^\s*"""',  # docstring 开始
    r'^\s*"""$',  # docstring 结束
]

# 扫描目录
SCAN_DIRS = [
    "src/news_sentry/core/",
    "src/news_sentry/skills/",
    "src/news_sentry/adapters/",
]


class HardcodedMatch:
    """一条硬编码匹配结果。"""

    def __init__(self, file: str, line_number: int, line_content: str, pattern: str, description: str):
        self.file = file
        self.line_number = line_number
        self.line_content = line_content
        self.pattern = pattern
        self.description = description

    def __repr__(self) -> str:
        return f"{self.file}:{self.line_number} [{self.description}] {self.line_content!r}"


def is_in_docstring_or_comment(line: str) -> bool:
    """判断该行是否是注释或 docstring 的一部分。"""
    stripped = line.strip()
    if stripped.startswith("#"):
        return True
    if stripped.startswith('"""') or stripped.startswith("'''"):
        return True
    # 以 " 如 " 开头的 docstring 行
    if stripped.startswith('"') and '"""' not in stripped:
        return True
    return False


def scan_for_hardcoded_target(
    root: Path,
    patterns: list[tuple[str, str]],
    scan_dirs: list[str],
) -> list[HardcodedMatch]:
    """扫描指定目录中的意大利硬编码，返回匹配列表。"""
    matches: list[HardcodedMatch] = []

    for scan_dir in scan_dirs:
        dir_path = root / scan_dir
        if not dir_path.exists():
            continue
        for py_file in dir_path.rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8")
            except Exception:
                continue

            in_docstring = False
            for i, line in enumerate(content.splitlines(), 1):
                # 跟踪 docstring 块
                if '"""' in line or "'''" in line:
                    count = line.count('"""') + line.count("'''")
                    if count == 1:
                        in_docstring = not in_docstring

                # 跳过注释行
                if line.strip().startswith("#"):
                    continue

                # 跳过 docstring 内行
                if in_docstring:
                    continue

                # 跳过纯 docstring 行（单行 docstring）
                stripped = line.strip()
                if stripped.startswith('"""') and stripped.endswith('"""') and len(stripped) > 6:
                    continue

                for pat, desc in patterns:
                    if re.search(pat, line, re.IGNORECASE):
                        matches.append(HardcodedMatch(
                            file=str(py_file.relative_to(root)),
                            line_number=i,
                            line_content=stripped,
                            pattern=pat,
                            description=desc,
                        ))

    return matches


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    matches = scan_for_hardcoded_target(root, ITALY_PATTERNS, SCAN_DIRS)

    # 过滤掉明确的合法引用（注释和示例中的）
    real_matches = [
        m for m in matches
        if not any(
            exc in m.line_content.lower()
            for exc in ["如", "例如", "example", "比如"]
        )
    ]

    if real_matches:
        print(f"❌ 发现 {len(real_matches)} 处疑似意大利硬编码：\n")
        for m in real_matches:
            print(f"  {m}")
        print(f"\n请确认这些是否为核心代码中的硬编码。如果是，请重构为配置驱动。")
        sys.exit(1)

    print("✅ 无意大利硬编码（core/skills/adapters 中未发现意大利专有字符串）")
    sys.exit(0)
