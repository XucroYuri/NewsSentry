"""FairScheduler — 多 Target 公平并发调度器。

两级并发控制：
1. per-target Semaphore: 每个目标保证至少 per_target_min 个并发槽位
2. global Semaphore: 所有目标合计不超过 global_max 个并发槽位

先完成的目标释放槽位给其他目标，保证不饥饿。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class FairScheduler:
    """公平并发调度器，基于 asyncio.Semaphore 实现两级并发控制。

    Args:
        per_target_min: 每个 target 保证的最小并发槽位数。
        global_max: 所有 target 合计的最大并发槽位数。
    """

    def __init__(self, per_target_min: int = 5, global_max: int = 30) -> None:
        self._per_target_min = per_target_min
        self._global = asyncio.Semaphore(global_max)
        self._per_target: dict[str, asyncio.Semaphore] = {}

    def register(self, target_id: str) -> None:
        """注册一个 target，为其创建 per-target Semaphore。

        Raises:
            ValueError: target 已注册。
        """
        if target_id in self._per_target:
            raise ValueError(f"target '{target_id}' 已注册")
        self._per_target[target_id] = asyncio.Semaphore(self._per_target_min)

    @property
    def registered_targets(self) -> list[str]:
        """返回已注册的所有 target ID 列表。"""
        return list(self._per_target.keys())

    async def acquire(self, target_id: str) -> None:
        """获取一个并发槽位。先获取 per-target，再获取全局。

        Raises:
            KeyError: target 未注册。
        """
        if target_id not in self._per_target:
            raise KeyError(f"unregistered target: '{target_id}'")
        await self._per_target[target_id].acquire()
        await self._global.acquire()

    def release(self, target_id: str) -> None:
        """释放一个并发槽位。先释放全局，再释放 per-target。

        Raises:
            KeyError: target 未注册。
        """
        if target_id not in self._per_target:
            raise KeyError(f"unregistered target: '{target_id}'")
        self._global.release()
        self._per_target[target_id].release()

    @asynccontextmanager
    async def slot(self, target_id: str) -> AsyncIterator[None]:
        """async context manager 形式获取/释放槽位。"""
        await self.acquire(target_id)
        try:
            yield
        finally:
            self.release(target_id)
