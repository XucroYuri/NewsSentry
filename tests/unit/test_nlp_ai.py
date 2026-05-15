"""P30.04: NLPAIAnalyzer 测试 — prompt 构建、响应解析、异步分析。"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from news_sentry.core.nlp_ai import NLPAIAnalyzer
from news_sentry.models.newsevent import (
    JudgeRecommendation,
    JudgeResult,
    NewsEvent,
    NLPAnalysis,
    NLPEntity,
    Sentiment,
)


def _make_event(nlp: NLPAnalysis | None = None) -> NewsEvent:
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
        title_original="La crisi economica colpisce Roma",
        content_original=(
            "La crisi economica sta causando gravi problemi a Roma e nel Paese intero."
        ),
        language="it",
        published_at="2026-05-15T00:00:00Z",
        collected_at="2026-05-15T00:00:00Z",
        judge_result=jr,
    )


def _mock_provider_router(response_content: str) -> MagicMock:
    """创建返回指定内容的 mock ProviderRouter。"""
    router = MagicMock()
    router.route_async = AsyncMock(
        return_value={
            "content": response_content,
            "model": "gpt-4o-mini",
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            "route_id": "nlp.ai-fast",
            "provider": "openai",
            "fallback_used": False,
            "budget_exceeded": False,
        }
    )
    return router


class TestNLPAIAnalyzerPrompt:
    def test_build_prompt_contains_event_data(self):
        router = _mock_provider_router("{}")
        analyzer = NLPAIAnalyzer(router)
        event = _make_event()
        prompt = analyzer._build_prompt(event)
        assert "La crisi economica colpisce Roma" in prompt
        assert "it" in prompt

    def test_build_prompt_includes_rules_summary(self):
        router = _mock_provider_router("{}")
        analyzer = NLPAIAnalyzer(router)
        rules_nlp = NLPAnalysis(
            sentiment=Sentiment.NEGATIVE,
            sentiment_confidence=65,
            entities=[NLPEntity(name="Roma", entity_type="location", relevance=80)],
        )
        event = _make_event(nlp=rules_nlp)
        prompt = analyzer._build_prompt(event)
        assert "negative" in prompt
        assert "Roma" in prompt


class TestNLPAIAnalyzerParse:
    def test_parse_valid_response(self):
        router = _mock_provider_router("{}")
        analyzer = NLPAIAnalyzer(router)
        response = {
            "sentiment": "positive",
            "sentiment_confidence": 85,
            "entities": [{"name": "UE", "entity_type": "organization", "relevance": 90}],
            "topic_tags": ["economy", "eu"],
            "event_relations": ["same_topic: bilancio UE"],
            "rationale_enhanced": "Una notizia positiva per l'economia italiana.",
        }
        result = analyzer._parse_response(json.dumps(response))
        assert result["nlp_analysis"].sentiment == Sentiment.POSITIVE
        assert len(result["nlp_analysis"].entities) == 1
        assert result["rationale_enhanced"] == "Una notizia positiva per l'economia italiana."

    def test_parse_invalid_json_returns_none(self):
        router = _mock_provider_router("{}")
        analyzer = NLPAIAnalyzer(router)
        result = analyzer._parse_response("not json")
        assert result is None

    def test_parse_partial_response(self):
        router = _mock_provider_router("{}")
        analyzer = NLPAIAnalyzer(router)
        response = {"sentiment": "neutral"}
        result = analyzer._parse_response(json.dumps(response))
        assert result is not None
        assert result["nlp_analysis"].sentiment == Sentiment.NEUTRAL
        assert result["nlp_analysis"].entities == []


class TestNLPAIAnalyzerAnalyze:
    @pytest.mark.asyncio
    async def test_analyze_success(self):
        ai_response = json.dumps(
            {
                "sentiment": "negative",
                "sentiment_confidence": 80,
                "entities": [{"name": "Roma", "entity_type": "location", "relevance": 95}],
                "topic_tags": ["crisis"],
                "event_relations": [],
                "rationale_enhanced": "Notizia negativa sulla crisi economica.",
            }
        )
        router = _mock_provider_router(ai_response)
        analyzer = NLPAIAnalyzer(router)
        event = _make_event()

        result = await analyzer.analyze(event)

        assert result["nlp_analysis"].sentiment == Sentiment.NEGATIVE
        assert result["rationale_enhanced"] == "Notizia negativa sulla crisi economica."
        router.route_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_analyze_api_failure_raises(self):
        router = MagicMock()
        router.route_async = AsyncMock(side_effect=Exception("API error"))
        analyzer = NLPAIAnalyzer(router)
        event = _make_event()

        with pytest.raises(Exception, match="API error"):
            await analyzer.analyze(event)
