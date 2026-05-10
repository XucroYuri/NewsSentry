"""JudgeSkill 模块测试。

覆盖：初始化、judge 填充字段、stage 变更、JudgeResult 构建、
provider 错误处理、JSON 响应解析。
使用 RulesProvider（无需 API key）作为 mock AI provider 测试 plumbing。
"""
from __future__ import annotations

import json
from unittest import mock

import pytest

from news_sentry.adapters.providers.rules_provider import RulesProvider
from news_sentry.models.newsevent import (
    JudgeRecommendation,
    JudgeResult,
    Language,
    NewsEvent,
    PipelineStage,
)
from news_sentry.skills.judge.judge_skill import JudgeSkill

# ── 辅助 fixture ────────────────────────────────────────────────────────

@pytest.fixture
def rules_provider() -> RulesProvider:
    """RulesProvider 实例，无需 API key。"""
    return RulesProvider()


@pytest.fixture
def sample_event() -> NewsEvent:
    """构造一个待研判的 NewsEvent（FILTERED 阶段）。"""
    return NewsEvent(
        id="ne-test-ansa-20260510-a1b2c3d4",
        run_id="test-run-001",
        source_id="ansa",
        url="https://ansa.it/politica/20260510_1",
        title_original="Cina e Italia firmano accordo commerciale",
        content_original="La Cina e l'Italia hanno firmato un nuovo accordo "
                         "commerciale a Pechino, rafforzando i legami "
                         "della Via della Seta.",
        language=Language.IT,
        published_at="2026-05-10T10:30:00+00:00",
        collected_at="2026-05-10T10:31:00+00:00",
        pipeline_stage=PipelineStage.FILTERED,
    )


# ── 初始化 ──────────────────────────────────────────────────────────────

class TestInit:
    """JudgeSkill 初始化测试。"""

    def test_init_with_provider(self, rules_provider):
        """JudgeSkill(RulesProvider()) 成功初始化。"""
        skill = JudgeSkill(rules_provider)
        assert skill._provider is rules_provider
        assert skill._sandbox_enforcer is None

    def test_init_with_provider_and_sandbox(self, rules_provider):
        """可传入 sandbox_enforcer。"""
        sandbox = object()
        skill = JudgeSkill(rules_provider, sandbox_enforcer=sandbox)
        assert skill._sandbox_enforcer is sandbox


# ── judge ────────────────────────────────────────────────────────────────

class TestJudge:
    """judge 方法测试。"""

    def test_judge_populates_fields(self, sample_event):
        """调用 judge() 后 news_value_score/china_relevance/title_translated 被填充。"""
        mock_provider = mock.MagicMock()
        mock_provider.call.return_value = {
            "content": json.dumps({
                "news_value_score": 75,
                "china_relevance": 60,
                "recommendation": "publish",
                "rationale": "高价值涉华新闻。",
                "sentiment_score": 0.5,
                "title_translated": "中意贸易协议",
                "content_translated": "内容译文...",
                "classification_l0": "china_related",
                "flags": ["china_significant"],
            }),
            "model": "gpt-4o-mini",
            "usage": {},
            "route_id": "judge.primary",
            "provider": "openai",
        }

        skill = JudgeSkill(mock_provider)
        result = skill.judge(sample_event, "run-001")

        assert result.news_value_score is not None
        assert result.china_relevance is not None
        assert result.news_value_score == 75
        assert result.china_relevance == 60

    def test_judge_stage_changed(self, rules_provider, sample_event):
        """pipeline_stage 从 FILTERED 变为 JUDGED。"""
        skill = JudgeSkill(rules_provider)
        result = skill.judge(sample_event, "run-001")

        assert result.pipeline_stage == PipelineStage.JUDGED

    def test_judge_judge_result(self, sample_event):
        """event.judge_result 包含 recommendation/rationale/confidence/flags。"""
        mock_provider = mock.MagicMock()
        mock_provider.call.return_value = {
            "content": json.dumps({
                "news_value_score": 60,
                "china_relevance": 40,
                "recommendation": "review",
                "rationale": "普通政治新闻，建议审核。",
                "sentiment_score": 0.0,
                "title_translated": "标题",
                "content_translated": "正文",
                "classification_l0": "political",
                "flags": ["priority_topic", "high_value"],
                "confidence": 65,
            }),
            "model": "gpt-4o-mini",
            "usage": {},
            "route_id": "judge.primary",
            "provider": "openai",
        }

        skill = JudgeSkill(mock_provider)
        result = skill.judge(sample_event, "run-001")

        assert result.judge_result is not None
        assert isinstance(result.judge_result, JudgeResult)
        assert isinstance(result.judge_result.recommendation, JudgeRecommendation)
        assert result.judge_result.recommendation == JudgeRecommendation.REVIEW
        assert isinstance(result.judge_result.rationale, str)
        assert len(result.judge_result.rationale) > 0
        assert 0 <= result.judge_result.confidence <= 100
        assert result.judge_result.confidence == 65
        assert isinstance(result.judge_result.flags, list)
        assert "priority_topic" in result.judge_result.flags

    def test_judge_sets_sentiment_score(self, rules_provider, sample_event):
        """sentiment_score 字段被设置。"""
        skill = JudgeSkill(rules_provider)
        result = skill.judge(sample_event, "run-001")

        assert result.sentiment_score is not None
        assert -1.0 <= result.sentiment_score <= 1.0

    def test_judge_handles_provider_error(self, sample_event):
        """mock provider.call() 抛异常，judge 不崩溃，stage 仍变为 JUDGED。"""
        bad_provider = mock.MagicMock()
        bad_provider.call.side_effect = RuntimeError("API 不可用")

        skill = JudgeSkill(bad_provider)
        result = skill.judge(sample_event, "run-001")

        # 不崩溃，stage 仍推进为 JUDGED
        assert result.pipeline_stage == PipelineStage.JUDGED
        # 原有字段可能未变（取决于实现）
        bad_provider.call.assert_called_once()

    def test_judge_handles_provider_error_preserves_existing_fields(self, sample_event):
        """AI provider 失败时保留已有的规则研判字段。"""
        sample_event.news_value_score = 50
        sample_event.pipeline_stage = PipelineStage.JUDGED  # 已由规则研判设置

        bad_provider = mock.MagicMock()
        bad_provider.call.side_effect = RuntimeError("API 不可用")

        skill = JudgeSkill(bad_provider)
        result = skill.judge(sample_event, "run-001")

        # 已有的规则研判字段保持不变
        assert result.news_value_score == 50
        assert result.pipeline_stage == PipelineStage.JUDGED

    def test_judge_parses_json_response(self, sample_event):
        """mock provider 返回 content 为 JSON 字符串，验证解析。"""
        raw_json = json.dumps({
            "news_value_score": 85,
            "china_relevance": 70,
            "recommendation": "publish",
            "rationale": "涉及中国重大经贸协议，建议发布。",
            "sentiment_score": 0.6,
            "title_translated": "中国与意大利签署贸易协议",
            "content_translated": "中国和意大利在北京签署了新的贸易协议...",
            "classification_l0": "china_related",
            "flags": ["china_significant", "high_value"],
        })

        mock_provider = mock.MagicMock()
        mock_provider.call.return_value = {
            "content": raw_json,
            "model": "gpt-4o-mini",
            "usage": {"total_tokens": 200},
            "route_id": "judge.primary",
            "provider": "openai",
        }

        skill = JudgeSkill(mock_provider)
        result = skill.judge(sample_event, "run-001")

        assert result.news_value_score == 85
        assert result.china_relevance == 70
        assert result.sentiment_score == 0.6
        assert result.title_translated == "中国与意大利签署贸易协议"
        assert result.content_translated == "中国和意大利在北京签署了新的贸易协议..."
        assert result.judge_result is not None
        assert result.judge_result.recommendation == JudgeRecommendation.PUBLISH
        assert "中国重大经贸协议" in result.judge_result.rationale
        assert result.judge_result.confidence == 50  # 未传 confidence，默认 50
        assert "china_significant" in result.judge_result.flags

    def test_judge_parses_json_with_markdown_wrapper(self, sample_event):
        """mock provider 返回 markdown 包裹的 JSON（```json ... ```），验证解析。"""
        raw_text = (
            '```json\n'
            '{"news_value_score": 60, "china_relevance": 40, '
            '"recommendation": "review", "rationale": "普通政治新闻。", '
            '"sentiment_score": 0.0, "title_translated": "标题", '
            '"content_translated": "正文", "classification_l0": "political", '
            '"flags": ["priority_topic"]}\n'
            '```'
        )

        mock_provider = mock.MagicMock()
        mock_provider.call.return_value = {
            "content": raw_text,
            "model": "gpt-4o-mini",
            "usage": {},
            "route_id": "judge.primary",
            "provider": "openai",
        }

        skill = JudgeSkill(mock_provider)
        result = skill.judge(sample_event, "run-001")

        assert result.news_value_score == 60
        assert result.china_relevance == 40
        assert result.judge_result.recommendation == JudgeRecommendation.REVIEW
        assert result.title_translated == "标题"
        assert result.content_translated == "正文"


# ── _parse_response ─────────────────────────────────────────────────────

class TestParseResponse:
    """_parse_response 静态方法测试。"""

    def test_parse_from_dict_with_direct_fields(self):
        """response 字段本身是 dict 且含 news_value_score。"""
        raw = {
            "response": {"news_value_score": 90, "recommendation": "publish"},
            "model": "gpt-4o",
        }
        result = JudgeSkill._parse_response(raw, "evt-001")
        assert result["news_value_score"] == 90

    def test_parse_from_content_json_string(self):
        """content 字段为纯 JSON 字符串。"""
        raw = {"content": '{"news_value_score": 75, "recommendation": "review"}'}
        result = JudgeSkill._parse_response(raw, "evt-002")
        assert result["news_value_score"] == 75

    def test_parse_unparseable_returns_empty_dict(self):
        """无法解析的响应返回空 dict。"""
        raw = {"content": "not json at all"}
        result = JudgeSkill._parse_response(raw, "evt-003")
        assert result == {}


# ── _map_recommendation ─────────────────────────────────────────────────

class TestMapRecommendation:
    """_map_recommendation 方法测试。"""

    def test_known_values(self, rules_provider):
        """已知推荐值正确映射。"""
        skill = JudgeSkill(rules_provider)
        assert skill._map_recommendation("publish") == JudgeRecommendation.PUBLISH
        assert skill._map_recommendation("review") == JudgeRecommendation.REVIEW
        assert skill._map_recommendation("archive") == JudgeRecommendation.ARCHIVE
        assert skill._map_recommendation("discard") == JudgeRecommendation.DISCARD

    def test_case_insensitive(self, rules_provider):
        """大小写不敏感。"""
        skill = JudgeSkill(rules_provider)
        assert skill._map_recommendation("PUBLISH") == JudgeRecommendation.PUBLISH
        assert skill._map_recommendation("Review") == JudgeRecommendation.REVIEW

    def test_unknown_falls_back_to_archive(self, rules_provider):
        """未知值回退为 ARCHIVE。"""
        skill = JudgeSkill(rules_provider)
        assert skill._map_recommendation("garbage") == JudgeRecommendation.ARCHIVE


# ── _normalize_flags ────────────────────────────────────────────────────

class TestNormalizeFlags:
    """_normalize_flags 静态方法测试。"""

    def test_normalizes_string_list(self):
        result = JudgeSkill._normalize_flags(["breaking", "high_value"])
        assert result == ["breaking", "high_value"]

    def test_strips_whitespace(self):
        result = JudgeSkill._normalize_flags(["  breaking ", " high_value"])
        assert result == ["breaking", "high_value"]

    def test_filters_empty_and_none(self):
        result = JudgeSkill._normalize_flags(["", None, "valid"])
        assert result == ["valid"]

    def test_none_input_returns_empty(self):
        assert JudgeSkill._normalize_flags(None) == []

    def test_empty_list_returns_empty(self):
        assert JudgeSkill._normalize_flags([]) == []
