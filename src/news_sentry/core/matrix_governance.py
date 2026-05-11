# src/news_sentry/core/matrix_governance.py
"""信源矩阵自进化治理模块。

管理信源生命周期状态机：
  active → degraded → dead → 归档
"""
from __future__ import annotations

from enum import Enum, auto
from typing import Any


class SourceLifecycle(Enum):
    """信源生命周期状态"""

    ACTIVE = auto()
    DEGRADED = auto()
    DEAD = auto()


class SourceHealth:
    """单个信源的健康状态。"""

    def __init__(
        self,
        source_id: str,
        degraded_after: int = 3,
        dead_after: int = 10,
    ) -> None:
        self.source_id = source_id
        self.state: SourceLifecycle = SourceLifecycle.ACTIVE
        self.consecutive_failures: int = 0
        self.consecutive_successes: int = 0
        self._degraded_after = degraded_after
        self._dead_after = dead_after

    def record_failure(self) -> None:
        """记录一次失败。"""
        self.consecutive_failures += 1
        self.consecutive_successes = 0
        self._recalculate_state()

    def record_success(self) -> None:
        """记录一次成功。"""
        self.consecutive_successes += 1
        self.consecutive_failures = 0
        if self.state == SourceLifecycle.DEGRADED:
            self.state = SourceLifecycle.ACTIVE

    def _recalculate_state(self) -> None:
        """根据连续失败次数重新计算状态。"""
        if self.consecutive_failures >= self._dead_after:
            self.state = SourceLifecycle.DEAD
        elif self.consecutive_failures >= self._degraded_after:
            self.state = SourceLifecycle.DEGRADED

    def to_dict(self) -> dict[str, Any]:
        """序列化为 dict。"""
        return {
            "source_id": self.source_id,
            "state": self.state.name,
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
        }


class MatrixGovernance:
    """信源矩阵治理管理器。

    管理所有信源的生命周期，提供健康审计和退化查询。
    """

    def __init__(self) -> None:
        self._health: dict[str, SourceHealth] = {}

    def get_or_create_health(self, source_id: str) -> SourceHealth:
        """获取或创建信源健康状态。"""
        if source_id not in self._health:
            self._health[source_id] = SourceHealth(source_id)
        return self._health[source_id]

    def get_degraded_sources(self) -> list[str]:
        """返回所有 degraded 的信源 ID。"""
        return [sid for sid, h in self._health.items() if h.state == SourceLifecycle.DEGRADED]

    def get_dead_sources(self) -> list[str]:
        """返回所有 dead 的信源 ID。"""
        return [sid for sid, h in self._health.items() if h.state == SourceLifecycle.DEAD]

    def get_active_sources(self) -> list[str]:
        """返回所有 active 的信源 ID。"""
        return [sid for sid, h in self._health.items() if h.state == SourceLifecycle.ACTIVE]

    def record_result(self, source_id: str, success: bool) -> None:
        """记录采集结果。"""
        health = self.get_or_create_health(source_id)
        if success:
            health.record_success()
        else:
            health.record_failure()

    def audit_summary(self) -> dict[str, Any]:
        """生成健康审计摘要。"""
        return {
            "total": len(self._health),
            "active": len(self.get_active_sources()),
            "degraded": len(self.get_degraded_sources()),
            "dead": len(self.get_dead_sources()),
            "details": [h.to_dict() for h in self._health.values()],
        }
