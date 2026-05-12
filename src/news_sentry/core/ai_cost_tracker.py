"""Phase 14: AI Cost Tracker — run-level cost and token summary.

Wraps provider_router.CostTracker to add token counting and per-run reporting.
Each bounded run creates one AICostTracker; after the run completes, summary()
produces a JSON-serializable cost report for the run log.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from news_sentry.core.provider_router import CostTracker

logger = logging.getLogger(__name__)


@dataclass
class AICallRecord:
    """单次 AI 调用记录。"""

    route_id: str
    task_type: str
    usd_cost: float
    input_tokens: int = 0
    output_tokens: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class AICostTracker:
    """Run 级 AI 成本追踪器。

    在 ProviderRouter.CostTracker 之上封装，增加：
    - 逐次调用明细（token 数、费用、时间戳）
    - run 级汇总报告
    - 费用/调用次数硬限制
    """

    def __init__(
        self,
        cost_budget: float = 1.0,
        max_calls: int = 200,
    ) -> None:
        self._cost_tracker = CostTracker(hard_limit=cost_budget)
        self._cost_budget = cost_budget
        self._max_calls = max_calls
        self._records: list[AICallRecord] = []
        self._run_id: str = ""
        self._started_at: str = ""

    def start_run(self, run_id: str) -> None:
        """标记 run 开始。"""
        self._run_id = run_id
        self._started_at = datetime.now(UTC).isoformat()

    def record(
        self,
        route_id: str,
        task_type: str,
        usd_cost: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """记录一次 AI 调用。"""
        self._cost_tracker.record(route_id, usd_cost)
        self._records.append(
            AICallRecord(
                route_id=route_id,
                task_type=task_type,
                usd_cost=usd_cost,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        )

    def is_over_budget(self) -> bool:
        """是否超过费用预算。"""
        return not self._cost_tracker.within_budget(self._cost_budget)

    def is_over_call_limit(self) -> bool:
        """是否超过调用次数限制。"""
        return len(self._records) >= self._max_calls

    def should_block(self) -> bool:
        """是否应阻断后续 AI 调用。"""
        return self.is_over_budget() or self.is_over_call_limit()

    @property
    def total_cost(self) -> float:
        """累计总费用（USD）。"""
        return self._cost_tracker.total

    @property
    def total_calls(self) -> int:
        """累计调用次数。"""
        return len(self._records)

    @property
    def total_input_tokens(self) -> int:
        """累计输入 token 数。"""
        return sum(r.input_tokens for r in self._records)

    @property
    def total_output_tokens(self) -> int:
        """累计输出 token 数。"""
        return sum(r.output_tokens for r in self._records)

    def cost_tracker(self) -> CostTracker:
        """返回底层 CostTracker，供 ProviderRouter 使用。"""
        return self._cost_tracker

    def summary(self) -> dict[str, object]:
        """生成 run 级成本汇总报告。"""
        by_task: dict[str, dict[str, int | float]] = {}
        for r in self._records:
            if r.task_type not in by_task:
                by_task[r.task_type] = {
                    "calls": 0,
                    "total_cost": 0.0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                }
            t = by_task[r.task_type]
            t["calls"] += 1
            t["total_cost"] += r.usd_cost
            t["input_tokens"] += r.input_tokens
            t["output_tokens"] += r.output_tokens

        return {
            "run_id": self._run_id,
            "started_at": self._started_at,
            "total_calls": self.total_calls,
            "total_cost": round(self.total_cost, 6),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "cost_budget": self._cost_budget,
            "over_budget": self.is_over_budget(),
            "over_call_limit": self.is_over_call_limit(),
            "per_route": self._cost_tracker.summary()["per_route"],
            "by_task": by_task,
        }
