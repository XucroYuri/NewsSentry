# src/news_sentry/core/matrix_governance.py
"""信源矩阵自进化治理模块。

管理信源生命周期状态机：
  active → degraded → dead → 归档

持久化至 data/{target_id}/memory/matrix-governance.yaml。
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum, auto
from pathlib import Path
from typing import Any

import yaml


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

    # ── 持久化 ─────────────────────────────────────

    def save(self, filepath: Path) -> None:
        """保存当前治理状态到 YAML 文件（原子写入）。

        Args:
            filepath: 目标文件路径（如 data/{target}/memory/matrix-governance.yaml）。
        """
        data: dict[str, Any] = {
            "sources": [h.to_dict() for h in self._health.values()],
            "updated_at": datetime.now(UTC).isoformat(),
        }
        tmp_path = filepath.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False)
        tmp_path.rename(filepath)

    @classmethod
    def load(cls, filepath: Path) -> MatrixGovernance:
        """从 YAML 文件恢复治理状态。

        Args:
            filepath: 源文件路径。

        Returns:
            恢复后的 MatrixGovernance 实例。文件不存在或为空时返回空实例。
        """
        gov = cls()
        if not filepath.exists():
            return gov
        try:
            with open(filepath, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception:
            return gov

        if not isinstance(data, dict):
            return gov

        for src_data in data.get("sources", []):
            if not isinstance(src_data, dict):
                continue
            source_id = src_data.get("source_id")
            if not source_id:
                continue
            health = SourceHealth(source_id)
            health.consecutive_failures = int(src_data.get("consecutive_failures", 0))
            health.consecutive_successes = int(src_data.get("consecutive_successes", 0))
            state_name = src_data.get("state", "ACTIVE")
            try:
                health.state = SourceLifecycle[state_name]
            except KeyError:
                health.state = SourceLifecycle.ACTIVE
            gov._health[source_id] = health

        return gov
