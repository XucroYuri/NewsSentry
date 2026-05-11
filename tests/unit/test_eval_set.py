"""Phase 13 — Eval Set Schema 校验 + Eval Runner 基础测试。"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from jsonschema import validate

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_DIR = PROJECT_ROOT / "schemas"
EVAL_DIR = PROJECT_ROOT / "data" / "eval"


def _import_from_tools(name: str):
    """从 tools/ 目录导入模块。"""
    sys.path.insert(0, str(PROJECT_ROOT / "tools"))
    mod = __import__("run_eval")
    return getattr(mod, name)


class TestEvalExampleSchema:
    """evalexample.schema.json 校验。"""

    def test_schema_is_valid_json(self) -> None:
        with open(SCHEMA_DIR / "evalexample.schema.json") as f:
            schema = json.load(f)
        assert schema["title"] == "EvalExample"
        assert "dimension" in schema["properties"]

    def test_eval_set_all_examples_pass(self) -> None:
        with open(SCHEMA_DIR / "evalexample.schema.json") as f:
            schema = json.load(f)
        with open(EVAL_DIR / "eval-set-v1.json") as f:
            data = json.load(f)

        assert data["total"] == len(data["examples"]) == 112

        for example in data["examples"]:
            validate(example, schema)

    def test_eval_set_dimension_coverage(self) -> None:
        with open(EVAL_DIR / "eval-set-v1.json") as f:
            data = json.load(f)

        dims = {ex["dimension"] for ex in data["examples"]}
        expected_dims = {
            "politics", "economics", "diplomacy", "security", "judicial",
            "society", "technology", "environment", "immigration", "culture",
            "religion", "china_relations", "other", "edge_case",
        }
        assert dims == expected_dims

    def test_eval_set_recommendation_distribution(self) -> None:
        with open(EVAL_DIR / "eval-set-v1.json") as f:
            data = json.load(f)

        recs = {ex["expected"]["recommendation"] for ex in data["examples"]}
        assert "publish" in recs
        assert "review" in recs
        assert "archive" in recs

    def test_eval_set_ids_match_pattern(self) -> None:
        with open(EVAL_DIR / "eval-set-v1.json") as f:
            data = json.load(f)

        pattern = re.compile(r"^eval-[a-z0-9-]+$")
        for ex in data["examples"]:
            assert pattern.match(ex["eval_id"]), f"Invalid eval_id: {ex['eval_id']}"


class TestEvalRunner:
    """Eval runner 基础功能测试。"""

    def test_eval_to_event_conversion(self) -> None:
        eval_to_event = _import_from_tools("eval_to_event")

        example = {
            "eval_id": "eval-test-001",
            "dimension": "politics",
            "input": {
                "title_original": "Test title",
                "content_original": "Test content",
                "source_id": "test-source",
                "language": "it",
            },
            "expected": {
                "recommendation": "publish",
                "l0_domain": "political",
            },
        }
        event = eval_to_event(example)
        assert event.id == "eval-test-001"
        assert event.title_original == "Test title"
        assert event.language == "it"

    def test_compare_recommendation_match(self) -> None:
        from news_sentry.models.newsevent import JudgeRecommendation

        compare_recommendation = _import_from_tools("compare_recommendation")
        assert compare_recommendation(JudgeRecommendation.PUBLISH, "publish") == "match"
        assert compare_recommendation(JudgeRecommendation.REVIEW, "review") == "match"

    def test_compare_recommendation_partial(self) -> None:
        from news_sentry.models.newsevent import JudgeRecommendation

        compare_recommendation = _import_from_tools("compare_recommendation")
        assert compare_recommendation(JudgeRecommendation.REVIEW, "publish") == "partial"
        assert compare_recommendation(JudgeRecommendation.PUBLISH, "review") == "partial"

    def test_compare_recommendation_miss(self) -> None:
        from news_sentry.models.newsevent import JudgeRecommendation

        compare_recommendation = _import_from_tools("compare_recommendation")
        assert compare_recommendation(JudgeRecommendation.DISCARD, "publish") == "miss"

    def test_compare_score(self) -> None:
        compare_score = _import_from_tools("compare_score")
        assert compare_score(80, 60) == "pass"
        assert compare_score(40, 60) == "miss"
        assert compare_score(None, 60) == "miss"
        assert compare_score(50, None) == "skip"

    def test_baseline_report_exists(self) -> None:
        report_path = EVAL_DIR / "report-v1-rules-baseline.json"
        assert report_path.is_file()
        with open(report_path) as f:
            report = json.load(f)
        assert report["overall"]["accuracy"] > 0
        assert "by_dimension" in report
