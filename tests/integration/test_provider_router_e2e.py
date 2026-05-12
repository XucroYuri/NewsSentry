"""Provider Router 端到端集成测试。

测试 ProviderRouter + ProviderRoute + CostTracker + RulesProvider 的完整链路,
覆盖路由解析 -> Provider 调用 -> 回退切换 -> 成本追踪全流程。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from news_sentry.adapters.providers.base import AIProvider
from news_sentry.adapters.providers.rules_provider import RulesProvider
from news_sentry.core.provider_router import CostTracker, ProviderRouter
from news_sentry.models.provider_config import ProviderRoutesConfig

# ── 测试用模拟 Provider ──────────────────────────────────────────────


class MockFailingProvider(AIProvider):
    """模拟 OpenAI Provider，调用时抛出异常，用于测试回退链路。"""

    provider_id = "openai"

    def __init__(self, should_fail: bool = True) -> None:
        self._should_fail = should_fail
        self.call_count: int = 0

    def call(self, route_id: str, prompt: str, **kwargs: Any) -> dict[str, Any]:  # noqa: ARG002, ANN401
        self.call_count += 1
        if self._should_fail:
            raise RuntimeError("模拟 OpenAI API 调用失败：网络超时")
        return {
            "content": "mock openai response",
            "model": "gpt-4o-mini",
            "usage": {"total_tokens": 100},
            "route_id": route_id,
            "provider": "openai",
        }

    def health_check(self) -> bool:
        return not self._should_fail


# ── 共享夹具（fixtures）─────────────────────────────────────────────


@pytest.fixture
def test_routes_data() -> dict[str, Any]:
    """返回测试用路由配置原始 dict。"""
    return {
        "routes_version": "1.0.0",
        "fallback_route_id": "fallback.local",
        "routes": [
            {
                "route_id": "judge.primary",
                "task_type": "judge",
                "provider": "local",
                "model": "local-rules",
                "timeout_seconds": 60,
                "max_cost_usd_per_call": 0.10,
                "output_schema_ref": "schemas/toolrunresult.schema.json",
                "audit": True,
                "fallback_route_ids": ["fallback.local"],
            },
            {
                "route_id": "judge.secondary",
                "task_type": "judge",
                "provider": "local",
                "model": "local-rules",
                "timeout_seconds": 30,
                "max_cost_usd_per_call": 0.05,
                "audit": False,
            },
            {
                "route_id": "filter.primary",
                "task_type": "filter",
                "provider": "local",
                "model": "local-rules",
                "timeout_seconds": 30,
                "max_cost_usd_per_call": 0.02,
                "audit": False,
            },
            {
                "route_id": "fallback.local",
                "task_type": "judge",
                "provider": "local",
                "model": "local-rules",
                "timeout_seconds": 120,
                "max_cost_usd_per_call": 0.0,
            },
        ],
    }


@pytest.fixture
def routes_config(test_routes_data: dict[str, Any]) -> ProviderRoutesConfig:
    """从测试路由 dict 构造 ProviderRoutesConfig。"""
    return ProviderRoutesConfig(**test_routes_data)


@pytest.fixture
def router(routes_config: ProviderRoutesConfig) -> ProviderRouter:
    """创建不带预算限制的 ProviderRouter。"""
    return ProviderRouter(routes_config)


@pytest.fixture
def router_with_budget(routes_config: ProviderRoutesConfig) -> ProviderRouter:
    """创建带 $0.05 预算的 ProviderRouter。"""
    return ProviderRouter(routes_config, cost_budget=0.05)


@pytest.fixture
def tmp_routes_yaml(tmp_path: Path, test_routes_data: dict[str, Any]) -> Path:
    """在 tmp_path 写入测试 routes.yaml，返回文件路径。"""
    provider_dir = tmp_path / "config" / "provider"
    provider_dir.mkdir(parents=True)
    yaml_path = provider_dir / "routes.yaml"
    with open(yaml_path, "w", encoding="utf-8") as f:
        f.write("# Schema: schemas/providerconfig.schema.json\n")
        yaml.safe_dump(test_routes_data, f, allow_unicode=True)
    return yaml_path


@pytest.fixture
def router_from_file(tmp_routes_yaml: Path) -> ProviderRouter:
    """从 tmp_path 中的 YAML 文件加载 ProviderRouter。"""
    with open(tmp_routes_yaml, encoding="utf-8") as f:
        lines = f.readlines()
    # 跳过第一行的 schema 注释
    yaml_content = "".join(lines[1:])
    data: dict[str, Any] = yaml.safe_load(yaml_content)
    config = ProviderRoutesConfig(**data)
    return ProviderRouter(config)


# ── 端到端测试：完整路由链 ──────────────────────────────────────────


class TestFullRouteChain:
    """完整路由链：解析路由 → 实例化 Provider → 调用 → 验证响应结构。"""

    def test_resolve_and_call_judge_primary(
        self,
        router: ProviderRouter,
    ) -> None:
        """解析 judge.primary 路由，使用 RulesProvider 调用并验证响应。"""
        # 1) 解析路由
        route = router.resolve_route("judge")
        assert route.route_id == "judge.primary"
        assert route.task_type == "judge"
        assert route.provider == "local"

        # 2) 基于 route.provider 实例化对应的 AIProvider
        provider = RulesProvider()
        assert isinstance(provider, AIProvider)
        assert provider.provider_id == "local"
        assert provider.health_check() is True

        # 3) 调用 Provider
        result = provider.call(
            route_id=route.route_id,
            prompt="China and Italy sign new Belt and Road trade deal in Beijing",
            task_type=route.task_type,
        )

        # 4) 验证响应结构符合 AIProvider.call() 契约
        assert isinstance(result, dict)
        assert result["provider"] == "local"
        assert result["route_id"] == "judge.primary"
        assert "recommendation" in result
        assert "china_relevance" in result
        assert "confidence" in result
        assert "rationale" in result
        assert "flags" in result

        # 高中国关联度关键词应触发高分
        assert result["china_relevance"] >= 30

    def test_resolve_and_call_with_explicit_route_id(
        self,
        router: ProviderRouter,
    ) -> None:
        """通过 preferred_route_id 显式指定路由并调用。"""
        route = router.resolve_route("judge", preferred_route_id="judge.secondary")
        assert route.route_id == "judge.secondary"
        assert route.timeout_seconds == 30
        assert route.audit is False

        provider = RulesProvider()
        result = provider.call(
            route_id=route.route_id,
            prompt="Milan fashion week showcases new summer collection",
            task_type=route.task_type,
        )
        assert result["route_id"] == "judge.secondary"
        # 无中国关键词 → china_relevance 为 0
        assert result["china_relevance"] == 0

    def test_full_chain_from_yaml_file(
        self,
        router_from_file: ProviderRouter,
    ) -> None:
        """从 YAML 文件加载完整配置，解析路由并调用 Provider。"""
        # 从文件加载的路由器应正确解析
        route = router_from_file.resolve_route("judge")
        assert route.route_id == "judge.primary"
        assert route.max_cost_usd_per_call == 0.10
        assert route.fallback_route_ids == ["fallback.local"]

        # 验证回退路由可用
        fallback = router_from_file.get_fallback_route(route)
        assert fallback is not None
        assert fallback.route_id == "fallback.local"
        assert fallback.provider == "local"

        # 调用回退 Provider
        fb_provider = RulesProvider()
        fb_result = fb_provider.call(
            route_id=fallback.route_id,
            prompt="Chinese investment in Italian ports grows rapidly",
            task_type=fallback.task_type,
        )
        assert fb_result["provider"] == "local"
        # 单个 China 关键词 (chinese) → 10 分
        assert fb_result["china_relevance"] >= 10

    def test_route_metadata_accessible(self, router: ProviderRouter) -> None:
        """解析后的路由元数据（audit、output_schema_ref、timeout）可直接访问。"""
        route = router.resolve_route("judge")
        assert route.audit is True
        assert route.output_schema_ref == "schemas/toolrunresult.schema.json"
        assert route.timeout_seconds == 60


# ── 端到端测试：回退切换 ────────────────────────────────────────────


class TestFallbackSwitching:
    """主 Provider 失败时自动回退到 fallback.local。"""

    _FALLBACK_PROMPT = "Cina e Italia: nuovi accordi commerciali strategici firmati a Pechino"

    def test_primary_fails_fallback_succeeds(
        self,
        router: ProviderRouter,
    ) -> None:
        """模拟主 Provider 异常 → 解析回退路由 → RulesProvider 正常响应。"""
        # 1) 解析主路由
        primary_route = router.resolve_route("judge")
        assert primary_route.route_id == "judge.primary"

        # 2) 模拟主 Provider（MockFailingProvider）抛出异常
        primary_provider = MockFailingProvider(should_fail=True)
        assert primary_provider.health_check() is False

        with pytest.raises(RuntimeError, match="模拟 OpenAI API 调用失败"):
            primary_provider.call(
                route_id=primary_route.route_id,
                prompt=self._FALLBACK_PROMPT,
                task_type=primary_route.task_type,
            )
        assert primary_provider.call_count == 1

        # 3) 获取回退路由
        fallback_route = router.get_fallback_route(primary_route)
        assert fallback_route is not None
        assert fallback_route.route_id == "fallback.local"
        assert fallback_route.provider == "local"

        # 4) 回退 Provider（RulesProvider）调用成功
        fallback_provider = RulesProvider()
        assert isinstance(fallback_provider, RulesProvider)
        result = fallback_provider.call(
            route_id=fallback_route.route_id,
            prompt=self._FALLBACK_PROMPT,
            task_type=fallback_route.task_type,
        )

        # 5) 验证回退返回有效结果
        assert isinstance(result, dict)
        assert result["provider"] == "local"
        assert result["route_id"] == "fallback.local"
        assert "china_relevance" in result
        assert "recommendation" in result

    def test_fallback_is_rules_provider_instance(
        self,
        router: ProviderRouter,
    ) -> None:
        """回退路由的 provider 字段为 'local'，应实例化为 RulesProvider。"""
        primary_route = router.resolve_route("judge")
        fallback_route = router.get_fallback_route(primary_route)
        assert fallback_route is not None
        assert fallback_route.provider == "local"

        # 实例化 RulesProvider 并验证
        fb_provider = RulesProvider()
        assert isinstance(fb_provider, AIProvider)
        assert fb_provider.provider_id == fallback_route.provider
        assert fb_provider.health_check() is True

    def test_fallback_returns_none_when_already_fallback(
        self,
        router: ProviderRouter,
    ) -> None:
        """回退路由自身无进一步回退（防止自循环）。"""
        fallback_route = router.get_route_by_id("fallback.local")
        assert fallback_route is not None

        further_fallback = router.get_fallback_route(fallback_route)
        assert further_fallback is None

    def test_full_fallback_chain_with_cost_tracking(
        self,
        router_with_budget: ProviderRouter,
    ) -> None:
        """主路由失败 → 回退成功 → 同时追踪成本。"""
        router = router_with_budget

        # 主路由调用失败（模拟）
        primary_route = router.resolve_route("judge")
        router.track_cost(primary_route.route_id, 0.0)  # 失败调用不计费

        # 回退路由调用成功
        fallback_route = router.get_fallback_route(primary_route)
        assert fallback_route is not None
        router.track_cost(fallback_route.route_id, 0.0)

        # 成本应仍在预算内
        assert router.is_over_budget() is False
        assert router.remaining_budget() == 0.05


# ── 端到端测试：CostTracker 成本追踪 ────────────────────────────────


class TestCostTrackerIntegration:
    """CostTracker 集成：跨多路由成本累计与软限制执行。"""

    def test_cost_tracker_within_budget_multi_route(self) -> None:
        """多路由调用累计成本在预算内。"""
        tracker = CostTracker(hard_limit=1.0)
        tracker.record("judge.primary", 0.08)
        tracker.record("judge.secondary", 0.04)
        tracker.record("filter.primary", 0.01)

        assert tracker.within_budget(1.0) is True
        assert tracker.total == pytest.approx(0.13)

    def test_cost_tracker_exceeds_hard_limit_blocks(self) -> None:
        """累计成本超过 hard_limit 时 within_budget 返回 False。"""
        tracker = CostTracker(hard_limit=0.10)
        tracker.record("judge.primary", 0.08)
        tracker.record("judge.secondary", 0.05)

        assert tracker.total == pytest.approx(0.13)
        assert tracker.within_budget(0.10) is False

    def test_cost_tracker_soft_limit_warns_but_allows(self) -> None:
        """软限制只记录不阻断，硬限制到达时阻断。"""
        tracker = CostTracker(soft_limit=0.05, hard_limit=0.20)
        tracker.record("judge.primary", 0.08)

        # 超过 soft_limit 但不影响 hard_limit 判断
        assert tracker.soft_limit == 0.05
        assert tracker.total == pytest.approx(0.08)
        assert tracker.within_budget(0.20) is True

        # 超过 hard_limit 才阻断
        tracker.record("judge.secondary", 0.15)
        assert tracker.within_budget(0.20) is False

    def test_cost_tracker_summary_across_routes(self) -> None:
        """summary() 正确汇总各路由成本。"""
        tracker = CostTracker(hard_limit=1.0)
        tracker.record("judge.primary", 0.05)
        tracker.record("judge.primary", 0.03)
        tracker.record("filter.primary", 0.01)

        summary = tracker.summary()
        assert summary["total_cost"] == pytest.approx(0.09)
        assert summary["per_route"]["judge.primary"] == pytest.approx(0.08)
        assert summary["per_route"]["filter.primary"] == pytest.approx(0.01)

    def test_router_budget_enforcement(self, router_with_budget: ProviderRouter) -> None:
        """ProviderRouter 对 is_over_budget 的执行。"""
        router = router_with_budget

        # 初始在预算内
        assert router.remaining_budget() == 0.05
        assert router.is_over_budget() is False

        # 累计超过 $0.05 预算
        router.track_cost("judge.primary", 0.06)
        assert router.is_over_budget() is True
        assert router.remaining_budget() == 0.0

    def test_router_unlimited_budget(self, router: ProviderRouter) -> None:
        """cost_budget=0 时不限制成本。"""
        router.track_cost("judge.primary", 999.0)
        assert router.is_over_budget() is False
        assert router.remaining_budget() == float("inf")

    def test_cost_accumulation_from_multiple_routes_via_router(
        self,
        router: ProviderRouter,
    ) -> None:
        """通过 ProviderRouter.track_cost 累计多个路由成本。"""
        router.track_cost("judge.primary", 0.03)
        router.track_cost("judge.secondary", 0.02)
        router.track_cost("filter.primary", 0.01)

        tracker = router.cost_tracker
        assert tracker.total == pytest.approx(0.06)

        summary = tracker.summary()
        assert summary["total_cost"] == pytest.approx(0.06)
        assert len(summary["per_route"]) == 3


# ── 端到端测试：多路由解析 ──────────────────────────────────────────


class TestMultiRouteResolution:
    """解析多个路由，验证类型正确且无交叉干扰。"""

    def test_resolve_all_task_types(self, router: ProviderRouter) -> None:
        """按 task_type 解析所有路由。"""
        judge_route = router.resolve_route("judge")
        assert judge_route.route_id == "judge.primary"
        assert judge_route.task_type == "judge"

        filter_route = router.resolve_route("filter")
        assert filter_route.route_id == "filter.primary"
        assert filter_route.task_type == "filter"

    def test_resolve_multiple_route_ids(self, router: ProviderRouter) -> None:
        """通过 preferred_route_id 解析多条具体路由。"""
        r1 = router.resolve_route("judge", preferred_route_id="judge.primary")
        r2 = router.resolve_route("judge", preferred_route_id="judge.secondary")

        assert r1.route_id == "judge.primary"
        assert r2.route_id == "judge.secondary"
        assert r1 is not r2
        assert r1.max_cost_usd_per_call == 0.10
        assert r2.max_cost_usd_per_call == 0.05

        # 两条路由不应互相覆盖字段
        assert r1.audit is True
        assert r2.audit is False

    def test_no_cross_route_interference(self, router: ProviderRouter) -> None:
        """多次解析不产生路由交叉干扰。"""
        routes = [
            router.resolve_route("judge", preferred_route_id="judge.primary"),
            router.resolve_route("judge", preferred_route_id="judge.secondary"),
            router.resolve_route("filter", preferred_route_id="filter.primary"),
        ]

        route_ids = [r.route_id for r in routes]
        assert route_ids == ["judge.primary", "judge.secondary", "filter.primary"]

        # 验证每个路由的字段独立
        for r in routes:
            assert r.route_id in {"judge.primary", "judge.secondary", "filter.primary"}
            assert r.timeout_seconds > 0
            assert r.max_cost_usd_per_call >= 0

    def test_list_all_routes_for_judge_task(self, router: ProviderRouter) -> None:
        """list_routes_for_task 列出 judge 任务的所有路由。"""
        judge_routes = router.list_routes_for_task("judge")
        judge_ids = [r.route_id for r in judge_routes]
        assert "judge.primary" in judge_ids
        assert "judge.secondary" in judge_ids
        assert "fallback.local" in judge_ids
        assert len(judge_routes) == 3

    def test_unknown_task_type_raises(self, router: ProviderRouter) -> None:
        """未知 task_type 抛出 ValueError。"""
        with pytest.raises(ValueError, match="任务类型 'nonexistent' 无匹配路由"):
            router.resolve_route("nonexistent")

    def test_unknown_route_id_raises(self, router: ProviderRouter) -> None:
        """显式指定不存在的 route_id 抛出 ValueError。"""
        with pytest.raises(ValueError, match="路由 'ghost.route' 未在配置中找到"):
            router.resolve_route("judge", preferred_route_id="ghost.route")
