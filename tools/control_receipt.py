#!/usr/bin/env python3
"""L1.3 对照回执协议：两条轨道写同一份 schema，这是"可比性"的物理保证。

回执把一次运行的**可比较事实**固定下来：commit、时间窗、事件集合摘要、
研判结果摘要、CPU 分位、信源 ok 率、制品体积、成本、静默错误、连续槽位。

**为什么需要它**：没有统一的回执，两组的"读数"就无法配对，
任何"实验组更好"的说法都退化为叙事（宪法 T3 / INV-B）。

用法：
    python tools/control_receipt.py build --track control --environment production \\
        --run-id r-1 --commit <40hex> --events rows.json \\
        --window-start 2026-09-19T00:00:00Z --window-end 2026-09-20T00:00:00Z \\
        --cpu-p50 1.2 --cpu-p99 4.1 --cpu-samples 1200 --output receipt.json
    python tools/control_receipt.py validate --input receipt.json

本工具不做网络 I/O：``--events`` 是已经取好的 ``wrangler d1 execute --json`` 结果集。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.control_common import (  # noqa: E402
    RECEIPT_VERSION,
    TRACKS,
    ControlError,
    events_digest,
    load_rows,
    require_commit,
    require_digest,
    require_int,
    require_number,
    scores_digest,
)

# 允许为 null 的字段：环境相关事实，取不到时**不得臆造**（宪法 L0 生成器原则）
NULLABLE_FIELDS = ("artifact_bytes", "dependency_count", "incremental_cost_usd")


def _iso(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ControlError(f"{label} 必须是非空 ISO 8601 字符串: {value!r}")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ControlError(f"{label} 不是合法 ISO 8601: {value!r}") from exc
    return value


def _stage_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        stage = row.get("pipeline_stage")
        key = stage if isinstance(stage, str) and stage else "unknown"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def build_receipt(
    *,
    track: str,
    environment: str,
    run_id: str,
    commit: str,
    rows: list[dict[str, Any]],
    window_start: str,
    window_end: str,
    cpu_p50: float | None,
    cpu_p99: float | None,
    cpu_samples: int,
    source_ok_ratio: float | None,
    artifact_bytes: int | None,
    dependency_count: int | None,
    incremental_cost_usd: float | None,
    silent_errors: int,
    healthy_slots: int,
    control_data_loss: int,
    control_downtime_seconds: int,
) -> dict[str, Any]:
    """组装回执。两组必须用**同一函数**产出，否则 schema 会漂移。"""
    if track not in TRACKS:
        raise ControlError(f"track 必须是 {TRACKS} 之一: {track!r}")
    require_commit(commit, label="commit")
    start = _iso(window_start, label="window.start")
    end = _iso(window_end, label="window.end")
    if start > end:
        raise ControlError(f"window.start 晚于 window.end: {start} > {end}")
    if not run_id.strip():
        raise ControlError("run_id 不能为空")

    cpu: dict[str, Any] = {"samples": require_int(cpu_samples, label="cpu_ms.samples")}
    if cpu["samples"] > 0:
        if cpu_p50 is None or cpu_p99 is None:
            raise ControlError("cpu_samples > 0 时必须同时提供 cpu_p50 与 cpu_p99")
        p50 = require_number(cpu_p50, label="cpu_ms.p50")
        p99 = require_number(cpu_p99, label="cpu_ms.p99")
        if p99 < p50:
            raise ControlError(f"cpu_ms.p99 ({p99}) 不得小于 p50 ({p50})")
        cpu.update({"p50": p50, "p99": p99})
    else:
        cpu.update({"p50": None, "p99": None})

    receipt: dict[str, Any] = {
        "receipt_version": RECEIPT_VERSION,
        "track": track,
        "environment": environment,
        "run_id": run_id,
        "commit": commit,
        "window": {"start": start, "end": end},
        "counts": {"events": len(rows), "by_stage": _stage_counts(rows)},
        "events_digest": events_digest(rows),
        "scores_digest": scores_digest(rows),
        "cpu_ms": cpu,
        "source_ok_ratio": (
            None
            if source_ok_ratio is None
            else require_number(source_ok_ratio, label="source_ok_ratio")
        ),
        "artifact_bytes": artifact_bytes,
        "dependency_count": dependency_count,
        "incremental_cost_usd": incremental_cost_usd,
        "silent_errors": require_int(silent_errors, label="silent_errors"),
        "healthy_slots": require_int(healthy_slots, label="healthy_slots"),
        "control_data_loss": require_int(control_data_loss, label="control_data_loss"),
        "control_downtime_seconds": require_int(
            control_downtime_seconds, label="control_downtime_seconds"
        ),
    }
    validate_receipt(receipt)
    return receipt


def validate_receipt(receipt: dict[str, Any]) -> None:
    """fail-closed 校验：任何形状不符都必须抛错，绝不"尽力而为"地继续。"""
    if receipt.get("receipt_version") != RECEIPT_VERSION:
        raise ControlError(
            f"receipt_version 必须是 {RECEIPT_VERSION!r}: {receipt.get('receipt_version')!r}"
        )
    track = receipt.get("track")
    if track not in TRACKS:
        raise ControlError(f"track 必须是 {TRACKS} 之一: {track!r}")
    require_commit(receipt.get("commit"), label="commit")
    require_digest(receipt.get("events_digest"), label="events_digest")
    require_digest(receipt.get("scores_digest"), label="scores_digest")

    window = receipt.get("window")
    if not isinstance(window, dict):
        raise ControlError("window 必须是对象")
    start = _iso(window.get("start"), label="window.start")
    end = _iso(window.get("end"), label="window.end")
    if start > end:
        raise ControlError(f"window.start 晚于 window.end: {start} > {end}")

    counts = receipt.get("counts")
    if not isinstance(counts, dict):
        raise ControlError("counts 必须是对象")
    require_int(counts.get("events"), label="counts.events")
    if not isinstance(counts.get("by_stage"), dict):
        raise ControlError("counts.by_stage 必须是对象")

    cpu = receipt.get("cpu_ms")
    if not isinstance(cpu, dict):
        raise ControlError("cpu_ms 必须是对象")
    samples = require_int(cpu.get("samples"), label="cpu_ms.samples")
    if samples > 0:
        p50 = require_number(cpu.get("p50"), label="cpu_ms.p50")
        p99 = require_number(cpu.get("p99"), label="cpu_ms.p99")
        if p99 < p50:
            raise ControlError(f"cpu_ms.p99 ({p99}) 不得小于 p50 ({p50})")
    elif samples < 0:
        raise ControlError(f"cpu_ms.samples 不得为负: {samples}")

    for field in NULLABLE_FIELDS:
        value = receipt.get(field)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise ControlError(f"{field} 必须是数值或 null: {value!r}")

    for field in (
        "silent_errors",
        "healthy_slots",
        "control_data_loss",
        "control_downtime_seconds",
    ):
        value = require_int(receipt.get(field), label=field)
        if value < 0:
            raise ControlError(f"{field} 不得为负: {value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="由 D1 结果集产出对照回执")
    build.add_argument("--track", required=True, choices=list(TRACKS))
    build.add_argument("--environment", required=True)
    build.add_argument("--run-id", required=True)
    build.add_argument("--commit", required=True)
    build.add_argument("--events", type=Path, required=True)
    build.add_argument("--window-start", required=True)
    build.add_argument("--window-end", required=True)
    build.add_argument("--cpu-p50", type=float, default=None)
    build.add_argument("--cpu-p99", type=float, default=None)
    build.add_argument("--cpu-samples", type=int, default=0)
    build.add_argument("--source-ok-ratio", type=float, default=None)
    build.add_argument("--artifact-bytes", type=int, default=None)
    build.add_argument("--dependency-count", type=int, default=None)
    build.add_argument("--incremental-cost-usd", type=float, default=None)
    build.add_argument("--silent-errors", type=int, default=0)
    build.add_argument("--healthy-slots", type=int, default=0)
    build.add_argument("--control-data-loss", type=int, default=0)
    build.add_argument("--control-downtime-seconds", type=int, default=0)
    build.add_argument("--output", type=Path, required=True)

    validate = sub.add_parser("validate", help="fail-closed 校验一份回执")
    validate.add_argument("--input", type=Path, required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            rows = load_rows(args.events)
            receipt = build_receipt(
                track=args.track,
                environment=args.environment,
                run_id=args.run_id,
                commit=args.commit,
                rows=rows,
                window_start=args.window_start,
                window_end=args.window_end,
                cpu_p50=args.cpu_p50,
                cpu_p99=args.cpu_p99,
                cpu_samples=args.cpu_samples,
                source_ok_ratio=args.source_ok_ratio,
                artifact_bytes=args.artifact_bytes,
                dependency_count=args.dependency_count,
                incremental_cost_usd=args.incremental_cost_usd,
                silent_errors=args.silent_errors,
                healthy_slots=args.healthy_slots,
                control_data_loss=args.control_data_loss,
                control_downtime_seconds=args.control_downtime_seconds,
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print(
                f"写入回执 {args.output}"
                f"（track={receipt['track']}, events={receipt['counts']['events']}）"
            )
            return 0
        # validate
        raw = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ControlError("回执顶层必须是对象")
        validate_receipt(raw)
        print(f"OK: 回执合法（track={raw['track']}, commit={raw['commit'][:12]}）")
        return 0
    except ControlError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    sys.exit(main())
