#!/usr/bin/env python3
"""Phase 13 — Evaluation runner for Judge accuracy benchmarking.

Loads eval-set JSON, runs the full filter→classify→judge pipeline on each
example using real config, compares actual vs expected, and outputs
Precision/Recall/F1 per dimension.

Usage:
    python tools/run_eval.py [--eval-set PATH] [--output PATH] [--target TARGET]
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

# 将项目 src/ 加入 path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import yaml

from news_sentry.core.config import ConfigLoader
from news_sentry.core.memory import Memory
from news_sentry.models.newsevent import (
    JudgeRecommendation,
    NewsEvent,
    PipelineStage,
)
from news_sentry.skills.filter.classifier_rules import ClassifierRules
from news_sentry.skills.filter.rules_filter import RulesFilter
from news_sentry.skills.judge.rules_judge import RulesJudgeSkill


def load_eval_set(path: Path) -> list[dict]:
    """加载 eval-set JSON，返回 examples 列表。"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data["examples"]


def eval_to_event(example: dict) -> NewsEvent:
    """将 eval example 转换为 NewsEvent（stage=collected）。"""
    inp = example["input"]
    return NewsEvent(
        id=example["eval_id"],
        run_id="eval-run",
        source_id=inp.get("source_id", "eval"),
        url=inp.get("url", ""),
        title_original=inp["title_original"],
        content_original=inp["content_original"],
        language=inp.get("language", "mixed"),
        published_at="2026-05-12T00:00:00Z",
        collected_at="2026-05-12T00:00:00Z",
        pipeline_stage=PipelineStage.COLLECTED,
    )


def run_pipeline(
    event: NewsEvent,
    rules_filter: RulesFilter,
    classifier: ClassifierRules,
    judge: RulesJudgeSkill,
) -> NewsEvent | None:
    """对单个事件执行 filter → classify → judge 流水线。

    Returns:
        通过 filter 的事件（已研判），或 None（被 filter 丢弃）。
    """
    # Step 1: filter — 设置 news_value_score
    filtered = rules_filter.filter([event], run_id="eval-run")
    if not filtered:
        return None
    event = filtered[0]

    # Step 2: classify — 设置 metadata.classification
    event = classifier.classify(event)

    # Step 3: judge — 设置 judge_result, china_relevance
    judged = judge.judge([event], run_id="eval-run")
    return judged[0]


def compare_recommendation(
    actual: JudgeRecommendation, expected: str,
) -> str:
    """比对推荐级别，返回 match / partial / miss。"""
    try:
        expected_rec = JudgeRecommendation(expected)
    except ValueError:
        return "miss"

    if actual == expected_rec:
        return "match"

    # partial: publish↔review, review↔archive 相邻级别
    adjacent = {
        JudgeRecommendation.PUBLISH: {JudgeRecommendation.REVIEW},
        JudgeRecommendation.REVIEW: {
            JudgeRecommendation.PUBLISH,
            JudgeRecommendation.ARCHIVE,
        },
        JudgeRecommendation.ARCHIVE: {
            JudgeRecommendation.REVIEW,
            JudgeRecommendation.DISCARD,
        },
        JudgeRecommendation.DISCARD: {JudgeRecommendation.ARCHIVE},
    }
    if actual in adjacent.get(expected_rec, set()):
        return "partial"
    return "miss"


def compare_score(actual: int | None, expected_min: int | None) -> str:
    """比对分值，actual >= expected_min 为 pass。"""
    if expected_min is None:
        return "skip"
    if actual is None:
        return "miss"
    return "pass" if actual >= expected_min else "miss"


def run_evaluation(
    eval_path: Path,
    target_id: str = "italy",
    output_path: Path | None = None,
) -> dict:
    """运行完整评估，返回结果 dict。"""
    examples = load_eval_set(eval_path)

    # 加载目标配置
    loader = ConfigLoader(PROJECT_ROOT)
    config = loader.load_target(target_id, profile_id="local-workstation")

    with tempfile.TemporaryDirectory() as tmpdir:
        memory = Memory(Path(tmpdir) / "memory")

        rules_filter = RulesFilter(config.filter_rules, memory)
        classifier = ClassifierRules(config.classification_rules)
        judge = RulesJudgeSkill(config.classification_rules, memory)

        results: list[dict] = []
        for example in examples:
            event = eval_to_event(example)
            expected = example["expected"]

            judged = run_pipeline(event, rules_filter, classifier, judge)

            if judged is None:
                # 被 filter 丢弃
                results.append({
                    "eval_id": example["eval_id"],
                    "dimension": example.get("dimension", "?"),
                    "filtered_out": True,
                    "recommendation": {
                        "actual": "discard",
                        "expected": expected["recommendation"],
                        "comparison": compare_recommendation(
                            JudgeRecommendation.DISCARD,
                            expected["recommendation"],
                        ),
                    },
                    "news_value_score": {
                        "actual": 0,
                        "expected_min": expected.get("news_value_score_min"),
                        "comparison": "miss",
                    },
                    "china_relevance": {
                        "actual": 0,
                        "expected_min": expected.get("china_relevance_min"),
                        "comparison": compare_score(
                            0, expected.get("china_relevance_min"),
                        ),
                    },
                })
                continue

            actual_rec = (
                judged.judge_result.recommendation
                if judged.judge_result
                else JudgeRecommendation.DISCARD
            )

            rec_comp = compare_recommendation(actual_rec, expected["recommendation"])
            nvs_comp = compare_score(
                judged.news_value_score, expected.get("news_value_score_min"),
            )
            cr_comp = compare_score(
                judged.china_relevance, expected.get("china_relevance_min"),
            )

            results.append({
                "eval_id": example["eval_id"],
                "dimension": example.get("dimension", "?"),
                "filtered_out": False,
                "recommendation": {
                    "actual": actual_rec.value,
                    "expected": expected["recommendation"],
                    "comparison": rec_comp,
                },
                "news_value_score": {
                    "actual": judged.news_value_score,
                    "expected_min": expected.get("news_value_score_min"),
                    "comparison": nvs_comp,
                },
                "china_relevance": {
                    "actual": judged.china_relevance,
                    "expected_min": expected.get("china_relevance_min"),
                    "comparison": cr_comp,
                },
            })

    # ── 聚合统计 ──────────────────────────────────────────────
    dims = defaultdict(list)
    for r in results:
        dims[r["dimension"]].append(r)

    metrics: dict[str, dict] = {}
    total_match = 0
    total_partial = 0
    total_miss = 0
    total_nvs_pass = 0
    total_nvs_count = 0
    total_cr_pass = 0
    total_cr_count = 0
    total_filtered_out = 0

    for dim, dim_results in sorted(dims.items()):
        match = sum(1 for r in dim_results if r["recommendation"]["comparison"] == "match")
        partial = sum(1 for r in dim_results if r["recommendation"]["comparison"] == "partial")
        miss = sum(1 for r in dim_results if r["recommendation"]["comparison"] == "miss")
        filtered_out = sum(1 for r in dim_results if r["filtered_out"])
        n = len(dim_results)

        total_match += match
        total_partial += partial
        total_miss += miss
        total_filtered_out += filtered_out

        tp = match
        fp_fn = miss
        precision = tp / (tp + fp_fn) if (tp + fp_fn) > 0 else 0.0
        recall = tp / (tp + fp_fn) if (tp + fp_fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        nvs_pass = sum(1 for r in dim_results if r["news_value_score"]["comparison"] == "pass")
        nvs_total = sum(1 for r in dim_results if r["news_value_score"]["comparison"] != "skip")
        cr_pass = sum(1 for r in dim_results if r["china_relevance"]["comparison"] == "pass")
        cr_total = sum(1 for r in dim_results if r["china_relevance"]["comparison"] != "skip")

        total_nvs_pass += nvs_pass
        total_nvs_count += nvs_total
        total_cr_pass += cr_pass
        total_cr_count += cr_total

        metrics[dim] = {
            "n": n,
            "match": match,
            "partial": partial,
            "miss": miss,
            "filtered_out": filtered_out,
            "accuracy": match / n if n > 0 else 0.0,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "nvs_compliance": nvs_pass / nvs_total if nvs_total > 0 else None,
            "cr_compliance": cr_pass / cr_total if cr_total > 0 else None,
        }

    n_total = len(results)
    overall = {
        "n": n_total,
        "match": total_match,
        "partial": total_partial,
        "miss": total_miss,
        "filtered_out": total_filtered_out,
        "accuracy": total_match / n_total if n_total > 0 else 0.0,
        "precision": total_match / (total_match + total_miss) if (total_match + total_miss) > 0 else 0.0,
        "recall": total_match / (total_match + total_miss) if (total_match + total_miss) > 0 else 0.0,
        "f1": 2 * total_match / (2 * total_match + total_miss) if (2 * total_match + total_miss) > 0 else 0.0,
        "nvs_compliance": total_nvs_pass / total_nvs_count if total_nvs_count > 0 else None,
        "cr_compliance": total_cr_pass / total_cr_count if total_cr_count > 0 else None,
    }

    report = {
        "eval_set": str(eval_path),
        "target": target_id,
        "total_examples": n_total,
        "dimensions": len(metrics),
        "overall": overall,
        "by_dimension": metrics,
        "details": results,
    }

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

    return report


def print_report(report: dict) -> None:
    """格式化打印评估报告。"""
    print(f"\n{'='*70}")
    print(f"  Phase 13 — Judge Accuracy Evaluation Report")
    print(f"  Eval set: {report['eval_set']}")
    print(f"  Target:   {report['target']}")
    print(f"  Examples: {report['total_examples']}")
    print(f"{'='*70}")

    o = report["overall"]
    print(f"\n  Overall:")
    print(f"    Recommendation Accuracy: {o['accuracy']:.1%} ({o['match']}/{o['n']})")
    print(f"    Partial Match: {o['partial']}  Miss: {o['miss']}")
    print(f"    Filtered Out: {o['filtered_out']}")
    print(f"    Precision: {o['precision']:.1%}  Recall: {o['recall']:.1%}  F1: {o['f1']:.1%}")
    if o["nvs_compliance"] is not None:
        print(f"    News Value Score Compliance: {o['nvs_compliance']:.1%}")
    if o["cr_compliance"] is not None:
        print(f"    China Relevance Compliance: {o['cr_compliance']:.1%}")

    print(f"\n  By Dimension:")
    print(f"  {'Dimension':<18} {'N':>3} {'OK':>3} {'~':>3} {'X':>3} {'Flt':>3} {'Acc':>6} {'F1':>6}")
    print(f"  {'-'*18} {'-'*3} {'-'*3} {'-'*3} {'-'*3} {'-'*3} {'-'*6} {'-'*6}")
    for dim, m in report["by_dimension"].items():
        print(
            f"  {dim:<18} {m['n']:>3} {m['match']:>3} {m['partial']:>3} "
            f"{m['miss']:>3} {m['filtered_out']:>3} {m['accuracy']:>5.0%} {m['f1']:>5.1%}"
        )

    print(f"\n{'='*70}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 13 eval runner")
    parser.add_argument(
        "--eval-set",
        type=Path,
        default=PROJECT_ROOT / "data" / "eval" / "eval-set-v1.json",
        help="Path to eval-set JSON",
    )
    parser.add_argument(
        "--target",
        type=str,
        default="italy",
        help="Target ID for config loading",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path to write JSON report",
    )
    args = parser.parse_args()

    report = run_evaluation(args.eval_set, args.target, args.output)
    print_report(report)


if __name__ == "__main__":
    main()
