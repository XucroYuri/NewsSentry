"""Implements: docs/spec/phase-4-tool-skill-registry-opencli.md §3.4

ReviewQueue — 人工检查队列，存储 sandbox violation、auth_required、low_quality
等需要人工介入的条目。存储于 memory/review-queue.yaml。

触发场景：
- SandboxViolationError（见 src/news_sentry/core/sandbox.py）
- OpenCLI 工具返回 exit_code=77（auth_required）
- 低质量/空结果自动降级
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel

ItemType = Literal["sandbox_violation", "auth_required", "low_quality"]


class ReviewQueueItem(BaseModel):
    """人工检查队列条目。

    对应 memory/review-queue.yaml 中的单条记录。
    """

    item_id: str
    created_at: datetime
    item_type: ItemType
    source_run_id: str
    detail: str
    event_id: str | None = None
    resolved: bool = False
    resolved_at: datetime | None = None


class ReviewQueue:
    """人工检查队列：写入 memory/review-queue.yaml。

    每次 bounded run 开始时可查阅未解决项。
    ``SandboxViolationError``、auth_required 退出码、低质量结果
    等需要人工介入的场景，通过 ``enqueue()`` 写入队列。
    """

    _FILENAME = "review-queue.yaml"

    def __init__(self, memory_root: Path) -> None:
        """初始化 ReviewQueue。

        Args:
            memory_root: memory/ 目录路径，不存在则自动创建。
        """
        self._memory_root = Path(memory_root)
        self._memory_root.mkdir(parents=True, exist_ok=True)
        self._file_path = self._memory_root / self._FILENAME

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def enqueue(self, item: ReviewQueueItem) -> None:
        """将条目追加到队列尾部。

        item_id 按 ``rq-{source_run_id}-{seq:03d}`` 格式自动生成，
        基于同一 source_run_id 已有条目数自增。

        Args:
            item: 待入队条目（item_id 会被覆盖为自动生成值）。
        """
        items = self._load()

        # 计算同一 source_run_id 的下一个序号
        existing_seq = [
            int(i["item_id"].rsplit("-", 1)[-1])
            for i in items
            if i.get("source_run_id") == item.source_run_id
            and i["item_id"].startswith(f"rq-{item.source_run_id}-")
        ]
        seq = max(existing_seq) + 1 if existing_seq else 1

        item.item_id = f"rq-{item.source_run_id}-{seq:03d}"
        item.created_at = datetime.now(UTC)

        items.append(item.model_dump(mode="json"))
        self._save(items)

    def get_unresolved(self) -> list[ReviewQueueItem]:
        """返回所有未解决条目。"""
        items = self._load()
        unresolved = [i for i in items if not i.get("resolved", False)]
        return [ReviewQueueItem.model_validate(i) for i in unresolved]

    def resolve(self, item_id: str, note: str = "") -> None:
        """将指定条目标记为已解决。

        Args:
            item_id: 待解决的条目 ID。
            note: 可选的解决备注（当前版本仅记录到 detail 字段）。
        """
        items = self._load()
        for item in items:
            if item.get("item_id") == item_id:
                item["resolved"] = True
                item["resolved_at"] = datetime.now(UTC).isoformat()
                if note:
                    item["detail"] = f"{item.get('detail', '')} | resolved: {note}"
                self._save(items)
                return

        raise KeyError(f"未找到 item_id={item_id}")

    # ------------------------------------------------------------------
    # 内部 YAML I/O
    # ------------------------------------------------------------------

    def _load(self) -> list[dict[str, Any]]:
        """从 memory/review-queue.yaml 加载条目列表。

        文件不存在时返回空列表。
        """
        if not self._file_path.exists():
            return []
        with open(self._file_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict) and "items" in data and isinstance(data["items"], list):
            return data["items"]
        return []

    def _save(self, items: list[dict[str, Any]]) -> None:
        """原子写入 memory/review-queue.yaml。

        先写 .tmp 文件，再 os.replace 到目标，使用 UUID 避免多进程 tmp 冲突。
        """
        target = self._file_path
        tmp = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                {"items": items},
                f,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )
        os.replace(tmp, target)
