"""P30.05: NLPAnalyzer 编排器测试。"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from news_sentry.core.nlp_analyzer import NLPAnalyzer
from news_sentry.core.nlp_rules import NLPRulesAnalyzer
from news_sentry.models.newsevent import (
    JudgeRecommendation,
    JudgeResult,
    NewsEvent,
    NLPAnalysis,
    NLPEntity,
    Sentiment,
)


def _make_event(
    nlp: NLPAnalysis | None = None,
    score: int | None = 50,
) -> NewsEvent:
    jr = JudgeResult(
        recommendation=JudgeRecommendation.REVIEW,
        rationale="test",
        confidence=60,
        nlp_analysis=nlp,
    )
    return NewsEvent(
        id="ne-test-001",
        run_id="run-001",
        source_id="src1",
        url="https://example.com",
        title_original="Test title",
        content_original="Test content",
        language="it",
        published_at="2026-05-15T00:00:00Z",
        collected_at="2026-05-15T00:00:00Z",
        news_value_score=score,
        judge_result=jr,
    )


def _high_quality_nlp() -> NLPAnalysis:
    """规则分析返回的高质量结果（不满足升级条件）。"""
    return NLPAnalysis(
        sentiment=Sentiment.NEUTRAL,
        sentiment_confidence=80,
        entities=[NLPEntity(name="Test", entity_type="person", relevance=50)],
        topic_tags=["test"],
    )


@pytest.fixture
def rules_analyzer(tmp_path: Path) -> NLPRulesAnalyzer:
    nlp_dir = tmp_path / "nlp"
    s = nlp_dir / "sentiment"
    e = nlp_dir / "entities"
    s.mkdir(parents=True)
    e.mkdir(parents=True)
    (s / "it.yaml").write_text("language: it\npositive:\n  - 'successo'\nnegative:\n  - 'crisi'\n")
    (e / "it.yaml").write_text("language: it\npersons:\n  - name: 'Meloni'\n")
    return NLPRulesAnalyzer(nlp_dir)


class TestNLPAnalyzerRulesOnly:
    @pytest.mark.asyncio
    async def test_enrich_without_ai(self, rules_analyzer: NLPRulesAnalyzer):
        analyzer = NLPAnalyzer(rules_analyzer)
        event = _make_event()
        events = await analyzer.enrich([event], "run-001")
        assert len(events) == 1
        assert events[0].judge_result.nlp_analysis is not None
        assert events[0].sentiment_score is not None

    @pytest.mark.asyncio
    async def test_sentiment_score_mapping(self, rules_analyzer: NLPRulesAnalyzer):
        analyzer = NLPAnalyzer(rules_analyzer)
        event = _make_event()
        events = await analyzer.enrich([event], "run-001")
        # 规则分析后 sentiment_score 应该有值（-1.0, 0.0, 或 1.0）
        assert events[0].sentiment_score in (-1.0, 0.0, 1.0)


class TestNLPAnalyzerWithAI:
    @pytest.mark.asyncio
    async def test_upgrade_high_value_event(self, rules_analyzer: NLPRulesAnalyzer):
        """news_value_score >= 70 的事件应升级到 AI。"""
        ai = MagicMock()
        ai.analyze = AsyncMock(
            return_value={
                "nlp_analysis": NLPAnalysis(sentiment=Sentiment.NEGATIVE, sentiment_confidence=90),
                "rationale_enhanced": "AI enhanced rationale",
            }
        )
        analyzer = NLPAnalyzer(rules_analyzer, ai_analyzer=ai)
        event = _make_event(score=80)
        await analyzer.enrich([event], "run-001")
        assert event.judge_result.nlp_analysis.sentiment == Sentiment.NEGATIVE
        assert event.judge_result.rationale == "AI enhanced rationale"
        ai.analyze.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_upgrade_high_confidence(self, rules_analyzer: NLPRulesAnalyzer):
        """规则置信度高 + 有实体 + 低分 → 不升级。

        enrich() 会先用规则分析覆盖手动设置的 nlp_analysis，
        所以需要 mock rules_analyzer.analyze 返回不满足升级条件的结果。
        """
        ai = MagicMock()
        ai.analyze = AsyncMock()
        analyzer = NLPAnalyzer(rules_analyzer, ai_analyzer=ai)
        event = _make_event(score=40)

        # Mock rules_analyzer.analyze 返回高置信度 + 有实体的结果
        with patch.object(rules_analyzer, "analyze", return_value=_high_quality_nlp()):
            await analyzer.enrich([event], "run-001")

        ai.analyze.assert_not_called()

    @pytest.mark.asyncio
    async def test_upgrade_low_sentiment_confidence(self, rules_analyzer: NLPRulesAnalyzer):
        """sentiment_confidence < 50 → 升级。

        规则分析返回低置信度结果（无词典命中时 confidence=0）。
        """
        ai = MagicMock()
        ai.analyze = AsyncMock(
            return_value={
                "nlp_analysis": NLPAnalysis(sentiment=Sentiment.POSITIVE, sentiment_confidence=95),
                "rationale_enhanced": "Upgraded",
            }
        )
        analyzer = NLPAnalyzer(rules_analyzer, ai_analyzer=ai)
        event = _make_event(score=40)
        # 规则分析对 "Test title Test content" 返回 NEUTRAL/confidence=0
        # confidence=0 < 50 → 触发升级
        await analyzer.enrich([event], "run-001")
        ai.analyze.assert_called_once()

    @pytest.mark.asyncio
    async def test_ai_failure_keeps_rules(self, rules_analyzer: NLPRulesAnalyzer):
        """AI 失败时保留规则结果。"""
        ai = MagicMock()
        ai.analyze = AsyncMock(side_effect=Exception("API down"))
        analyzer = NLPAnalyzer(rules_analyzer, ai_analyzer=ai)
        event = _make_event(score=80)
        await analyzer.enrich([event], "run-001")
        assert event.judge_result.nlp_analysis is not None


class TestNLPAnalyzerStats:
    @pytest.mark.asyncio
    async def test_stats_tracking(self, rules_analyzer: NLPRulesAnalyzer):
        ai = MagicMock()
        ai.analyze = AsyncMock(
            return_value={
                "nlp_analysis": NLPAnalysis(sentiment=Sentiment.POSITIVE),
                "rationale_enhanced": "ok",
            }
        )
        analyzer = NLPAnalyzer(rules_analyzer, ai_analyzer=ai)

        # 事件 1: score=80 → 高价值，升级
        event1 = _make_event(score=80)
        event1.id = "ne-test-high"

        # 事件 2: score=30，需要 mock rules 返回高质量结果以避免升级
        event2 = _make_event(score=30)
        event2.id = "ne-test-low"

        def analyze_side_effect(e: NewsEvent) -> NLPAnalysis:
            if e.id == "ne-test-low":
                return _high_quality_nlp()
            # 默认返回低质量结果（触发升级）
            return NLPAnalysis(sentiment=Sentiment.NEUTRAL, sentiment_confidence=0, entities=[])

        with patch.object(rules_analyzer, "analyze", side_effect=analyze_side_effect):
            await analyzer.enrich([event1, event2], "run-001")

        stats = analyzer.stats
        assert stats["total"] == 2
        assert stats["ai_upgraded"] == 1
        assert stats["rules_only"] == 1
