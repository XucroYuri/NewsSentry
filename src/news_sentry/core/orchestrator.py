"""News Sentry — Pipeline orchestrator (sequential and concurrent modes)."""

from __future__ import annotations

from enum import Enum

PIPELINE_STAGE_ORDER = ["collect", "filter", "judge", "output", "analyze"]


class OrchestratorMode(str, Enum):
    SEQUENTIAL = "sequential"
    CONCURRENT = "concurrent"


class PipelineOrchestrator:
    """编排 bounded run 的 stage 执行顺序与并行度."""

    def __init__(
        self,
        mode: OrchestratorMode = OrchestratorMode.SEQUENTIAL,
        parallelism: int = 1,
    ) -> None:
        self.mode = mode
        self.parallelism = parallelism
        self.known_stages = set(PIPELINE_STAGE_ORDER)

    def validate_stage_order(self, stages: list[str]) -> bool:
        """验证阶段顺序是否合法（sequential 模式）。"""
        indices = []
        for stage in stages:
            if stage not in self.known_stages:
                return False
            indices.append(PIPELINE_STAGE_ORDER.index(stage))
        return indices == sorted(indices)
