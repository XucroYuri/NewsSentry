#!/usr/bin/env python3
"""L1.4 / L1.6 对照读数与支配判定。

从两条轨道的 D1 事件集（+ 可选回执）计算六项对照指标，并据**四条规则 + 绝对地板**
给出支配判定。**判定不可人工覆盖**：没有任何命令行开关能把 not_dominant 变成 dominant。

四条规则（``docs/spec/02-engineering-baseline.md §3.4``）：

1. **无短板** —— 六项指标实验组均不劣于对照组
2. **有优势** —— 至少三项严格优于对照组
3. **够持久** —— 连续健康槽位 ≥ 28（7 天，复用 continuity 账本口径）
4. **零代价** —— 对照组数据零损失、零停机

**绝对地板**（不可协商，因为对照组自身 ok 率仅约 74%，相对比较可能"轻松赢"）：
E2 召回 ≥ 99%；对照组信源 ok 率 ≥ 90%；E3 摘要差异 = 0；
E1 CPU p99 < 10ms；E4 制品 < 200KB 且 0 依赖；E6 静默错误 = 0。

**fail-closed**：任何指标缺少 A/B 双方数据即记为 ``present=false``，
而**缺失一律判定为不满足**（宪法 INV-B：没有 A/B 数据就没有结论）。

用法：
    python tools/control_compare.py compare \\
        --control-events control.json --treatment-events treatment.json \\
        --control-receipt control-receipt.json --treatment-receipt treatment-receipt.json \\
        --output dominance.json
    python tools/control_compare.py compare ... --assert-dominance   # 未支配则 exit 1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from tools.control_common import (
    ControlError,
    events_digest,
    load_json_object,
    load_rows,
    sha256_digest,
)

SCHEMA_VERSION = "news-sentry.control-dominance.v1"

# 支配规则阈值（与 SPEC 对齐，不通过 CLI 暴露以免被"调参通过"）
REQUIRED_STRICT_ADVANTAGES = 3
REQUIRED_HEALTHY_SLOTS = 28

# 绝对地板
FLOOR_RECALL = 0.99
FLOOR_CONTROL_SOURCE_OK_RATIO = 0.90
FLOOR_CPU_P99_MS = 10.0
FLOOR_ARTIFACT_BYTES = 200 * 1024
FLOOR_DEPENDENCY_COUNT = 0
FLOOR_DIGEST_DIFF = 0
FLOOR_SILENT_ERRORS = 0

MAX_LISTED_IDS = 50


def _score_map(rows: list[dict[str, Any]]) -> dict[str, tuple[Any, Any]]:
    """event_id -> (value_score, pipeline_stage)，用于 E3 对等比较。"""
    out: dict[str, tuple[Any, Any]] = {}
    for index, row in enumerate(rows):
        event_id = row.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            raise ControlError(f"第 {index} 行缺少非空 event_id")
        stage = row.get("pipeline_stage")
        out[event_id] = (row.get("value_score"), stage if isinstance(stage, str) else None)
    return out


def compare_event_sets(
    control_rows: list[dict[str, Any]], treatment_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """集合运算：召回 / 精确 / 双向差异 / E3 摘要差异。"""
    control_ids = set(_score_map(control_rows))
    treatment_ids = set(_score_map(treatment_rows))
    common = control_ids & treatment_ids
    missing = sorted(control_ids - treatment_ids)  # 对照组看到、实验组漏掉（危险方向）
    extra = sorted(treatment_ids - control_ids)

    control_scores = _score_map(control_rows)
    treatment_scores = _score_map(treatment_rows)
    digest_diff = sorted(
        event_id for event_id in common if control_scores[event_id] != treatment_scores[event_id]
    )

    recall = len(common) / len(control_ids) if control_ids else 0.0
    precision = len(common) / len(treatment_ids) if treatment_ids else 0.0

    return {
        "control_events": len(control_ids),
        "treatment_events": len(treatment_ids),
        "common": len(common),
        "recall": recall,
        "precision": precision,
        "missing_from_treatment_count": len(missing),
        "missing_from_treatment_sample": missing[:MAX_LISTED_IDS],
        "extra_in_treatment_count": len(extra),
        "extra_in_treatment_sample": extra[:MAX_LISTED_IDS],
        "digest_diff_count": len(digest_diff),
        "digest_diff_sample": digest_diff[:MAX_LISTED_IDS],
    }


def _metric(
    metric_id: str,
    name: str,
    *,
    control: float | None,
    treatment: float | None,
    lower_is_better: bool = True,
    absolute_ok: bool | None,
    absolute_requirement: str,
) -> dict[str, Any]:
    """构造一项指标读数。

    ``control``/``treatment`` 为 None 表示**该侧数据缺失** —— 缺失一律判不满足。
    """
    present = control is not None and treatment is not None
    normalized: dict[str, float | None] = {"control": None, "treatment": None}
    not_worse: bool | None = None
    strictly_better: bool | None = None

    if present:
        assert control is not None and treatment is not None
        if lower_is_better:
            normalized = {"control": control, "treatment": treatment}
        else:
            normalized = {"control": -control, "treatment": -treatment}
        not_worse = normalized["treatment"] <= normalized["control"]
        strictly_better = normalized["treatment"] < normalized["control"]

    return {
        "id": metric_id,
        "name": name,
        "value": {"control": control, "treatment": treatment},
        "normalized_lower_is_better": normalized,
        "absolute_requirement": absolute_requirement,
        "absolute_ok": absolute_ok,
        "present": present,
        "not_worse": not_worse,
        "strictly_better": strictly_better,
    }


def _receipt_value(receipt: dict[str, Any] | None, *path: str) -> Any:
    node: Any = receipt
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def evaluate_dominance(
    sets: dict[str, Any],
    control_receipt: dict[str, Any] | None,
    treatment_receipt: dict[str, Any] | None,
) -> dict[str, Any]:
    """六项指标 + 四条规则 + 绝对地板 → 支配判定。"""
    c_cpu = _receipt_value(control_receipt, "cpu_ms", "p99")
    t_cpu = _receipt_value(treatment_receipt, "cpu_ms", "p99")
    c_ok = _receipt_value(control_receipt, "source_ok_ratio")
    c_bytes = _receipt_value(control_receipt, "artifact_bytes")
    t_bytes = _receipt_value(treatment_receipt, "artifact_bytes")
    t_deps = _receipt_value(treatment_receipt, "dependency_count")
    t_cost = _receipt_value(treatment_receipt, "incremental_cost_usd")
    c_cost = _receipt_value(control_receipt, "incremental_cost_usd")
    t_silent = _receipt_value(treatment_receipt, "silent_errors")
    c_silent = _receipt_value(control_receipt, "silent_errors")
    t_slots = _receipt_value(treatment_receipt, "healthy_slots")
    c_loss = _receipt_value(control_receipt, "control_data_loss")
    t_loss = _receipt_value(treatment_receipt, "control_data_loss")
    c_down = _receipt_value(control_receipt, "control_downtime_seconds")
    t_down = _receipt_value(treatment_receipt, "control_downtime_seconds")

    recall = sets["recall"]
    digest_diff = sets["digest_diff_count"]

    metrics = [
        _metric(
            "E1",
            "Worker 单源采集 CPU p99",
            control=_num(c_cpu),
            treatment=_num(t_cpu),
            absolute_ok=(None if _num(t_cpu) is None else _num(t_cpu) < FLOOR_CPU_P99_MS),
            absolute_requirement=f"treatment < {FLOOR_CPU_P99_MS} ms",
        ),
        _metric(
            "E2",
            "事件召回率",
            control=1.0,  # 对照组对自身恒为 1.0；相对比较由 treatment 召回承担
            treatment=recall,
            lower_is_better=False,
            absolute_ok=(
                recall >= FLOOR_RECALL
                and _num(c_ok) is not None
                and _num(c_ok) >= FLOOR_CONTROL_SOURCE_OK_RATIO
            ),
            absolute_requirement=(
                f"recall >= {FLOOR_RECALL} 且对照组 source_ok_ratio "
                f">= {FLOOR_CONTROL_SOURCE_OK_RATIO}"
            ),
        ),
        _metric(
            "E3",
            "研判结果摘要差异",
            control=0.0,  # 对照组对自身恒为 0
            treatment=float(digest_diff),
            absolute_ok=digest_diff == FLOOR_DIGEST_DIFF,
            absolute_requirement=f"差异 = {FLOOR_DIGEST_DIFF}",
        ),
        _metric(
            "E4",
            "前端制品体积",
            control=_num(c_bytes),
            treatment=_num(t_bytes),
            absolute_ok=(
                None
                if _num(t_bytes) is None
                else (_num(t_bytes) < FLOOR_ARTIFACT_BYTES and t_deps == FLOOR_DEPENDENCY_COUNT)
            ),
            absolute_requirement=(
                f"treatment < {FLOOR_ARTIFACT_BYTES} B 且 dependency_count = "
                f"{FLOOR_DEPENDENCY_COUNT}"
            ),
        ),
        _metric(
            "E5",
            "账号级增量成本",
            control=_num(c_cost),
            treatment=_num(t_cost),
            absolute_ok=(None if _num(t_cost) is None else _num(t_cost) <= 0.0),
            absolute_requirement="treatment <= 0.0 美元/月",
        ),
        _metric(
            "E6",
            "静默错误数",
            control=_num(c_silent),
            treatment=_num(t_silent),
            absolute_ok=(None if _num(t_silent) is None else _num(t_silent) == FLOOR_SILENT_ERRORS),
            absolute_requirement=f"treatment = {FLOOR_SILENT_ERRORS}",
        ),
    ]

    # 规则 1：无短板（缺失即不满足）
    no_weakness = all(m["present"] and m["not_worse"] is True for m in metrics)
    # 规则 2：至少三项严格优
    strict_count = sum(1 for m in metrics if m["strictly_better"] is True)
    has_advantage = strict_count >= REQUIRED_STRICT_ADVANTAGES
    # 规则 3：连续健康槽位
    persistent = _num(t_slots) is not None and _num(t_slots) >= REQUIRED_HEALTHY_SLOTS
    # 规则 4：对照组零代价
    zero_cost = _num(c_loss) == 0 and _num(t_loss) == 0 and _num(c_down) == 0 and _num(t_down) == 0
    # 绝对地板
    floors_ok = all(m["absolute_ok"] is True for m in metrics)

    rules = {
        "no_weakness": no_weakness,
        "has_advantage": has_advantage,
        "strict_advantage_count": strict_count,
        "strict_advantage_required": REQUIRED_STRICT_ADVANTAGES,
        "persistent": persistent,
        "healthy_slots": _num(t_slots),
        "healthy_slots_required": REQUIRED_HEALTHY_SLOTS,
        "zero_cost": zero_cost,
        "absolute_floors": floors_ok,
    }

    blockers: list[str] = []
    for metric in metrics:
        if not metric["present"]:
            blockers.append(f"{metric['id']} 缺少 A/B 双方数据（缺失即不满足）")
        elif not metric["not_worse"]:
            blockers.append(f"{metric['id']} 实验组劣于对照组")
        if metric["absolute_ok"] is False:
            blockers.append(f"{metric['id']} 未达绝对地板：{metric['absolute_requirement']}")
    if not has_advantage:
        blockers.append(f"严格优指标仅 {strict_count} 项，需 ≥ {REQUIRED_STRICT_ADVANTAGES}")
    if not persistent:
        blockers.append(f"连续健康槽位不足（需 ≥ {REQUIRED_HEALTHY_SLOTS}）")
    if not zero_cost:
        blockers.append("对照组出现数据损失或停机")

    verdict = (
        "dominant"
        if all(
            rules[key]
            for key in (
                "no_weakness",
                "has_advantage",
                "persistent",
                "zero_cost",
                "absolute_floors",
            )
        )
        else "not_dominant"
    )

    return {"metrics": metrics, "rules": rules, "verdict": verdict, "blockers": blockers}


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def build_report(
    control_rows: list[dict[str, Any]],
    treatment_rows: list[dict[str, Any]],
    control_receipt: dict[str, Any] | None,
    treatment_receipt: dict[str, Any] | None,
) -> dict[str, Any]:
    sets = compare_event_sets(control_rows, treatment_rows)
    evaluation = evaluate_dominance(sets, control_receipt, treatment_receipt)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_from": {
            "control_events_digest": events_digest(control_rows),
            "treatment_events_digest": events_digest(treatment_rows),
            "control_receipt_digest": (
                None if control_receipt is None else sha256_digest(control_receipt)
            ),
            "treatment_receipt_digest": (
                None if treatment_receipt is None else sha256_digest(treatment_receipt)
            ),
        },
        "event_sets": sets,
        **evaluation,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    compare = sub.add_parser("compare", help="计算对照读数与支配判定")
    compare.add_argument("--control-events", type=Path, required=True)
    compare.add_argument("--treatment-events", type=Path, required=True)
    compare.add_argument("--control-receipt", type=Path)
    compare.add_argument("--treatment-receipt", type=Path)
    compare.add_argument("--output", type=Path)
    compare.add_argument(
        "--assert-dominance",
        action="store_true",
        help="未达支配时以非零退出（判定本身不可被覆盖）",
    )

    args = parser.parse_args(argv)
    try:
        control_rows = load_rows(args.control_events)
        treatment_rows = load_rows(args.treatment_events)
        control_receipt = (
            load_json_object(args.control_receipt, label="control receipt")
            if args.control_receipt
            else None
        )
        treatment_receipt = (
            load_json_object(args.treatment_receipt, label="treatment receipt")
            if args.treatment_receipt
            else None
        )
        report = build_report(control_rows, treatment_rows, control_receipt, treatment_receipt)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print(f"写入 {args.output}")

        rules = report["rules"]
        print(
            "对照读数："
            f"control={report['event_sets']['control_events']} "
            f"treatment={report['event_sets']['treatment_events']} "
            f"common={report['event_sets']['common']} "
            f"recall={report['event_sets']['recall']:.4f} "
            f"digest_diff={report['event_sets']['digest_diff_count']}"
        )
        print(
            f"规则：no_weakness={rules['no_weakness']} "
            f"strict={rules['strict_advantage_count']}/{rules['strict_advantage_required']} "
            f"persistent={rules['persistent']} zero_cost={rules['zero_cost']} "
            f"floors={rules['absolute_floors']}"
        )
        print(f"判定：{report['verdict']}")
        for blocker in report["blockers"]:
            print(f"  - {blocker}")

        if args.assert_dominance and report["verdict"] != "dominant":
            print("FAIL: 未达支配", file=sys.stderr)
            return 1
        return 0
    except ControlError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    sys.exit(main())
