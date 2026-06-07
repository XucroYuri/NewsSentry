"""Phase 5: Provider Router — resolution, fallback, cost tracking.

Implements: docs/spec/phase-5-ai-provider-routing.md
Contracts: docs/contracts-canonical.md §7
ADR: ADR-0005
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from typing import Any

from news_sentry.adapters.providers.base import AIProvider
from news_sentry.models.provider_config import ProviderRoute, ProviderRoutesConfig

logger = logging.getLogger(__name__)

_MODEL_COOLDOWN_SECONDS = 30 * 60


class CostTracker:
    """基于路由的 AI 调用成本追踪器。

    支持软限制（警告）和硬限制（阻断）：
    - soft limit: 达到时发出警告日志，不阻断
    - hard limit: 达到时 ``within_budget`` 返回 False，应阻断调用

    所有操作 O(1)。
    """

    def __init__(self, soft_limit: float = 0.0, hard_limit: float = 0.0) -> None:
        self._soft_limit = soft_limit
        self._hard_limit = hard_limit
        self._per_route: dict[str, float] = {}
        self._total: float = 0.0

    def record(self, route_id: str, usd_cost: float) -> None:
        """记录一次 AI 调用的成本。

        Args:
            route_id: 路由标识。
            usd_cost: 本次调用的 USD 成本。
        """
        self._per_route[route_id] = self._per_route.get(route_id, 0.0) + usd_cost
        self._total += usd_cost

    def within_budget(self, limit: float) -> bool:
        """检查总成本是否在给定限额内。

        Args:
            limit: USD 预算上限。

        Returns:
            True 如果 ``total <= limit``，否则 False。
        """
        return self._total <= limit

    def summary(self) -> dict[str, Any]:
        """返回成本摘要。

        Returns:
            dict with ``total_cost`` (float) and ``per_route`` (dict[str, float])。
        """
        return {
            "total_cost": round(self._total, 6),
            "per_route": dict(self._per_route),
        }

    @property
    def total(self) -> float:
        """累计总成本（USD）。"""
        return self._total

    @property
    def soft_limit(self) -> float:
        return self._soft_limit

    @property
    def hard_limit(self) -> float:
        return self._hard_limit


class ProviderRouter:
    """AI Provider 路由引擎 — 根据 task_type/preferred_route_id 匹配路由。

    功能：
    - 按 task_type 查找最佳路由
    - 支持显式 route_id 指定
    - 支持回退链 (fallback_route_ids + 全局 fallback_route_id)
    - 运行时成本追踪
    """

    def __init__(
        self,
        routes_config: ProviderRoutesConfig,
        cost_budget: float = 0.0,
    ) -> None:
        """初始化路由器。

        Args:
            routes_config: 加载的路由配置。
            cost_budget: 本次运行的最大成本预算（USD），0 表示不限制。
        """
        self._config = routes_config
        self._cost_budget = cost_budget
        self._cost_tracker = CostTracker(hard_limit=cost_budget)
        # 构建 route_id → route 索引，O(1) 查找
        self._route_index: dict[str, ProviderRoute] = {r.route_id: r for r in routes_config.routes}
        # 构建 task_type → 路由列表索引
        self._task_index: dict[str, list[ProviderRoute]] = {}
        for route in routes_config.routes:
            self._task_index.setdefault(route.task_type, []).append(route)
        self._model_cursor: dict[str, int] = {}
        self._model_cooldowns: dict[tuple[str, str], float] = {}

    # ── 路由解析 ──────────────────────────────────────────────────

    def resolve_route(
        self,
        task_type: str,
        preferred_route_id: str | None = None,
    ) -> ProviderRoute:
        """为任务类型查找最佳路由。

        解析顺序：
        1. 如果指定了 preferred_route_id，优先返回该路由
        2. 否则返回匹配 task_type 的第一条路由
        3. 无匹配则抛出 ValueError

        Args:
            task_type: 任务类型（translate/judge/classify）。
            preferred_route_id: 可选，优先使用的路由 ID。

        Returns:
            匹配的 ProviderRoute。

        Raises:
            ValueError: 未找到匹配路由。
        """
        # 显式指定路由 ID 优先
        if preferred_route_id is not None:
            route = self._route_index.get(preferred_route_id)
            if route is not None:
                return route
            raise ValueError(
                f"路由 '{preferred_route_id}' 未在配置中找到。"
                f" 可用路由: {list(self._route_index.keys())}"
            )

        # 按 task_type 查找
        candidates = self._task_index.get(task_type, [])
        if not candidates:
            raise ValueError(
                f"任务类型 '{task_type}' 无匹配路由。 可用类型: {list(self._task_index.keys())}"
            )
        return candidates[0]

    def get_fallback_route(self, route: ProviderRoute) -> ProviderRoute | None:
        """获取指定路由的下一级回退路由。

        查找顺序：
        1. 路由自身的 fallback_route_ids（按序尝试）
        2. 全局 fallback_route_id
        3. 都没有则返回 None

        Args:
            route: 当前路由。

        Returns:
            回退路由，无可用回退时返回 None。
        """
        # 先检查路由自身的回退链
        for fallback_id in route.fallback_route_ids:
            fb = self._route_index.get(fallback_id)
            if fb is not None:
                return fb

        # 再检查全局回退
        global_fb = self._route_index.get(self._config.fallback_route_id)
        if global_fb is not None and global_fb.route_id != route.route_id:
            return global_fb

        return None

    def get_route_by_id(self, route_id: str) -> ProviderRoute | None:
        """按 route_id 精确查找路由。

        Args:
            route_id: 路由标识。

        Returns:
            ProviderRoute 或 None。
        """
        return self._route_index.get(route_id)

    def list_routes_for_task(self, task_type: str) -> list[ProviderRoute]:
        """列出某任务类型的所有可用路由。

        Args:
            task_type: 任务类型。

        Returns:
            匹配的 ProviderRoute 列表（可能为空）。
        """
        return list(self._task_index.get(task_type, []))

    # ── 成本追踪 ──────────────────────────────────────────────────

    def track_cost(self, route_id: str, usd_cost: float) -> None:
        """记录一次 AI 调用的成本。

        Args:
            route_id: 使用的路由 ID。
            usd_cost: 本次调用 USD 成本。
        """
        self._cost_tracker.record(route_id, usd_cost)

    def is_over_budget(self) -> bool:
        """检查是否已超出运行预算。

        Returns:
            True 如果累计成本 > 预算（且预算 > 0）。
        """
        if self._cost_budget <= 0:
            return False
        return self._cost_tracker.total > self._cost_budget

    def remaining_budget(self) -> float:
        """返回剩余预算（USD）。

        Returns:
            max(0, budget - total_cost)，budget 为 0 时返回 inf。
        """
        if self._cost_budget <= 0:
            return float("inf")
        return max(0.0, self._cost_budget - self._cost_tracker.total)

    @property
    def cost_tracker(self) -> CostTracker:
        """获取内部 CostTracker 实例，用于外部查询成本详情。"""
        return self._cost_tracker

    @property
    def routes_config(self) -> ProviderRoutesConfig:
        """获取当前路由配置。"""
        return self._config

    # ── 模型池轮换 ────────────────────────────────────────────────

    @staticmethod
    def _dedupe_models(models: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for model in models:
            normalized = model.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result

    def _model_candidates(self, route: ProviderRoute) -> list[str]:
        """返回本次调用应尝试的模型顺序。

        ``route.model`` 保持兼容语义；``route.model_pool`` 提供低成本候选池。
        每个 route 独立轮换，429/402 等错误触发短期冷却。
        """

        if route.model_env_var:
            route_model = os.environ.get(route.model_env_var, route.model)
        else:
            route_model = route.model
        models = self._dedupe_models([route_model, *route.model_pool])
        if not models:
            return [route.model]

        now = time.monotonic()
        active = [
            model
            for model in models
            if self._model_cooldowns.get((route.provider, model), 0.0) <= now
        ]
        candidates = active or models
        cursor = self._model_cursor.get(route.route_id, 0) % len(candidates)
        self._model_cursor[route.route_id] = (cursor + 1) % len(candidates)
        return [*candidates[cursor:], *candidates[:cursor]]

    @staticmethod
    def _is_rate_or_credit_error(error: BaseException | str) -> bool:
        text = str(error).lower()
        return any(
            marker in text
            for marker in (
                "429",
                "rate limit",
                "too many requests",
                "402",
                "insufficient credits",
                "quota",
            )
        )

    def _cooldown_model_if_needed(
        self,
        route: ProviderRoute,
        model: str,
        error: BaseException | str,
    ) -> None:
        if not model or not self._is_rate_or_credit_error(error):
            return
        self._model_cooldowns[(route.provider, model)] = time.monotonic() + _MODEL_COOLDOWN_SECONDS

    @staticmethod
    def _validate_ai_result(route: ProviderRoute, model: str, result: dict[str, Any]) -> None:
        if route.provider == "local":
            return
        content = result.get("content")
        if content is None or not str(content).strip():
            raise RuntimeError(
                f"Provider '{route.provider}' model '{model}' returned empty content"
            )

    # ── 路由编排 ──────────────────────────────────────────────────

    def route(
        self,
        task_type: str,
        prompt: str,
        provider_factory: Callable[[str], AIProvider | None],
        preferred_route_id: str | None = None,
        **kwargs: Any,  # noqa: ANN401
    ) -> dict[str, Any]:
        """执行完整的 AI 路由编排：解析 → 预算检查 → 调用 → 回退 → 成本记录。

        SPEC §3.1 定义的 route() 编排方法，将路由解析、Provider 调用、
        fallback 切换和成本追踪串联为一次调用。

        Args:
            task_type: 任务类型（translate/judge/classify）。
            prompt: 发送给 AI Provider 的提示词。
            provider_factory: 将 provider_name 映射为 AIProvider 实例的工厂函数。
            preferred_route_id: 可选，优先使用的路由 ID。
            **kwargs: 转发给 AIProvider.call() 的额外参数（如 model, max_tokens）。

        Returns:
            dict with keys:
            - content (str): AI 响应文本
            - model (str): 实际使用的模型
            - usage (dict): token 用量
            - route_id (str): 使用的路由 ID
            - provider (str): 实际 Provider 名称
            - fallback_used (bool): 是否使用了回退路由
            - budget_exceeded (bool): 是否因预算超限被跳过
        """
        # 1) 解析路由
        route = self.resolve_route(task_type, preferred_route_id)

        # 2) 预算检查
        if self.is_over_budget():
            logger.warning(
                "预算超限，跳过 AI 调用: route_id=%s budget=%.4f cost=%.4f",
                route.route_id,
                self._cost_budget,
                self._cost_tracker.total,
            )
            return {
                "content": "",
                "model": "",
                "usage": {},
                "route_id": route.route_id,
                "provider": "",
                "fallback_used": False,
                "budget_exceeded": True,
            }

        # 3) 尝试主路由 + 回退链
        current_route: ProviderRoute | None = route
        fallback_used = False
        last_error: str | None = None

        while current_route is not None:
            provider = provider_factory(current_route.provider)
            if provider is None:
                logger.warning(
                    "Provider '%s' 不可用，尝试回退",
                    current_route.provider,
                )
                current_route = self.get_fallback_route(current_route)
                fallback_used = True
                continue

            for model in self._model_candidates(current_route):
                try:
                    call_kwargs = dict(kwargs)
                    if not call_kwargs.get("model"):
                        call_kwargs["model"] = model
                    result = provider.call(
                        route_id=current_route.route_id,
                        prompt=prompt,
                        **call_kwargs,
                    )
                    result = dict(result)
                    self._validate_ai_result(current_route, model, result)
                    # 4) 记录成本
                    cost = current_route.max_cost_usd_per_call
                    self.track_cost(current_route.route_id, cost)

                    result.setdefault("route_id", current_route.route_id)
                    result.setdefault("provider", current_route.provider)
                    result.setdefault("model", model)
                    result["fallback_used"] = fallback_used
                    result["budget_exceeded"] = False
                    return result

                except Exception as e:
                    last_error = str(e)
                    self._cooldown_model_if_needed(current_route, model, e)
                    logger.warning(
                        "Provider '%s' model '%s' 调用失败: %s",
                        current_route.provider,
                        model,
                        e,
                    )
                    continue

            current_route = self.get_fallback_route(current_route)
            fallback_used = True

        # 5) 所有 Provider 均失败
        logger.error(
            "所有 Provider 均失败: route_id=%s last_error=%s",
            route.route_id,
            last_error,
        )
        return {
            "content": "",
            "model": "",
            "usage": {},
            "route_id": route.route_id,
            "provider": "",
            "fallback_used": True,
            "budget_exceeded": False,
            "error": last_error or "All providers failed",
        }

    # ── 异步路由编排 ──────────────────────────────────────────────

    async def route_async(
        self,
        task_type: str,
        prompt: str,
        provider_factory: Callable[[str], AIProvider | None],
        preferred_route_id: str | None = None,
        **kwargs: Any,  # noqa: ANN401
    ) -> dict[str, Any]:
        """异步版路由编排：解析 → 预算检查 → async 调用 → 回退 → 成本记录。

        优先调用 provider.call_async（鸭子类型检测），无则通过
        asyncio.to_thread 回退到同步 call()。

        Args:
            task_type: 任务类型（translate/judge/classify）。
            prompt: 发送给 AI Provider 的提示词。
            provider_factory: 将 provider_name 映射为 AIProvider 实例的工厂函数。
            preferred_route_id: 可选，优先使用的路由 ID。
            **kwargs: 转发给 AIProvider 的额外参数（如 model, max_tokens）。

        Returns:
            与 route() 相同结构的 dict。
        """
        import asyncio

        route = self.resolve_route(task_type, preferred_route_id)

        if self.is_over_budget():
            logger.warning("预算超限，跳过 AI 调用: route_id=%s", route.route_id)
            return {
                "content": "",
                "model": "",
                "usage": {},
                "route_id": route.route_id,
                "provider": "",
                "fallback_used": False,
                "budget_exceeded": True,
            }

        current_route: ProviderRoute | None = route
        fallback_used = False
        last_error: str | None = None

        while current_route is not None:
            provider = provider_factory(current_route.provider)
            if provider is None:
                current_route = self.get_fallback_route(current_route)
                fallback_used = True
                continue

            for model in self._model_candidates(current_route):
                try:
                    call_kwargs = dict(kwargs)
                    if not call_kwargs.get("model"):
                        call_kwargs["model"] = model
                    if hasattr(provider, "call_async") and callable(provider.call_async):
                        result = await provider.call_async(
                            route_id=current_route.route_id,
                            prompt=prompt,
                            **call_kwargs,
                        )
                    else:
                        result = await asyncio.to_thread(
                            provider.call,
                            route_id=current_route.route_id,
                            prompt=prompt,
                            **call_kwargs,
                        )

                    result = dict(result)
                    self._validate_ai_result(current_route, model, result)
                    cost = current_route.max_cost_usd_per_call
                    self.track_cost(current_route.route_id, cost)
                    result.setdefault("route_id", current_route.route_id)
                    result.setdefault("provider", current_route.provider)
                    result.setdefault("model", model)
                    result["fallback_used"] = fallback_used
                    result["budget_exceeded"] = False
                    return result

                except Exception as e:
                    last_error = str(e)
                    self._cooldown_model_if_needed(current_route, model, e)
                    logger.warning(
                        "Provider '%s' model '%s' 异步调用失败: %s",
                        current_route.provider,
                        model,
                        e,
                    )
                    continue

            current_route = self.get_fallback_route(current_route)
            fallback_used = True

        logger.error("所有 Provider 异步调用均失败: route_id=%s", route.route_id)
        return {
            "content": "",
            "model": "",
            "usage": {},
            "route_id": route.route_id,
            "provider": "",
            "fallback_used": True,
            "budget_exceeded": False,
            "error": last_error or "All providers failed",
        }
