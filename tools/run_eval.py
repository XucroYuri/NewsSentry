#!/usr/bin/env python3
"""Phase 14 — Three-mode evaluation runner (Rules / AI / Hybrid).

Loads eval-set JSON, runs the full filter→classify→judge pipeline on each
example using real config, compares actual vs expected, and outputs
Precision/Recall/F1 per dimension.

Modes:
  rules  — Rules-only judge (Phase 13 baseline, no AI calls)
  ai     — AI-only judge (JudgeSkill via ProviderRouter)
  hybrid — ConfidenceRouter: rules first, low-confidence escalates to AI

Usage:
    python tools/run_eval.py [--eval-set PATH] [--output PATH] [--target TARGET] [--mode MODE]
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
sys.path.insert(0, str(PROJECT_ROOT / "src"))  # noqa: E402

from news_sentry.core.confidence_router import ConfidenceRouter  # noqa: E402
from news_sentry.core.config import ConfigLoader  # noqa: E402
from news_sentry.core.memory import Memory  # noqa: E402
from news_sentry.core.provider_router import ProviderRouter  # noqa: E402
from news_sentry.models.newsevent import (  # noqa: E402
    JudgeRecommendation,
    NewsEvent,
    PipelineStage,
)
from news_sentry.skills.filter.classifier_rules import ClassifierRules  # noqa: E402
from news_sentry.skills.filter.rules_filter import RulesFilter  # noqa: E402
from news_sentry.skills.judge.judge_skill import JudgeSkill  # noqa: E402
from news_sentry.skills.judge.rules_judge import RulesJudgeSkill  # noqa: E402


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


def _init_ai_judge(
    config: object,
    memory: Memory,
) -> JudgeSkill | None:
    """尝试初始化 AI JudgeSkill，环境不可用时返回 None。"""
    try:
        routes_config = getattr(config, "provider_routes", None)
        if routes_config is None:
            return None

        cost_budget = 1.0  # 单次 eval run 最多 $1
        router = ProviderRouter(routes_config, cost_budget=cost_budget)

        def _factory(name: str) -> None:
            # 简化工厂：eval 中只做路由，不实际创建 provider
            return None

        return JudgeSkill(router, _factory)
    except Exception:
        return None


def run_pipeline(
    event: NewsEvent,
    rules_filter: RulesFilter,
    classifier: ClassifierRules,
    rules_judge: RulesJudgeSkill,
    ai_judge: JudgeSkill | None = None,
    mode: str = "rules",
) -> NewsEvent | None:
    """对单个事件执行 filter → classify → judge 流水线。

    Args:
        mode: "rules" (规则), "ai" (AI), "hybrid" (置信度路由)

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

    # Step 3: judge — 根据模式选择研判方式
    if mode == "ai" and ai_judge is not None:
        event = ai_judge.judge(event, run_id="eval-run")
    elif mode == "hybrid":
        router = ConfidenceRouter(rules_judge, ai_judge=ai_judge)
        judged = router.judge([event], run_id="eval-run")
        event = judged[0]
    else:
        # mode == "rules" 或 AI 不可用时回退
        judged = rules_judge.judge([event], run_id="eval-run")
        event = judged[0]

    return event


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
    mode: str = "rules",
) -> dict:
    """运行完整评估，返回结果 dict。

    Args:
        mode: "rules" / "ai" / "hybrid"
    """
    examples = load_eval_set(eval_path)

    # 加载目标配置
    loader = ConfigLoader(PROJECT_ROOT)
    config = loader.load_target(target_id, profile_id="local-workstation")

    with tempfile.TemporaryDirectory() as tmpdir:
        memory = Memory(Path(tmpdir) / "memory")

        rules_filter = RulesFilter(config.filter_rules, memory)
        classifier = ClassifierRules(config.classification_rules)
        rules_judge = RulesJudgeSkill(config.classification_rules, memory)

        # AI judge（仅 ai/hybrid 模式需要）
        ai_judge = None
        if mode in ("ai", "hybrid"):
            ai_judge = _init_ai_judge(config, memory)
            if ai_judge is None and mode == "ai":
                print("警告: AI judge 不可用，回退到 rules 模式", file=sys.stderr)
            elif ai_judge is None and mode == "hybrid":
                print("警告: AI judge 不可用，hybrid 将退化为 rules 模式", file=sys.stderr)

        results: list[dict] = []
        for example in examples:
            event = eval_to_event(example)
            expected = example["expected"]

            judged = run_pipeline(
                event, rules_filter, classifier, rules_judge,
                ai_judge=ai_judge, mode=mode,
            )

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
        "precision": (
            total_match / (total_match + total_miss)
            if (total_match + total_miss) > 0 else 0.0
        ),
        "recall": (
            total_match / (total_match + total_miss)
            if (total_match + total_miss) > 0 else 0.0
        ),
        "f1": (
            2 * total_match / (2 * total_match + total_miss)
            if (2 * total_match + total_miss) > 0 else 0.0
        ),
        "nvs_compliance": (
            total_nvs_pass / total_nvs_count
            if total_nvs_count > 0 else None
        ),
        "cr_compliance": (
            total_cr_pass / total_cr_count
            if total_cr_count > 0 else None
        ),
    }

    report = {
        "eval_set": str(eval_path),
        "target": target_id,
        "mode": mode,
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
    mode_label = {"rules": "Rules-only", "ai": "AI-only", "hybrid": "Hybrid"}
    print(f"\n{'='*70}")
    print("  Phase 14 — Judge Accuracy Evaluation Report")
    print(f"  Eval set: {report['eval_set']}")
    print(f"  Target:   {report['target']}")
    print(f"  Mode:     {mode_label.get(report['mode'], report['mode'])}")
    print(f"  Examples: {report['total_examples']}")
    print(f"{'='*70}")

    o = report["overall"]
    print("\n  Overall:")
    print(f"    Recommendation Accuracy: {o['accuracy']:.1%} ({o['match']}/{o['n']})")
    print(f"    Partial Match: {o['partial']}  Miss: {o['miss']}")
    print(f"    Filtered Out: {o['filtered_out']}")
    print(
        f"    Precision: {o['precision']:.1%}"
        f"  Recall: {o['recall']:.1%}"
        f"  F1: {o['f1']:.1%}"
    )
    if o["nvs_compliance"] is not None:
        print(f"    News Value Score Compliance: {o['nvs_compliance']:.1%}")
    if o["cr_compliance"] is not None:
        print(f"    China Relevance Compliance: {o['cr_compliance']:.1%}")

    print("\n  By Dimension:")
    hdr = (
        f"  {'Dimension':<18} {'N':>3}"
        f" {'OK':>3} {'~':>3} {'X':>3}"
        f" {'Flt':>3} {'Acc':>6} {'F1':>6}"
    )
    print(hdr)
    sep = (
        f"  {'-'*18} {'-'*3}"
        f" {'-'*3} {'-'*3} {'-'*3}"
        f" {'-'*3} {'-'*6} {'-'*6}"
    )
    print(sep)
    for dim, m in report["by_dimension"].items():
        print(
            f"  {dim:<18} {m['n']:>3} {m['match']:>3} {m['partial']:>3} "
            f"{m['miss']:>3} {m['filtered_out']:>3} {m['accuracy']:>5.0%} {m['f1']:>5.1%}"
        )

    print(f"\n{'='*70}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 14 eval runner (three-mode)")
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
    parser.add_argument(
        "--mode",
        type=str,
        default="rules",
        choices=["rules", "ai", "hybrid"],
        help="Judge mode: rules (baseline), ai (AI-only), hybrid (confidence router)",
    )
    args = parser.parse_args()

    report = run_evaluation(args.eval_set, args.target, args.output, mode=args.mode)
    print_report(report)


if __name__ == "__main__":
    main()
