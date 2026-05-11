"""RulesJudgeSkill 模块测试 — 规则引擎研判分支覆盖。"""
from __future__ import annotations

import pytest

from news_sentry.core.memory import Memory
from news_sentry.models.newsevent import (
    JudgeRecommendation,
    Language,
    NewsEvent,
    PipelineStage,
)
from news_sentry.skills.judge.rules_judge import RulesJudgeSkill


def _make_event(
    title: str = "Test news",
    content: str = "Test content",
    score: int | None = None,
    classification: dict | None = None,
) -> NewsEvent:
    event = NewsEvent(
        id="ne-test-judge-001",
        run_id="run-001",
        source_id="test",
        url="https://example.com/1",
        title_original=title,
        content_original=content,
        language=Language.EN,
        published_at="2026-05-10T10:00:00+00:00",
        collected_at="2026-05-10T10:01:00+00:00",
        pipeline_stage=PipelineStage.FILTERED,
    )
    if score is not None:
        event.news_value_score = score
    if classification is not None:
        event.metadata["classification"] = classification
    return event


@pytest.fixture
def skill(tmp_path) -> RulesJudgeSkill:
    memory = Memory(tmp_path / "memory")
    return RulesJudgeSkill({}, memory)


# ── _decide_recommendation 分支 ──────────────────────────────


class TestDecideRecommendation:
    """推荐决策逻辑的 7 条优先级规则测试。"""

    def test_score_ge_80_publish(self, skill):
        """news_value_score >= 80 → PUBLISH。"""
        event = _make_event(score=85, classification={"l0": "other"})
        rec = skill._decide_recommendation(event, event.metadata.get("classification", {}))
        assert rec == JudgeRecommendation.PUBLISH

    def test_l0_breaking_news_publish(self, skill):
        """l0 == breaking_news → PUBLISH（即使 score 低）。"""
        event = _make_event(score=20, classification={"l0": "breaking_news"})
        rec = skill._decide_recommendation(event, event.metadata["classification"])
        assert rec == JudgeRecommendation.PUBLISH

    def test_l0_china_related_publish(self, skill):
        """l0 == china_related → PUBLISH。"""
        event = _make_event(score=40, classification={"l0": "china_related"})
        rec = skill._decide_recommendation(event, event.metadata["classification"])
        assert rec == JudgeRecommendation.PUBLISH

    def test_score_ge_60_review(self, skill):
        """news_value_score >= 60 → REVIEW。"""
        event = _make_event(score=65, classification={"l0": "other"})
        rec = skill._decide_recommendation(event, event.metadata.get("classification", {}))
        assert rec == JudgeRecommendation.REVIEW

    def test_l0_political_review(self, skill):
        """l0 == political → REVIEW。"""
        event = _make_event(score=40, classification={"l0": "political"})
        rec = skill._decide_recommendation(event, event.metadata["classification"])
        assert rec == JudgeRecommendation.REVIEW

    def test_l0_economy_review(self, skill):
        """l0 == economy → REVIEW。"""
        event = _make_event(score=40, classification={"l0": "economy"})
        rec = skill._decide_recommendation(event, event.metadata["classification"])
        assert rec == JudgeRecommendation.REVIEW

    def test_score_lt_30_discard(self, skill):
        """news_value_score < 30 → DISCARD。"""
        event = _make_event(score=15, classification={"l0": "other"})
        rec = skill._decide_recommendation(event, event.metadata.get("classification", {}))
        assert rec == JudgeRecommendation.DISCARD

    def test_fallback_archive(self, skill):
        """score 在 30-60 之间且 l0 非重点 → ARCHIVE。"""
        event = _make_event(score=45, classification={"l0": "society"})
        rec = skill._decide_recommendation(event, event.metadata.get("classification", {}))
        assert rec == JudgeRecommendation.ARCHIVE


# ── _calc_china_relevance ────────────────────────────────────


class TestCalcChinaRelevance:
    """China 关键词匹配计算测试。"""

    def test_no_china_keyword(self, skill):
        event = _make_event(title="Local weather report", content="Sunny day")
        assert skill._calc_china_relevance(event) == 0

    def test_single_china_keyword(self, skill):
        event = _make_event(title="China trade policy", content="Update")
        assert skill._calc_china_relevance(event) == 10

    def test_multiple_china_keywords(self, skill):
        event = _make_event(
            title="China and Beijing summit",
            content="Xi Jinping addresses BRICS leaders in Shanghai",
        )
        rel = skill._calc_china_relevance(event)
        assert rel >= 40

    def test_max_100(self, skill):
        event = _make_event(
            title="cina china cinese chinese via della seta belt and road "
                  "pechino beijing shanghai xi jinping brics",
            content="",
        )
        assert skill._calc_china_relevance(event) == 100


# ── _build_rationale ─────────────────────────────────────────


class TestBuildRationale:
    """研判理由生成测试。"""

    def test_includes_score(self, skill):
        event = _make_event(score=75)
        classification = {"l0": "other"}
        rationale = skill._build_rationale(event, classification, 0, JudgeRecommendation.REVIEW)
        assert "75" in rationale

    def test_includes_china_rel_when_ge_30(self, skill):
        event = _make_event(score=50)
        classification = {"l0": "china_related"}
        rationale = skill._build_rationale(event, classification, 40, JudgeRecommendation.PUBLISH)
        assert "中国关联度" in rationale

    def test_excludes_china_rel_when_lt_30(self, skill):
        event = _make_event(score=50)
        classification = {"l0": "other"}
        rationale = skill._build_rationale(event, classification, 10, JudgeRecommendation.ARCHIVE)
        assert "中国关联度" not in rationale

    def test_includes_l1_codes(self, skill):
        event = _make_event(score=50)
        classification = {"l0": "political", "l1": [{"code": "elections"}, {"code": "government"}]}
        rationale = skill._build_rationale(event, classification, 0, JudgeRecommendation.REVIEW)
        assert "elections" in rationale


# ── _build_flags ─────────────────────────────────────────────


class TestBuildFlags:
    """研判标记生成测试。"""

    def test_high_value_flag(self):
        event = _make_event(score=85)
        flags = RulesJudgeSkill._build_flags(event, {"l0": "other"}, 0)
        assert "high_value" in flags

    def test_no_high_value_flag(self):
        event = _make_event(score=50)
        flags = RulesJudgeSkill._build_flags(event, {"l0": "other"}, 0)
        assert "high_value" not in flags

    def test_china_significant_flag(self):
        event = _make_event(score=50)
        flags = RulesJudgeSkill._build_flags(event, {"l0": "other"}, 60)
        assert "china_significant" in flags

    def test_china_related_flag(self):
        event = _make_event(score=50)
        flags = RulesJudgeSkill._build_flags(event, {"l0": "other"}, 35)
        assert "china_related" in flags
        assert "china_significant" not in flags

    def test_breaking_flag(self):
        event = _make_event(score=50)
        flags = RulesJudgeSkill._build_flags(event, {"l0": "breaking_news"}, 0)
        assert "breaking" in flags

    def test_priority_topic_political(self):
        event = _make_event(score=50)
        flags = RulesJudgeSkill._build_flags(event, {"l0": "political"}, 0)
        assert "priority_topic" in flags

    def test_priority_topic_economy(self):
        event = _make_event(score=50)
        flags = RulesJudgeSkill._build_flags(event, {"l0": "economy"}, 0)
        assert "priority_topic" in flags


# ── judge (集成) ──────────────────────────────────────────────


class TestJudge:
    """judge 方法集成测试 — 验证所有字段被填充。"""

    def test_judge_populates_all_fields(self, skill):
        event = _make_event(
            title="China economic summit",
            content="Beijing hosts major economic summit",
            score=70,
            classification={"l0": "economy", "confidence": 60},
        )
        results = skill.judge([event], "run-001")

        assert len(results) == 1
        result = results[0]
        assert result.pipeline_stage == PipelineStage.JUDGED
        assert result.china_relevance is not None
        assert result.china_relevance >= 0
        assert result.judge_result is not None
        assert result.judge_result.recommendation in list(JudgeRecommendation)
        assert len(result.judge_result.rationale) > 0
        assert 0 <= result.judge_result.confidence <= 100
        assert isinstance(result.judge_result.flags, list)

    def test_judge_empty_list(self, skill):
        results = skill.judge([], "run-001")
        assert results == []

    def test_judge_multiple_events(self, skill):
        events = [
            _make_event(title="Breaking: earthquake", content="", score=90,
                        classification={"l0": "breaking_news", "confidence": 80}),
            _make_event(title="Sports results", content="", score=20,
                        classification={"l0": "other", "confidence": 30}),
        ]
        results = skill.judge(events, "run-001")
        assert len(results) == 2
        assert results[0].judge_result.recommendation == JudgeRecommendation.PUBLISH
        assert results[1].judge_result.recommendation == JudgeRecommendation.DISCARD
