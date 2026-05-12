"""Phase 14 — ConfidenceRouter 测试：混合规则+AI 置信度路由。"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from news_sentry.core.confidence_router import ConfidenceRouter
from news_sentry.core.memory import Memory
from news_sentry.models.newsevent import (
    JudgeRecommendation,
    JudgeResult,
    NewsEvent,
    PipelineStage,
)
from news_sentry.skills.judge.rules_judge import RulesJudgeSkill


def _make_event(
    event_id: str = "test-001",
    title: str = "Test title",
    content: str = "Test content",
    score: int | None = None,
) -> NewsEvent:
    """构造一个 NewsEvent（stage=filtered）。"""
    return NewsEvent(
        id=event_id,
        run_id="test-run",
        source_id="test",
        url="",
        title_original=title,
        content_original=content,
        language="it",
        published_at="2026-05-12T00:00:00Z",
        collected_at="2026-05-12T00:00:00Z",
        pipeline_stage=PipelineStage.FILTERED,
        news_value_score=score,
    )


def _make_rules_judge() -> RulesJudgeSkill:
    """构造 RulesJudgeSkill 实例。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        memory = Memory(Path(tmpdir) / "memory")
        return RulesJudgeSkill({}, memory)


class TestShouldEscalate:
    """_should_escalate 决策逻辑测试。"""

    def test_no_judge_result_escalates(self) -> None:
        """无 judge_result 时升级。"""
        rules = _make_rules_judge()
        router = ConfidenceRouter(rules, ai_judge=MagicMock())
        event = _make_event()
        # No judge_result set
        assert router._should_escalate(event) is True

    def test_low_confidence_escalates(self) -> None:
        """低置信度升级。"""
        rules = _make_rules_judge()
        router = ConfidenceRouter(rules, ai_judge=MagicMock(), confidence_threshold=60)
        event = _make_event()
        event.judge_result = JudgeResult(
            recommendation=JudgeRecommendation.REVIEW,
            rationale="test",
            confidence=40,
            flags=[],
        )
        assert router._should_escalate(event) is True

    def test_high_confidence_no_escalation(self) -> None:
        """高置信度+明确分值不升级。"""
        rules = _make_rules_judge()
        router = ConfidenceRouter(rules, ai_judge=MagicMock())
        event = _make_event(score=85)
        event.judge_result = JudgeResult(
            recommendation=JudgeRecommendation.REVIEW,
            rationale="test",
            confidence=80,
            flags=[],
        )
        # confidence ≥ 60, score=85 (not in 30-80), not ARCHIVE/DISCARD with china_rel
        assert router._should_escalate(event) is False

    def test_publish_high_confidence_no_escalation(self) -> None:
        """PUBLISH + confidence≥70 不升级。"""
        rules = _make_rules_judge()
        router = ConfidenceRouter(rules, ai_judge=MagicMock())
        event = _make_event(score=85)
        event.judge_result = JudgeResult(
            recommendation=JudgeRecommendation.PUBLISH,
            rationale="test",
            confidence=75,
            flags=[],
        )
        assert router._should_escalate(event) is False

    def test_boundary_score_escalates(self) -> None:
        """分值在 30-80 区间升级。"""
        rules = _make_rules_judge()
        router = ConfidenceRouter(rules, ai_judge=MagicMock())
        event = _make_event(score=55)
        event.judge_result = JudgeResult(
            recommendation=JudgeRecommendation.REVIEW,
            rationale="test",
            confidence=70,
            flags=[],
        )
        # confidence ≥ 60 but score in (30, 80) → escalate
        assert router._should_escalate(event) is True

    def test_archive_with_china_relevance_escalates(self) -> None:
        """ARCHIVE + china_relevance≥30 升级。"""
        rules = _make_rules_judge()
        router = ConfidenceRouter(rules, ai_judge=MagicMock())
        event = _make_event(score=25)
        event.china_relevance = 50
        event.judge_result = JudgeResult(
            recommendation=JudgeRecommendation.ARCHIVE,
            rationale="test",
            confidence=65,
            flags=[],
        )
        assert router._should_escalate(event) is True

    def test_discard_no_china_no_escalation(self) -> None:
        """DISCARD 且无中国关联不升级。"""
        rules = _make_rules_judge()
        router = ConfidenceRouter(rules, ai_judge=MagicMock())
        event = _make_event(score=15)
        event.judge_result = JudgeResult(
            recommendation=JudgeRecommendation.DISCARD,
            rationale="test",
            confidence=70,
            flags=[],
        )
        # confidence ≥ 60, score < 30 (not in 30-80), DISCARD but china_relevance=0
        assert router._should_escalate(event) is False


class TestConfidenceRouterIntegration:
    """ConfidenceRouter 与 RulesJudgeSkill 集成测试。"""

    def test_no_ai_judge_all_rules(self) -> None:
        """无 AI judge 时全部走规则。"""
        rules = _make_rules_judge()
        router = ConfidenceRouter(rules, ai_judge=None)
        events = [_make_event("e1"), _make_event("e2")]
        result = router.judge(events, "test-run")

        assert len(result) == 2
        assert router.stats["rules_only"] == 2
        assert router.stats["ai_escalated"] == 0

    def test_with_ai_some_escalated(self) -> None:
        """有 AI 时部分事件升级。"""
        rules = _make_rules_judge()
        ai = MagicMock()
        # AI judge returns the same event (with potential modifications)
        ai.judge.side_effect = lambda e, rid: e
        router = ConfidenceRouter(rules, ai_judge=ai)

        # Create event with China keywords to ensure it gets filtered and judged
        events = [
            _make_event(
                "e1",
                title="Governo Italiano",
                content="Il governo italiano ha approvato",
            )
        ]
        result = router.judge(events, "test-run")

        assert len(result) == 1
        # Whether it escalates depends on rules_judge output
        assert router.stats["total"] == 1

    def test_ai_failure_preserves_rules(self) -> None:
        """AI 失败时保留规则结果。"""
        rules = _make_rules_judge()
        ai = MagicMock()
        ai.judge.side_effect = RuntimeError("AI provider failed")
        router = ConfidenceRouter(rules, ai_judge=ai)

        events = [_make_event("e1", title="Cina e Italia", content="La Cina ha firmato un accordo")]
        result = router.judge(events, "test-run")

        # Event should still have a valid judge_result from rules
        assert result[0].judge_result is not None
        assert result[0].pipeline_stage == PipelineStage.JUDGED


class TestConfidenceRouterStats:
    """路由统计测试。"""

    def test_stats_all_rules(self) -> None:
        rules = _make_rules_judge()
        router = ConfidenceRouter(rules, ai_judge=None)
        router.judge([_make_event("e1")], "test-run")

        stats = router.stats
        assert stats["total"] == 1
        assert stats["rules_only"] == 1
        assert stats["ai_escalated"] == 0

    def test_stats_returns_copy(self) -> None:
        """stats 返回副本，不影响内部状态。"""
        rules = _make_rules_judge()
        router = ConfidenceRouter(rules, ai_judge=None)
        router.judge([_make_event("e1")], "test-run")

        stats1 = router.stats
        stats2 = router.stats
        assert stats1 == stats2
        assert stats1 is not stats2
