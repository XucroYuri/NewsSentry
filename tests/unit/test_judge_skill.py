"""JudgeSkill 模块测试（Phase 5 多 Provider 路由适配）。

覆盖：初始化、judge 填充字段、stage 变更、JudgeResult 构建、
router 错误处理、JSON 响应解析、budget_exceeded 降级。
使用 mock ProviderRouter 模拟多 Provider 路由。
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


def _make_mock_router(route_return: dict | None = None) -> mock.MagicMock:
    """创建模拟 ProviderRouter，route() 返回指定结果。"""
    router = mock.MagicMock()
    router.route.return_value = route_return or {}
    return router


def _make_provider_factory(provider=None):
    """创建 provider_factory callable，返回指定 provider 或 RulesProvider。"""
    if provider is None:
        provider = RulesProvider()
    return lambda name: provider


@pytest.fixture
def rules_skill() -> JudgeSkill:
    """使用 RulesProvider + mock router 的 JudgeSkill。

    Router 的 route() 委托给 RulesProvider.call()。
    """
    rules = RulesProvider()
    router = mock.MagicMock()

    def route_side_effect(task_type, prompt, provider_factory, preferred_route_id=None, **kwargs):
        return rules.call(
            route_id=preferred_route_id or "judge.primary",
            prompt=prompt,
            task_type=task_type,
        )

    router.route.side_effect = route_side_effect
    return JudgeSkill(router, lambda name: rules)


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

    def test_init_with_router(self):
        """JudgeSkill(router, factory) 成功初始化。"""
        router = _make_mock_router()
        factory = _make_provider_factory()
        skill = JudgeSkill(router, factory)
        assert skill._router is router
        assert skill._provider_factory is factory
        assert skill._sandbox_enforcer is None

    def test_init_with_router_and_sandbox(self):
        """可传入 sandbox_enforcer。"""
        router = _make_mock_router()
        factory = _make_provider_factory()
        sandbox = object()
        skill = JudgeSkill(router, factory, sandbox_enforcer=sandbox)
        assert skill._sandbox_enforcer is sandbox


# ── judge ────────────────────────────────────────────────────────────────


class TestJudge:
    """judge 方法测试。"""

    def test_judge_populates_fields(self, sample_event):
        """调用 judge() 后 news_value_score/china_relevance/title_translated 被填充。"""
        router = mock.MagicMock()
        router.route.return_value = {
            "content": json.dumps(
                {
                    "news_value_score": 75,
                    "china_relevance": 60,
                    "recommendation": "publish",
                    "rationale": "高价值涉华新闻。",
                    "sentiment_score": 0.5,
                    "title_translated": "中意贸易协议",
                    "content_translated": "内容译文...",
                    "classification_l0": "china_related",
                    "flags": ["china_significant"],
                }
            ),
            "model": "gpt-4o-mini",
            "usage": {},
            "route_id": "judge.primary",
            "provider": "openai",
            "fallback_used": False,
            "budget_exceeded": False,
        }

        skill = JudgeSkill(router, lambda name: None)
        result = skill.judge(sample_event, "run-001")

        assert result.news_value_score is not None
        assert result.china_relevance is not None
        assert result.news_value_score == 75
        assert result.china_relevance == 60

    def test_judge_stage_changed(self, rules_skill, sample_event):
        """pipeline_stage 从 FILTERED 变为 JUDGED。"""
        result = rules_skill.judge(sample_event, "run-001")
        assert result.pipeline_stage == PipelineStage.JUDGED

    def test_judge_judge_result(self, sample_event):
        """event.judge_result 包含 recommendation/rationale/confidence/flags。"""
        router = mock.MagicMock()
        router.route.return_value = {
            "content": json.dumps(
                {
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
                }
            ),
            "model": "gpt-4o-mini",
            "usage": {},
            "route_id": "judge.primary",
            "provider": "openai",
            "fallback_used": False,
            "budget_exceeded": False,
        }

        skill = JudgeSkill(router, lambda name: None)
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

    def test_judge_sets_sentiment_score(self, rules_skill, sample_event):
        """sentiment_score 由 NLPAnalyzer 填充，rules_judge 不再设置。"""
        result = rules_skill.judge(sample_event, "run-001")
        # sentiment_score 不再由 rules_judge 硬编码 0.0，由 NLPAnalyzer 后续填充
        assert result.sentiment_score is None or -1.0 <= result.sentiment_score <= 1.0

    def test_judge_handles_router_error(self, sample_event):
        """mock router.route() 返回 error，judge 不崩溃，stage 仍变为 JUDGED。"""
        router = mock.MagicMock()
        router.route.return_value = {
            "content": "",
            "model": "",
            "usage": {},
            "route_id": "judge.primary",
            "provider": "",
            "fallback_used": True,
            "budget_exceeded": False,
            "error": "All providers failed",
        }

        skill = JudgeSkill(router, lambda name: None)
        result = skill.judge(sample_event, "run-001")

        # 不崩溃，stage 仍推进为 JUDGED
        assert result.pipeline_stage == PipelineStage.JUDGED
        router.route.assert_called_once()

    def test_judge_handles_router_exception(self, sample_event):
        """router.route() 抛异常，保留已有字段，stage 仍变为 JUDGED。"""
        router = mock.MagicMock()
        router.route.side_effect = RuntimeError("API 不可用")

        skill = JudgeSkill(router, lambda name: None)
        result = skill.judge(sample_event, "run-001")

        # 不崩溃，stage 仍推进为 JUDGED
        assert result.pipeline_stage == PipelineStage.JUDGED
        router.route.assert_called_once()

    def test_judge_handles_error_preserves_existing_fields(self, sample_event):
        """AI router 失败时保留已有的规则研判字段。"""
        sample_event.news_value_score = 50
        sample_event.pipeline_stage = PipelineStage.JUDGED  # 已由规则研判设置

        router = mock.MagicMock()
        router.route.side_effect = RuntimeError("API 不可用")

        skill = JudgeSkill(router, lambda name: None)
        result = skill.judge(sample_event, "run-001")

        # 已有的规则研判字段保持不变
        assert result.news_value_score == 50
        assert result.pipeline_stage == PipelineStage.JUDGED

    def test_judge_budget_exceeded_downgrades_to_monitor(self, sample_event):
        """预算超限时，recommendation 降级为 monitor。"""
        router = mock.MagicMock()
        router.route.return_value = {
            "content": "",
            "model": "",
            "usage": {},
            "route_id": "judge.primary",
            "provider": "",
            "fallback_used": False,
            "budget_exceeded": True,
        }

        skill = JudgeSkill(router, lambda name: None)
        result = skill.judge(sample_event, "run-001")

        assert result.judge_result is not None
        assert result.judge_result.recommendation == JudgeRecommendation.MONITOR
        assert result.pipeline_stage == PipelineStage.JUDGED

    def test_judge_parses_json_response(self, sample_event):
        """mock router 返回 content 为 JSON 字符串，验证解析。"""
        raw_json = json.dumps(
            {
                "news_value_score": 85,
                "china_relevance": 70,
                "recommendation": "publish",
                "rationale": "涉及中国重大经贸协议，建议发布。",
                "sentiment_score": 0.6,
                "title_translated": "中国与意大利签署贸易协议",
                "content_translated": "中国和意大利在北京签署了新的贸易协议...",
                "classification_l0": "china_related",
                "flags": ["china_significant", "high_value"],
            }
        )

        router = mock.MagicMock()
        router.route.return_value = {
            "content": raw_json,
            "model": "gpt-4o-mini",
            "usage": {"total_tokens": 200},
            "route_id": "judge.primary",
            "provider": "openai",
            "fallback_used": False,
            "budget_exceeded": False,
        }

        skill = JudgeSkill(router, lambda name: None)
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
        """mock router 返回 markdown 包裹的 JSON，验证解析。"""
        raw_text = (
            "```json\n"
            '{"news_value_score": 60, "china_relevance": 40, '
            '"recommendation": "review", "rationale": "普通政治新闻。", '
            '"sentiment_score": 0.0, "title_translated": "标题", '
            '"content_translated": "正文", "classification_l0": "political", '
            '"flags": ["priority_topic"]}\n'
            "```"
        )

        router = mock.MagicMock()
        router.route.return_value = {
            "content": raw_text,
            "model": "gpt-4o-mini",
            "usage": {},
            "route_id": "judge.primary",
            "provider": "openai",
            "fallback_used": False,
            "budget_exceeded": False,
        }

        skill = JudgeSkill(router, lambda name: None)
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

    @pytest.fixture
    def skill(self) -> JudgeSkill:
        """创建 JudgeSkill 实例用于测试 _map_recommendation（router 不会被调用）。"""
        router = _make_mock_router()
        return JudgeSkill(router, lambda name: None)

    def test_known_values(self, skill):
        """已知推荐值正确映射。"""
        assert skill._map_recommendation("publish") == JudgeRecommendation.PUBLISH
        assert skill._map_recommendation("review") == JudgeRecommendation.REVIEW
        assert skill._map_recommendation("archive") == JudgeRecommendation.ARCHIVE
        assert skill._map_recommendation("discard") == JudgeRecommendation.DISCARD
        assert skill._map_recommendation("monitor") == JudgeRecommendation.MONITOR

    def test_case_insensitive(self, skill):
        """大小写不敏感。"""
        assert skill._map_recommendation("PUBLISH") == JudgeRecommendation.PUBLISH
        assert skill._map_recommendation("Review") == JudgeRecommendation.REVIEW

    def test_unknown_falls_back_to_archive(self, skill):
        """未知值回退为 ARCHIVE。"""
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


# ── _extract_json_from_text ────────────────────────────────────────


class TestExtractJsonFromText:
    """_extract_json_from_text 静态方法测试。"""

    def test_valid_json_string(self):
        """直接可解析的 JSON 字符串。"""
        text = '{"news_value_score": 75}'
        result = JudgeSkill._extract_json_from_text(text, "evt-001")
        assert result["news_value_score"] == 75

    def test_json_with_surrounding_text(self):
        """JSON 嵌入在文本中，通过 {...} 提取。"""
        text = 'Here is the result: {"news_value_score": 60, "recommendation": "review"} end'
        result = JudgeSkill._extract_json_from_text(text, "evt-002")
        assert result["news_value_score"] == 60

    def test_invalid_brace_content_returns_empty(self):
        """{...} 内不是有效 JSON 时返回空 dict。"""
        text = "Result: {not valid json at all} end"
        result = JudgeSkill._extract_json_from_text(text, "evt-003")
        assert result == {}

    def test_no_braces_returns_empty(self):
        """没有 {} 的文本返回空 dict。"""
        text = "plain text without any json"
        result = JudgeSkill._extract_json_from_text(text, "evt-004")
        assert result == {}
