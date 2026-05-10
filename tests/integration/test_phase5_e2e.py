"""Phase 5 端到端集成测试：ProviderRouter.route() 全链路。

覆盖：route() 编排 → Provider 调用 → 回退切换 → 成本追踪 → 预算超限。
使用 mock AIProvider 避免真实 API 调用。
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest import mock

import pytest

from news_sentry.core.provider_router import ProviderRouter
from news_sentry.models.provider_config import ProviderRoute, ProviderRoutesConfig

# ── 测试用路由配置 ─────────────────────────────────────────────────────

def _make_e2e_routes_config() -> ProviderRoutesConfig:
    """构造含主路由 + 回退路由的测试配置。"""
    return ProviderRoutesConfig(
        routes_version="1.0.0",
        fallback_route_id="fallback.local",
        routes=[
            ProviderRoute(
                route_id="judge.primary",
                task_type="judge",
                provider="openai",
                model="gpt-4o",
                timeout_seconds=60,
                max_cost_usd_per_call=0.10,
                audit=True,
                fallback_route_ids=["judge.anthropic"],
            ),
            ProviderRoute(
                route_id="judge.anthropic",
                task_type="judge",
                provider="anthropic",
                model="claude-3-haiku-20240307",
                timeout_seconds=60,
                max_cost_usd_per_call=0.05,
                audit=True,
            ),
            ProviderRoute(
                route_id="translate.fast",
                task_type="translate",
                provider="openai",
                model="gpt-4o-mini",
                timeout_seconds=30,
                max_cost_usd_per_call=0.01,
            ),
            ProviderRoute(
                route_id="fallback.local",
                task_type="judge",
                provider="local",
                model="rules-engine",
                timeout_seconds=120,
                max_cost_usd_per_call=0.0,
            ),
        ],
    )


# ── 模拟 Provider ───────────────────────────────────────────────────────

def _make_mock_provider(
    content: str = "mock response",
    should_fail: bool = False,
    provider_name: str = "",
) -> mock.MagicMock:
    """创建模拟 AIProvider，side_effect 动态填充 route_id/provider。"""
    provider = mock.MagicMock()
    if should_fail:
        provider.call.side_effect = RuntimeError("模拟 Provider 调用失败")
    else:
        def call_side_effect(
            route_id: str = "", prompt: str = "", **kwargs: Any,  # noqa: ARG001
        ) -> dict[str, Any]:
            return {
                "content": content,
                "model": "mock-model",
                "usage": {"total_tokens": 50},
                "route_id": route_id,
                "provider": provider_name or "mock",
            }
        provider.call.side_effect = call_side_effect
    return provider


def _factory(providers: dict[str, mock.MagicMock | None]) -> Callable[[str], Any | None]:
    """创建 provider_factory callable。"""
    def inner(name: str) -> Any | None:
        return providers.get(name)
    return inner


# ── 夹具 ────────────────────────────────────────────────────────────────

@pytest.fixture
def router() -> ProviderRouter:
    """不带预算限制的 ProviderRouter。"""
    return ProviderRouter(_make_e2e_routes_config())


@pytest.fixture
def router_with_budget() -> ProviderRouter:
    """带 $0.03 预算的 ProviderRouter。"""
    return ProviderRouter(_make_e2e_routes_config(), cost_budget=0.03)


# ── route() 编排：成功路径 ─────────────────────────────────────────────

class TestRouteSuccess:
    """route() 成功调用路径。"""

    def test_route_resolves_and_calls_primary(self, router):
        """route() 按 task_type 解析路由并调用 Provider。"""
        mock_openai = _make_mock_provider(content="AI 研判结果", provider_name="openai")
        factory = _factory({"openai": mock_openai})

        result = router.route("judge", "test prompt", factory)

        assert result["content"] == "AI 研判结果"
        assert result["fallback_used"] is False
        assert result["budget_exceeded"] is False
        assert result["route_id"] == "judge.primary"
        assert result["provider"] == "openai"
        mock_openai.call.assert_called_once()

    def test_route_with_preferred_route_id(self, router):
        """preferred_route_id 显式指定路由。"""
        mock_anthropic = _make_mock_provider(content="Claude 研判结果", provider_name="anthropic")
        factory = _factory({"anthropic": mock_anthropic})

        result = router.route(
            "judge", "test prompt", factory,
            preferred_route_id="judge.anthropic",
        )

        assert result["route_id"] == "judge.anthropic"
        assert result["provider"] == "anthropic"
        assert result["content"] == "Claude 研判结果"
        mock_anthropic.call.assert_called_once()

    def test_route_tracks_cost_on_success(self, router):
        """成功调用后成本被追踪。"""
        mock_openai = _make_mock_provider(provider_name="openai")
        factory = _factory({"openai": mock_openai})

        assert router.cost_tracker.total == 0.0
        router.route("judge", "test prompt", factory)
        # judge.primary max_cost_usd_per_call = 0.10
        assert router.cost_tracker.total == 0.10

    def test_route_passes_kwargs_to_provider(self, router):
        """route() 将 **kwargs 转发给 provider.call()。"""
        mock_openai = _make_mock_provider(provider_name="openai")
        factory = _factory({"openai": mock_openai})

        router.route("judge", "test prompt", factory, max_tokens=500, temperature=0.3)

        call_kwargs = mock_openai.call.call_args.kwargs
        assert call_kwargs.get("max_tokens") == 500
        assert call_kwargs.get("temperature") == 0.3


# ── route() 编排：回退路径 ─────────────────────────────────────────────

class TestRouteFallback:
    """route() 回退链路测试。"""

    def test_primary_fails_fallback_succeeds(self, router):
        """主 Provider 失败 → 自动回退到 judge.anthropic。"""
        mock_openai = _make_mock_provider(should_fail=True)
        mock_anthropic = _make_mock_provider(
            content="回退 Provider 结果", provider_name="anthropic"
        )
        factory = _factory({"openai": mock_openai, "anthropic": mock_anthropic})

        result = router.route("judge", "test prompt", factory)

        assert result["fallback_used"] is True
        assert result["budget_exceeded"] is False
        assert result["content"] == "回退 Provider 结果"
        assert result["route_id"] == "judge.anthropic"
        assert result["provider"] == "anthropic"
        mock_openai.call.assert_called_once()
        mock_anthropic.call.assert_called_once()

    def test_fallback_chain_to_local(self, router):
        """主 + 回退均失败 → 最终回退到 fallback.local。"""
        mock_openai = _make_mock_provider(should_fail=True)
        mock_anthropic = _make_mock_provider(should_fail=True)
        mock_local = _make_mock_provider(content="本地规则引擎结果", provider_name="local")
        factory = _factory({
            "openai": mock_openai, "anthropic": mock_anthropic, "local": mock_local,
        })

        result = router.route("judge", "test prompt", factory)

        assert result["fallback_used"] is True
        assert result["content"] == "本地规则引擎结果"
        mock_openai.call.assert_called_once()
        mock_anthropic.call.assert_called_once()
        mock_local.call.assert_called_once()

    def test_all_providers_fail(self, router):
        """所有 Provider 均失败 → 返回 error。"""
        mock_openai = _make_mock_provider(should_fail=True)
        mock_anthropic = _make_mock_provider(should_fail=True)
        mock_local = _make_mock_provider(should_fail=True)
        factory = _factory({
            "openai": mock_openai, "anthropic": mock_anthropic, "local": mock_local,
        })

        result = router.route("judge", "test prompt", factory)

        assert "error" in result
        assert result["content"] == ""
        assert result["fallback_used"] is True
        assert result["budget_exceeded"] is False

    def test_provider_unavailable_triggers_fallback(self, router):
        """工厂返回 None → 跳过该 Provider → 使用回退。"""
        mock_anthropic = _make_mock_provider(
            content="跳过 OpenAI 后的结果", provider_name="anthropic"
        )
        factory = _factory({"openai": None, "anthropic": mock_anthropic})

        result = router.route("judge", "test prompt", factory)

        assert result["fallback_used"] is True
        assert result["content"] == "跳过 OpenAI 后的结果"
        assert result["route_id"] == "judge.anthropic"


# ── route() 编排：预算超限 ─────────────────────────────────────────────

class TestRouteBudget:
    """route() 预算超限测试。"""

    def test_budget_exceeded_blocks_call(self, router_with_budget):
        """预算超限时跳过 AI 调用，返回 budget_exceeded=True。"""
        mock_openai = _make_mock_provider(provider_name="openai")
        factory = _factory({"openai": mock_openai})

        # 先消耗超预算（预算仅 0.03，消耗 0.05 即可超限）
        router_with_budget.track_cost("translate.fast", 0.05)

        result = router_with_budget.route("judge", "test prompt", factory)

        assert result["budget_exceeded"] is True
        assert result["content"] == ""
        assert result["fallback_used"] is False
        mock_openai.call.assert_not_called()


# ── route() 编排：端到端完整链 ─────────────────────────────────────────

class TestFullE2EChain:
    """完整的端到端编排链路。"""

    def test_judge_primary_to_anthropic_fallback_with_cost(self, router):
        """完整链：judge.primary(OpenAI) 失败 → judge.anthropic 成功 + 成本追踪。"""
        mock_openai = _make_mock_provider(should_fail=True)
        mock_anthropic = _make_mock_provider(
            content="Anthropic 研判完成", provider_name="anthropic"
        )
        factory = _factory({"openai": mock_openai, "anthropic": mock_anthropic})

        result = router.route("judge", "综合研判 prompt", factory)

        assert result["content"] == "Anthropic 研判完成"
        assert result["fallback_used"] is True
        assert result["route_id"] == "judge.anthropic"
        # 只有成功的回退调用被计费
        assert router.cost_tracker.total == 0.05  # judge.anthropic max_cost

    def test_translate_route_no_fallback_needed(self, router):
        """translate.fast 直接成功，无需回退。"""
        mock_openai = _make_mock_provider(content="翻译完成：中文标题", provider_name="openai")
        factory = _factory({"openai": mock_openai})

        result = router.route("translate", "Translate title", factory)

        assert result["content"] == "翻译完成：中文标题"
        assert result["fallback_used"] is False
        assert result["route_id"] == "translate.fast"
        assert router.cost_tracker.total == 0.01
