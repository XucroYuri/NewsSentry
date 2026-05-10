"""Phase 5: Tests for ProviderRouter, CostTracker, ProviderRoute config, and RulesProvider."""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest
import yaml

from news_sentry.adapters.providers.base import AIProvider
from news_sentry.adapters.providers.rules_provider import RulesProvider
from news_sentry.core.provider_router import CostTracker, ProviderRouter
from news_sentry.models.provider_config import ProviderRoute, ProviderRoutesConfig

# ------------------------------------------------------------------
# Shared test fixtures — 模拟 routes.yaml 的 5 条路由
# ------------------------------------------------------------------

def _make_test_routes_config() -> ProviderRoutesConfig:
    """构造与 config/provider/routes.yaml 结构一致的测试配置。"""
    return ProviderRoutesConfig(
        routes_version="1.0.0",
        fallback_route_id="fallback.local",
        routes=[
            ProviderRoute(
                route_id="translate.fast",
                task_type="translate",
                provider="<placeholder>",
                model="<placeholder>",
                timeout_seconds=30,
                max_cost_usd_per_call=0.01,
                notes="collect 阶段快速预翻译",
            ),
            ProviderRoute(
                route_id="translate.high",
                task_type="translate",
                provider="<placeholder>",
                model="<placeholder>",
                timeout_seconds=60,
                max_cost_usd_per_call=0.05,
                audit=True,
                notes="judge 阶段高质量翻译",
            ),
            ProviderRoute(
                route_id="judge.primary",
                task_type="judge",
                provider="<placeholder>",
                model="<placeholder>",
                timeout_seconds=60,
                max_cost_usd_per_call=0.10,
                output_schema_ref="schemas/toolrunresult.schema.json",
                audit=True,
                fallback_route_ids=["fallback.local"],
            ),
            ProviderRoute(
                route_id="classify.primary",
                task_type="classify",
                provider="<placeholder>",
                model="<placeholder>",
                timeout_seconds=30,
                max_cost_usd_per_call=0.02,
                output_schema_ref="schemas/classification.schema.json",
                audit=True,
            ),
            ProviderRoute(
                route_id="fallback.local",
                task_type="judge",
                provider="local",
                model="<placeholder-local-llm>",
                timeout_seconds=120,
                max_cost_usd_per_call=0.0,
                notes="主路由失败时的本地回退",
            ),
        ],
    )


# ------------------------------------------------------------------
# ProviderRoute / ProviderRoutesConfig model tests
# ------------------------------------------------------------------

def test_routes_config_from_dict() -> None:
    """验证从字典（模拟 YAML 加载）构造 ProviderRoutesConfig。"""
    data = {
        "routes_version": "1.0.0",
        "fallback_route_id": "fallback.local",
        "routes": [
            {
                "route_id": "translate.fast",
                "task_type": "translate",
                "provider": "openai",
                "model": "gpt-4o-mini",
                "timeout_seconds": 30,
                "max_cost_usd_per_call": 0.01,
            },
            {
                "route_id": "fallback.local",
                "task_type": "judge",
                "provider": "local",
                "model": "llama3",
                "timeout_seconds": 120,
                "max_cost_usd_per_call": 0.0,
            },
        ],
    }
    config = ProviderRoutesConfig(**data)
    assert config.routes_version == "1.0.0"
    assert config.fallback_route_id == "fallback.local"
    assert len(config.routes) == 2
    assert config.routes[0].route_id == "translate.fast"


def test_routes_config_from_yaml_file(tmp_path: Path) -> None:
    """验证从 YAML 文件（模拟 routes.yaml）加载 ProviderRoutesConfig。"""
    yaml_content = {
        "routes_version": "1.0.0",
        "fallback_route_id": "fallback.local",
        "routes": [
            {
                "route_id": "translate.fast",
                "task_type": "translate",
                "provider": "<placeholder>",
                "model": "<placeholder>",
                "timeout_seconds": 30,
                "max_cost_usd_per_call": 0.01,
            },
            {
                "route_id": "judge.primary",
                "task_type": "judge",
                "provider": "<placeholder>",
                "model": "<placeholder>",
                "timeout_seconds": 60,
                "max_cost_usd_per_call": 0.10,
                "audit": True,
            },
        ],
    }
    yaml_path = tmp_path / "routes.yaml"
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(yaml_content, f)

    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    config = ProviderRoutesConfig(**data)
    assert config.routes_version == "1.0.0"
    assert len(config.routes) == 2
    assert config.routes[0].route_id == "translate.fast"
    assert config.routes[1].audit is True


def test_provider_route_defaults() -> None:
    """验证 ProviderRoute 的默认字段值。"""
    route = ProviderRoute(
        route_id="test.route",
        task_type="test",
        provider="test",
        model="test",
        timeout_seconds=10,
        max_cost_usd_per_call=0.0,
    )
    assert route.audit is False
    assert route.output_schema_ref is None
    assert route.notes is None
    assert route.fallback_route_ids == []


# ------------------------------------------------------------------
# resolve_route
# ------------------------------------------------------------------


def test_resolve_route_by_task_type() -> None:
    """按 task_type 匹配返回第一条路由。"""
    config = _make_test_routes_config()
    router = ProviderRouter(config)

    route = router.resolve_route("translate")
    assert route.route_id == "translate.fast"
    assert route.task_type == "translate"

    route = router.resolve_route("judge")
    assert route.route_id == "judge.primary"

    route = router.resolve_route("classify")
    assert route.route_id == "classify.primary"


def test_resolve_route_by_explicit_route_id() -> None:
    """通过 preferred_route_id 指定具体路由。"""
    config = _make_test_routes_config()
    router = ProviderRouter(config)

    route = router.resolve_route("translate", preferred_route_id="translate.high")
    assert route.route_id == "translate.high"
    assert route.audit is True


def test_resolve_route_raises_for_unknown_task_type() -> None:
    """未注册的 task_type 抛出 ValueError。"""
    config = _make_test_routes_config()
    router = ProviderRouter(config)

    with pytest.raises(ValueError, match="任务类型 'unknown' 无匹配路由"):
        router.resolve_route("unknown")


def test_resolve_route_raises_for_unknown_route_id() -> None:
    """显式指定的 route_id 不存在时抛出 ValueError。"""
    config = _make_test_routes_config()
    router = ProviderRouter(config)

    with pytest.raises(ValueError, match="路由 'nonexistent' 未在配置中找到"):
        router.resolve_route("judge", preferred_route_id="nonexistent")


# ------------------------------------------------------------------
# get_fallback_route
# ------------------------------------------------------------------


def test_get_fallback_route_from_route_chain() -> None:
    """路由自身 fallback_route_ids 中配置了回退路由。"""
    config = _make_test_routes_config()
    router = ProviderRouter(config)

    primary = router.get_route_by_id("judge.primary")
    assert primary is not None

    fallback = router.get_fallback_route(primary)
    assert fallback is not None
    assert fallback.route_id == "fallback.local"


def test_get_fallback_route_from_global() -> None:
    """路由自身无回退时，使用全局 fallback_route_id。"""
    config = _make_test_routes_config()
    router = ProviderRouter(config)

    classify_route = router.get_route_by_id("classify.primary")
    assert classify_route is not None
    # classify.primary 无 fallback_route_ids → 回退到全局 fallback.local
    fallback = router.get_fallback_route(classify_route)
    assert fallback is not None
    assert fallback.route_id == "fallback.local"


def test_get_fallback_route_returns_none_when_already_fallback() -> None:
    """已经是全局回退路由本身时返回 None（避免自循环）。"""
    config = _make_test_routes_config()
    router = ProviderRouter(config)

    fallback_route = router.get_route_by_id("fallback.local")
    assert fallback_route is not None

    result = router.get_fallback_route(fallback_route)
    assert result is None


# ------------------------------------------------------------------
# get_route_by_id / list_routes_for_task
# ------------------------------------------------------------------


def test_get_route_by_id() -> None:
    """按 route_id 精确查找路由。"""
    config = _make_test_routes_config()
    router = ProviderRouter(config)

    assert router.get_route_by_id("translate.fast") is not None
    assert router.get_route_by_id("nonexistent") is None


def test_list_routes_for_task() -> None:
    """列出某任务类型的所有路由。"""
    config = _make_test_routes_config()
    router = ProviderRouter(config)

    translate_routes = router.list_routes_for_task("translate")
    assert len(translate_routes) == 2
    route_ids = [r.route_id for r in translate_routes]
    assert "translate.fast" in route_ids
    assert "translate.high" in route_ids

    # 无匹配时返回空列表
    unknown_routes = router.list_routes_for_task("unknown")
    assert unknown_routes == []


# ------------------------------------------------------------------
# track_cost / budget
# ------------------------------------------------------------------


def test_track_cost_and_budget() -> None:
    """成本追踪和预算查询。"""
    router = ProviderRouter(_make_test_routes_config(), cost_budget=0.50)

    assert router.remaining_budget() == 0.50
    assert router.is_over_budget() is False

    router.track_cost("translate.fast", 0.01)
    assert router.remaining_budget() == 0.49

    router.track_cost("judge.primary", 0.10)
    assert router.remaining_budget() == 0.39


def test_is_over_budget() -> None:
    """超预算时 is_over_budget 返回 True。"""
    router = ProviderRouter(_make_test_routes_config(), cost_budget=0.05)

    router.track_cost("judge.primary", 0.10)
    assert router.is_over_budget() is True
    assert router.remaining_budget() == 0.0


def test_no_budget_limit() -> None:
    """cost_budget=0 表示不限制。"""
    router = ProviderRouter(_make_test_routes_config())  # default budget 0.0

    router.track_cost("translate.high", 999.0)
    assert router.is_over_budget() is False
    assert router.remaining_budget() == float("inf")


# ------------------------------------------------------------------
# CostTracker 独立测试
# ------------------------------------------------------------------


def test_cost_tracker_within_budget() -> None:
    """CostTracker 在预算内返回 True。"""
    tracker = CostTracker(hard_limit=1.0)
    tracker.record("route_a", 0.10)
    tracker.record("route_b", 0.20)
    assert tracker.within_budget(1.0) is True
    assert tracker.total == pytest.approx(0.30)


def test_cost_tracker_exceeds_budget() -> None:
    """CostTracker 超预算时 within_budget 返回 False。"""
    tracker = CostTracker(hard_limit=1.0)
    tracker.record("route_a", 0.60)
    tracker.record("route_b", 0.50)
    assert tracker.within_budget(1.0) is False
    assert tracker.total == 1.10


def test_cost_tracker_summary() -> None:
    """CostTracker.summary() 返回完整成本摘要。"""
    tracker = CostTracker(hard_limit=2.0)
    tracker.record("route_a", 0.10)
    tracker.record("route_a", 0.15)
    tracker.record("route_b", 0.30)

    s = tracker.summary()
    assert s["total_cost"] == 0.55
    assert s["per_route"]["route_a"] == 0.25
    assert s["per_route"]["route_b"] == 0.30


def test_cost_tracker_soft_limit() -> None:
    """软限制存储但不阻断 within_budget。"""
    tracker = CostTracker(soft_limit=0.30, hard_limit=1.0)
    tracker.record("route_a", 0.50)
    assert tracker.soft_limit == 0.30
    # 超过 soft_limit 但不影响 within_budget(hard_limit)
    assert tracker.within_budget(1.0) is True
    # 超过 hard_limit 则阻断
    tracker.record("route_b", 0.60)
    assert tracker.within_budget(1.0) is False


# ------------------------------------------------------------------
# RulesProvider
# ------------------------------------------------------------------


def test_rules_provider_health_check() -> None:
    """本地 provider 健康检查始终返回 True。"""
    provider = RulesProvider()
    assert provider.health_check() is True
    assert provider.provider_id == "local"


def test_rules_provider_is_ai_provider() -> None:
    """RulesProvider 满足 AIProvider 协议（runtime_checkable）。"""
    provider = RulesProvider()
    assert isinstance(provider, AIProvider)


def test_rules_provider_call_judge() -> None:
    """本地 judge 调用返回结构化结果。"""
    provider = RulesProvider()
    result = provider.call(
        "judge.primary",
        "China and Italy sign new trade deal in Beijing about Belt and Road",
        task_type="judge",
    )
    assert isinstance(result, dict)
    assert "recommendation" in result
    assert "china_relevance" in result
    assert "confidence" in result
    assert "rationale" in result
    assert "flags" in result
    assert result["provider"] == "local"
    # 包含多个 China 关键词（china, beijing, belt and road）→ 高中国关联度
    assert result["china_relevance"] >= 30


def test_rules_provider_call_no_china() -> None:
    """不含中国关键词时 china_relevance 为 0。"""
    provider = RulesProvider()
    result = provider.call(
        "translate.fast",
        "Milan fashion week showcases new summer collection",
        task_type="translate",
    )
    assert result["china_relevance"] == 0
    assert "local_rules" in result["flags"]


def test_rules_provider_call_breaking() -> None:
    """breaking/urgente 关键词触发 breaking_news 分类。"""
    provider = RulesProvider()
    result = provider.call(
        "judge.primary",
        "ULTIMORA: terremoto in Italia centrale, scosse avvertite a Roma",
        task_type="judge",
    )
    assert result["recommendation"] == "publish"
    assert "breaking" in result["flags"]


# ------------------------------------------------------------------
# TestRouteOrchestration — route() 编排方法测试
# ------------------------------------------------------------------


class TestRouteOrchestration:
    """route() 方法的完整编排逻辑测试：解析 → 预算 → 调用 → 回退 → 成本。"""

    @staticmethod
    def _mock_provider_factory(
        return_value: dict[str, object] | None = None,
        side_effect: Exception | None = None,
    ) -> mock.MagicMock:
        """创建返回模拟 AIProvider 的工厂函数。

        返回的 MagicMock 在调用 factory(provider_name) 时返回模拟 provider；
        该 provider 的 .call() 返回给定值或抛出异常。
        """
        mock_provider = mock.MagicMock()
        if side_effect is not None:
            mock_provider.call.side_effect = side_effect
        else:
            mock_provider.call.return_value = return_value or {
                "content": "mock response",
                "model": "mock-model",
                "usage": {"total_tokens": 42},
                "route_id": "judge.primary",
                "provider": "<placeholder>",
            }
        factory = mock.MagicMock(return_value=mock_provider)
        return factory

    # ── 正常流程 ──────────────────────────────────────────────────

    def test_route_resolves_and_calls_provider(self) -> None:
        """route() 解析路由并调用 provider，返回正确结果。"""
        router = ProviderRouter(_make_test_routes_config())
        factory = self._mock_provider_factory()

        result = router.route("judge", "test prompt", factory)

        assert result["content"] == "mock response"
        assert result["fallback_used"] is False
        assert result["budget_exceeded"] is False
        assert result["model"] == "mock-model"
        assert result["usage"] == {"total_tokens": 42}
        # 验证工厂被调用 — 路由 judge.primary 的 provider 为 "<placeholder>"
        factory.assert_called_with("<placeholder>")

    # ── 预算超限 ──────────────────────────────────────────────────

    def test_route_budget_exceeded(self) -> None:
        """预算耗尽时 route() 不再调用 provider，直接返回 budget_exceeded=True。"""
        router = ProviderRouter(_make_test_routes_config(), cost_budget=0.01)
        router.track_cost("translate.fast", 0.02)  # 超出 0.01 预算

        factory = mock.MagicMock()  # 不应被调用
        result = router.route("judge", "test prompt", factory)

        assert result["budget_exceeded"] is True
        assert result["content"] == ""
        assert result["provider"] == ""
        factory.assert_not_called()

    # ── 回退逻辑 ──────────────────────────────────────────────────

    def test_route_fallback_on_primary_failure(self) -> None:
        """主 provider 抛异常时自动回退到 fallback provider。"""
        router = ProviderRouter(_make_test_routes_config())

        primary = mock.MagicMock()
        primary.call.side_effect = RuntimeError("primary error")
        fallback = mock.MagicMock()
        fallback.call.return_value = {
            "content": "fallback response",
            "model": "fallback-model",
            "usage": {"total_tokens": 10},
            "route_id": "fallback.local",
            "provider": "local",
        }

        def factory(provider_name: str) -> AIProvider | None:
            if provider_name == "<placeholder>":
                return primary
            if provider_name == "local":
                return fallback
            return None

        result = router.route("judge", "test prompt", factory)

        assert result["fallback_used"] is True
        assert result["content"] == "fallback response"
        assert result["route_id"] == "fallback.local"
        assert result["provider"] == "local"
        primary.call.assert_called_once()
        fallback.call.assert_called_once()

    def test_route_all_providers_fail(self) -> None:
        """所有 provider（含回退链）均失败时返回 error 和空 content。"""
        router = ProviderRouter(_make_test_routes_config())

        failing = mock.MagicMock()
        failing.call.side_effect = RuntimeError("all providers down")

        def factory(provider_name: str) -> AIProvider | None:
            return failing

        result = router.route("judge", "test prompt", factory)

        assert "error" in result
        assert "all providers down" in result["error"]
        assert result["content"] == ""
        assert result["fallback_used"] is True

    # ── preferred_route_id ────────────────────────────────────────

    def test_route_uses_preferred_route_id(self) -> None:
        """preferred_route_id 指定后使用对应路由的 provider。"""
        router = ProviderRouter(_make_test_routes_config())
        mock_provider = mock.MagicMock()
        mock_provider.call.return_value = {
            "content": "preferred response",
            "model": "preferred-model",
            "usage": {},
            "route_id": "translate.high",
            "provider": "<placeholder>",
        }

        factory = mock.MagicMock(return_value=mock_provider)
        # 使用 preferred_route_id 覆盖默认 task_type 匹配
        result = router.route(
            "translate", "test prompt", factory,
            preferred_route_id="translate.high",
        )

        assert result["route_id"] == "translate.high"
        factory.assert_called_with("<placeholder>")

    # ── 成本追踪 ──────────────────────────────────────────────────

    def test_route_tracks_cost_on_success(self) -> None:
        """成功调用后 cost_tracker.total 增加对应路由的 max_cost_usd_per_call。"""
        router = ProviderRouter(_make_test_routes_config())
        factory = self._mock_provider_factory()

        assert router.cost_tracker.total == 0.0
        router.route("judge", "test prompt", factory)
        # judge.primary 的 max_cost_usd_per_call = 0.10
        assert router.cost_tracker.total == 0.10

    # ── 配置集成 ──────────────────────────────────────────────────

    def test_route_uses_router_config(self) -> None:
        """route() 使用初始化时注入的 ProviderRoutesConfig 进行路由匹配。"""
        config = _make_test_routes_config()
        router = ProviderRouter(config)
        # 为所有 provider 名创建统一 mock
        mock_provider = mock.MagicMock()
        mock_provider.call.return_value = {
            "content": "config-based response",
            "model": "config-model",
            "usage": {},
            "route_id": "classify.primary",
            "provider": "<placeholder>",
        }

        def factory(provider_name: str) -> AIProvider | None:
            return mock_provider

        result = router.route("classify", "test prompt", factory)

        # 验证使用了配置中的 classify.primary 路由
        assert result["route_id"] == "classify.primary"
        assert result["fallback_used"] is False
        assert result["budget_exceeded"] is False
        assert result["content"] == "config-based response"
