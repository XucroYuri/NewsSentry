#!/usr/bin/env python3
"""L1.5 隔离哨兵：证明一条轨道的写入不会到达另一条轨道。

**为什么需要阳性对照**：只查"哨兵不在对照组"是没有意义的 ——
查询过滤本身就能造成"查不到"。因此本工具的验证要求**两条**同时成立：

1. **阳性对照**：哨兵**确实**出现在被写入的轨道里（证明写入与查询都工作）
2. **隔离成立**：哨兵**不**出现在另一条轨道里

并且**两组结果集都必须非空** —— 空集合下"查不到"不构成证据。

用法：
    python tools/isolation_proof.py make-sentinel --target preview
    python tools/isolation_proof.py sentinel-sql --sentinel <id> --target preview --output s.sql
    python tools/isolation_proof.py verify --sentinel <id> --written-to treatment \\
        --control-events control.json --treatment-events treatment.json
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.control_common import TRACKS, ControlError, event_ids, load_rows  # noqa: E402

SENTINEL_PREFIX = "iso-sentinel-"


def make_sentinel_id(*, target_id: str, nonce: str) -> str:
    """确定性地生成哨兵 id：同一 (target, nonce) 必然得到同一 id。"""
    if not target_id.strip():
        raise ControlError("target_id 不能为空")
    if not nonce.strip():
        raise ControlError("nonce 不能为空")
    digest = hashlib.sha256(f"{target_id}:{nonce}".encode()).hexdigest()[:12]
    return f"{SENTINEL_PREFIX}{target_id}-{digest}"


def build_sentinel_sql(
    *, sentinel_id: str, target_id: str, source_id: str, observed_at: str
) -> str:
    """产出可对目标 D1 执行的 INSERT（幂等：ON CONFLICT DO NOTHING）。

    只填充 `events` 表的 NOT NULL 列，其余走默认值 —— 哨兵不参与研判，
    它的唯一作用是"在两条轨道的集合运算中可被区分"。
    """
    if not sentinel_id.startswith(SENTINEL_PREFIX):
        raise ControlError(f"哨兵 id 必须以 {SENTINEL_PREFIX!r} 开头: {sentinel_id!r}")
    for label, value in (("target_id", target_id), ("source_id", source_id)):
        if not value.strip():
            raise ControlError(f"{label} 不能为空")
    if not observed_at.strip():
        raise ControlError("observed_at 不能为空")

    def _q(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    return (
        "INSERT INTO events (event_id, target_id, source_id, published_at, collected_at,"
        " title, summary, pipeline_stage, source_name, source_type, value_label)\n"
        f"VALUES ({_q(sentinel_id)}, {_q(target_id)}, {_q(source_id)},"
        f" {_q(observed_at)}, {_q(observed_at)},"
        f" {_q('Isolation sentinel (synthetic; not news)')},"
        f" {_q('Written by tools/isolation_proof.py to prove cross-track isolation.')},"
        f" {_q('collected')}, {_q('isolation-sentinel')}, {_q('synthetic')},"
        f" {_q('哨兵')})\n"
        "ON CONFLICT(event_id) DO NOTHING;\n"
    )


def verify_isolation(
    *,
    sentinel_id: str,
    written_to: str,
    control_rows: list[dict],
    treatment_rows: list[dict],
) -> dict[str, object]:
    """三条判据：双方非空、阳性对照成立、另一轨不含哨兵。"""
    if written_to not in TRACKS:
        raise ControlError(f"written-to 必须是 {TRACKS} 之一: {written_to!r}")
    if not sentinel_id.startswith(SENTINEL_PREFIX):
        raise ControlError(f"哨兵 id 必须以 {SENTINEL_PREFIX!r} 开头: {sentinel_id!r}")

    control_ids = set(event_ids(control_rows))
    treatment_ids = set(event_ids(treatment_rows))

    written_ids, other_ids = (
        (treatment_ids, control_ids) if written_to == "treatment" else (control_ids, treatment_ids)
    )
    other_track = "control" if written_to == "treatment" else "treatment"

    checks = {
        "written_track_non_empty": len(written_ids) > 0,
        "other_track_non_empty": len(other_ids) > 0,
        "positive_control_sentinel_present": sentinel_id in written_ids,
        "isolation_sentinel_absent_in_other": sentinel_id not in other_ids,
    }
    failures: list[str] = []
    if not checks["written_track_non_empty"]:
        failures.append(f"{written_to} 结果集为空 —— 无法判定（查询可能失败）")
    if not checks["other_track_non_empty"]:
        failures.append(f"{other_track} 结果集为空 —— 无法判定（查询可能失败）")
    if not checks["positive_control_sentinel_present"]:
        failures.append(f"阳性对照失败：哨兵未出现在写入轨 {written_to}")
    if not checks["isolation_sentinel_absent_in_other"]:
        failures.append(f"隔离失败：哨兵出现在 {other_track}（跨轨写入）")

    return {
        "sentinel_id": sentinel_id,
        "written_to": written_to,
        "other_track": other_track,
        "control_ids": len(control_ids),
        "treatment_ids": len(treatment_ids),
        "checks": checks,
        "verdict": "PASS" if not failures else "FAIL",
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    make = sub.add_parser("make-sentinel", help="确定性生成哨兵 id")
    make.add_argument("--target", required=True)
    make.add_argument("--nonce", required=True)

    sql = sub.add_parser("sentinel-sql", help="产出写入哨兵的 SQL")
    sql.add_argument("--sentinel", required=True)
    sql.add_argument("--target", required=True)
    sql.add_argument("--source", default="isolation-sentinel")
    sql.add_argument("--observed-at", required=True)
    sql.add_argument("--output", type=Path, required=True)

    verify = sub.add_parser("verify", help="验证隔离（要求阳性对照 + 双方非空）")
    verify.add_argument("--sentinel", required=True)
    verify.add_argument("--written-to", required=True, choices=list(TRACKS))
    verify.add_argument("--control-events", type=Path, required=True)
    verify.add_argument("--treatment-events", type=Path, required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "make-sentinel":
            print(make_sentinel_id(target_id=args.target, nonce=args.nonce))
            return 0
        if args.command == "sentinel-sql":
            statement = build_sentinel_sql(
                sentinel_id=args.sentinel,
                target_id=args.target,
                source_id=args.source,
                observed_at=args.observed_at,
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(statement, encoding="utf-8")
            print(f"写入 {args.output}")
            return 0
        result = verify_isolation(
            sentinel_id=args.sentinel,
            written_to=args.written_to,
            control_rows=load_rows(args.control_events),
            treatment_rows=load_rows(args.treatment_events),
        )
        print(
            f"哨兵 {result['sentinel_id']} → 写入轨 {result['written_to']}；"
            f"control={result['control_ids']} treatment={result['treatment_ids']}"
        )
        for name, ok in dict(result["checks"]).items():  # type: ignore[arg-type]
            print(f"  {'✅' if ok else '❌'} {name}")
        print(f"判定：{result['verdict']}")
        for failure in list(result["failures"]):  # type: ignore[arg-type]
            print(f"  - {failure}")
        return 0 if result["verdict"] == "PASS" else 1
    except ControlError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    sys.exit(main())
