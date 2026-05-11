"""News Sentry — Stage checkpoint for bounded run recovery."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel


class ErrorType(StrEnum):
    TRANSIENT = "transient"  # 网络/限流，自动重试
    DATA = "data"  # 单条 event 异常，跳过
    FATAL = "fatal"  # 配置/schema 错误，停止运行


class StageCheckpoint(BaseModel):
    """单个 stage 的进度快照."""

    stage: str
    cursor: str = ""
    processed_ids: set[str] = set()
    saved_at: str = ""

    def model_post_init(self, __context: object) -> None:
        if not self.saved_at:
            self.saved_at = datetime.now(UTC).isoformat()


class CheckpointManager:
    """管理 stage checkpoint 的持久化与恢复."""

    def __init__(self, memory_dir: Path) -> None:
        self.memory_dir = memory_dir
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, stage: str) -> Path:
        safe_stage = stage.replace("/", "_").replace("..", "_")
        return self.memory_dir / f"checkpoint_{safe_stage}.json"

    def save(self, checkpoint: StageCheckpoint) -> None:
        self._path(checkpoint.stage).write_text(
            checkpoint.model_dump_json(indent=2), encoding="utf-8"
        )

    def load(self, stage: str) -> StageCheckpoint | None:
        path = self._path(stage)
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return StageCheckpoint(**data)
