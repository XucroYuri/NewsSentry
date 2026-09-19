#!/usr/bin/env python3
"""对照实验的共享基础件：D1 取数解析、规范摘要、fail-closed 校验。

设计约束（与 tools/cloudflare_preview_guard.py 一致）：

- **不做网络 I/O**：所有输入都是已经取好的 JSON 文件（由 wrangler 或 CI 产出），
  因此本模块可在无凭据环境下被完整测试。
- **fail-closed**：任何形状不符的输入都抛 ``ControlError``，绝不"尽力而为"地继续。
- **可复现摘要**：摘要基于排序后的规范 JSON，跨语言、跨运行一致。

对照主键是 ``events.event_id`` —— 内容寻址（``ne-{target}-{source}-{yyyymmdd}-{hash8}``），
因此**同一源、同一天、同一条新闻在两个运行时必然得到同一个 id**（见
``docs/spec/02-engineering-baseline.md §3.2``）。对照协议由此退化为集合运算。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

TRACKS = ("control", "treatment")
RECEIPT_VERSION = "control-v1"

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class ControlError(RuntimeError):
    """对照实验输入不合契约。fail-closed，绝不降级继续。"""

    exit_code = 2


def parse_d1_rows(raw: str) -> list[dict[str, Any]]:
    """解析 ``wrangler d1 execute --json`` 输出，返回首个结果集的行。

    接受两种已知形状：``[{"results": [...]}]`` 与 ``{"results": [...]}``。
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ControlError(f"D1 输出不是合法 JSON: {exc}") from exc

    if isinstance(payload, list):
        if not payload:
            return []
        first: Any = payload[0]
    else:
        first = payload

    if isinstance(first, dict):
        rows = first.get("results", first.get("result"))
        if isinstance(rows, list):
            return _require_row_dicts(rows)
        if "event_id" in first:  # 单行被直接返回
            return [first]
    if isinstance(first, list):
        return _require_row_dicts(first)

    raise ControlError("D1 输出缺少 results/result 列表")


def _require_row_dicts(rows: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ControlError(f"D1 结果集第 {index} 行不是对象")
        out.append(row)
    return out


def load_rows(path: Path) -> list[dict[str, Any]]:
    """从文件读取并解析 D1 结果集。"""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ControlError(f"无法读取 {path}: {exc}") from exc
    return parse_d1_rows(raw)


def load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    """读取一个 JSON 对象（用于 receipt / dominance 等）。"""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ControlError(f"无法读取 {label} {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ControlError(f"{label} {path} 不是合法 JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ControlError(f"{label} {path} 顶层必须是对象")
    return payload


def canonical_json(value: Any) -> str:
    """规范 JSON 文本：键排序、紧凑分隔符、非 ASCII 原样保留。"""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_digest(value: Any) -> str:
    """对任意可序列化值求规范摘要，形如 ``sha256:<64hex>``。"""
    encoded = canonical_json(value).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def event_ids(rows: list[dict[str, Any]]) -> list[str]:
    """抽取并按字典序排序 event_id 列表（缺字段即 fail-closed）。"""
    ids: list[str] = []
    for index, row in enumerate(rows):
        value = row.get("event_id")
        if not isinstance(value, str) or not value:
            raise ControlError(f"第 {index} 行缺少非空 event_id")
        ids.append(value)
    return sorted(ids)


def events_digest(rows: list[dict[str, Any]]) -> str:
    """事件集合摘要：**两组是否看到同一批新闻**由此退化为一次字符串比较。"""
    return sha256_digest(event_ids(rows))


def scores_digest(rows: list[dict[str, Any]]) -> str:
    """研判结果摘要：``(event_id, value_score, pipeline_stage)`` 排序后的摘要。

    这是 E3（bit-for-bit 对等）的比较对象：**不比数值，比摘要**。
    """
    pairs: list[list[Any]] = []
    for index, row in enumerate(rows):
        event_id = row.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            raise ControlError(f"第 {index} 行缺少非空 event_id")
        score = row.get("value_score")
        if score is not None and not isinstance(score, (int, float)):
            raise ControlError(f"第 {index} 行 value_score 不是数值: {score!r}")
        stage = row.get("pipeline_stage")
        pairs.append([event_id, score, stage if isinstance(stage, str) else None])
    pairs.sort(key=lambda item: item[0])
    return sha256_digest(pairs)


def require_commit(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not COMMIT_RE.match(value):
        raise ControlError(f"{label} 必须是 40 位十六进制 commit: {value!r}")
    return value


def require_digest(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not DIGEST_RE.match(value):
        raise ControlError(f"{label} 必须是 sha256:<64hex>: {value!r}")
    return value


def require_number(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ControlError(f"{label} 必须是数值: {value!r}")
    return float(value)


def require_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ControlError(f"{label} 必须是整数: {value!r}")
    return value
