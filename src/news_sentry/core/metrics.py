"""News Sentry — Run metrics collection and persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel


class RunMetrics(BaseModel):
    """一次 bounded run 的指标快照."""

    run_id: str
    target_id: str
    collected: int = 0
    filtered: int = 0
    judged: int = 0
    outputted: int = 0
    duration_collect_ms: int = 0
    duration_filter_ms: int = 0
    duration_judge_ms: int = 0
    duration_output_ms: int = 0
    provider_calls: dict[str, int] = {}
    provider_cost: dict[str, float] = {}
    generated_at: str = ""

    def model_post_init(self, __context: object) -> None:
        if not self.generated_at:
            self.generated_at = datetime.now(UTC).isoformat()


class MetricsWriter:
    """将 RunMetrics 追加写入 JSONL 文件."""

    def __init__(self, memory_dir: Path) -> None:
        self.memory_dir = memory_dir
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def write(self, metrics: RunMetrics) -> Path:
        file_path = self.memory_dir / "metrics.jsonl"
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(metrics.model_dump_json() + "\n")
        return file_path
