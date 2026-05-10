#!/usr/bin/env python3
"""扫描 memory/ 和 config/ 目录中的敏感关键词。

CI 安全扫描工具：拒绝包含 cookie/token/password/bearer/secret
等敏感关键词的 YAML 文件进入仓库。

用法：
    python tools/scan_sensitive_data.py [ROOT_DIR]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SENSITIVE_KEYWORDS = [
    "cookie",
    "bearer",
    "password",
    "session_key",
    "access_token",
    "api_key",
    "secret",
]

# 不扫描的目录
EXCLUDE_DIRS = {".venv", "node_modules", ".git", "__pycache__", ".omc"}

# 扫描的文件模式
SCAN_PATTERNS = [
    "memory/**/*.yaml",
    "memory/**/*.yml",
    "config/**/*.yaml",
    "config/**/*.yml",
]

# 字段值中允许出现关键词的豁免字段名（如描述性说明）
ALLOWED_FIELD_NAMES = {"description", "display_name", "notes"}

# 关键词匹配模式：匹配冒号后的值部分（即 YAML 值）
VALUE_PATTERN = re.compile(r":\s*[\"']?(.+?)[\"']?\s*$")


def scan_file(filepath: Path) -> list[tuple[int, str, str]]:
    """扫描单个文件，返回 (行号, 关键词, 行内容) 列表。"""
    hits: list[tuple[int, str, str]] = []
    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception:
        return hits

    for line_num, line in enumerate(content.splitlines(), 1):
        # 跳过注释行
        stripped = line.strip()
        if stripped.startswith("#"):
            continue

        # 提取 YAML 键和值
        if ":" not in line:
            continue

        key_part, _, value_part = line.partition(":")
        field_name = key_part.strip().split(".")[-1]  # 取最后一段

        # 豁免字段名（如 description: "使用 cookie 认证" 允许提及）
        if field_name in ALLOWED_FIELD_NAMES:
            continue

        value_lower = value_part.lower()
        for keyword in SENSITIVE_KEYWORDS:
            # 匹配关键词作为值的一部分（而非键名）
            if keyword in value_lower:
                # 排除纯描述性提及（如 "requires session_profile"）
                # 只匹配看起来像实际值的情况
                value_stripped = value_part.strip().strip("\"'")
                if keyword in value_stripped.lower() and "=" in value_stripped:
                    hits.append((line_num, keyword, stripped))
                    break
                # 也匹配明显的 token 值模式
                if re.search(rf"\b{keyword}\s*[=:]\s*\S+", value_lower):
                    hits.append((line_num, keyword, stripped))
                    break

    return hits


def scan(root: Path) -> int:
    """扫描所有目标文件，返回发现的问题数量。"""
    all_hits: list[tuple[Path, int, str, str]] = []

    for pattern in SCAN_PATTERNS:
        for filepath in root.glob(pattern):
            if any(part in filepath.parts for part in EXCLUDE_DIRS):
                continue
            if filepath.name.endswith(".local.yaml") or filepath.name.endswith(
                ".local.yml"
            ):
                continue
            if filepath.name.endswith(".actual.yaml") or filepath.name.endswith(
                ".actual.yml"
            ):
                continue
            for line_num, keyword, line_content in scan_file(filepath):
                all_hits.append((filepath, line_num, keyword, line_content))

    if all_hits:
        print(f"❌ 发现 {len(all_hits)} 处敏感数据：\n")
        for filepath, line_num, keyword, line_content in all_hits:
            print(f"  {filepath}:{line_num} [{keyword}] {line_content!r}")
        return len(all_hits)

    print("✅ 未发现敏感数据")
    return 0


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    count = scan(root)
    sys.exit(1 if count > 0 else 0)
