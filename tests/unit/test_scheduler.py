"""FairScheduler 公平并发调度器测试。"""

from __future__ import annotations

import asyncio

import pytest

from news_sentry.core.scheduler import FairScheduler


class TestFairScheduler:
    """FairScheduler 两级并发控制：per-target 最小保证 + 全局最大上限。"""

    @pytest.mark.asyncio
    async def test_acquire_release_within_min(self) -> None:
        """per_target_min 内的请求应立即获取槽位。"""
        scheduler = FairScheduler(per_target_min=5, global_max=30)
        scheduler.register("italy")

        for _ in range(5):
            await scheduler.acquire("italy")

        for _ in range(5):
            scheduler.release("italy")

    @pytest.mark.asyncio
    async def test_exceed_per_target_blocks_until_release(self) -> None:
        """超过 per_target_min 的请求阻塞，直到有槽位释放。"""
        scheduler = FairScheduler(per_target_min=2, global_max=30)
        scheduler.register("italy")

        await scheduler.acquire("italy")
        await scheduler.acquire("italy")

        acquired = asyncio.Event()

        async def try_acquire() -> None:
            await scheduler.acquire("italy")
            acquired.set()

        task = asyncio.create_task(try_acquire())
        await asyncio.sleep(0.05)
        assert not acquired.is_set()

        scheduler.release("italy")
        await asyncio.sleep(0.05)
        assert acquired.is_set()

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        scheduler.release("italy")

    @pytest.mark.asyncio
    async def test_global_max_limits_total_concurrency(self) -> None:
        """全局信号量限制所有 target 的总并发数。"""
        scheduler = FairScheduler(per_target_min=3, global_max=4)
        scheduler.register("italy")
        scheduler.register("japan")

        await scheduler.acquire("italy")
        await scheduler.acquire("italy")
        await scheduler.acquire("italy")
        await scheduler.acquire("japan")

        scheduler.register("germany")
        acquired = asyncio.Event()

        async def try_acquire_germany() -> None:
            await scheduler.acquire("germany")
            acquired.set()

        task = asyncio.create_task(try_acquire_germany())
        await asyncio.sleep(0.05)
        assert not acquired.is_set()

        scheduler.release("italy")
        await asyncio.sleep(0.05)
        assert acquired.is_set()

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        scheduler.release("germany")

    @pytest.mark.asyncio
    async def test_no_starvation_completed_target_releases_slots(self) -> None:
        """先完成的 target 释放槽位后，其他 target 可以获取全局槽位。"""
        scheduler = FairScheduler(per_target_min=2, global_max=3)
        scheduler.register("italy")
        scheduler.register("japan")

        # italy 占 2 per-target + 2 global
        await scheduler.acquire("italy")
        await scheduler.acquire("italy")
        # japan 占 1 per-target + 1 global (global 满)
        await scheduler.acquire("japan")

        # japan 完成，释放全部
        scheduler.release("japan")

        # italy 释放 1 个，然后 japan 可以重新获取
        scheduler.release("italy")
        await scheduler.acquire("japan")
        scheduler.release("japan")

        # 清理剩余 italy
        scheduler.release("italy")

    @pytest.mark.asyncio
    async def test_register_creates_per_target_semaphore(self) -> None:
        """register() 为每个 target 创建独立的 Semaphore。"""
        scheduler = FairScheduler(per_target_min=5, global_max=30)
        scheduler.register("italy")
        scheduler.register("japan")

        assert "italy" in scheduler.registered_targets
        assert "japan" in scheduler.registered_targets
        assert len(scheduler.registered_targets) == 2

    @pytest.mark.asyncio
    async def test_register_duplicate_raises(self) -> None:
        """重复注册同一 target 应抛出 ValueError。"""
        scheduler = FairScheduler(per_target_min=5, global_max=30)
        scheduler.register("italy")

        with pytest.raises(ValueError, match="已注册"):
            scheduler.register("italy")

    @pytest.mark.asyncio
    async def test_acquire_unregistered_target_raises(self) -> None:
        """未 register 的 target 调用 acquire 应抛出 KeyError。"""
        scheduler = FairScheduler(per_target_min=5, global_max=30)

        with pytest.raises(KeyError, match="unregistered"):
            await scheduler.acquire("nonexistent")

    @pytest.mark.asyncio
    async def test_release_unregistered_target_raises(self) -> None:
        """未 register 的 target 调用 release 应抛出 KeyError。"""
        scheduler = FairScheduler(per_target_min=5, global_max=30)

        with pytest.raises(KeyError, match="unregistered"):
            scheduler.release("nonexistent")

    @pytest.mark.asyncio
    async def test_context_manager_usage(self) -> None:
        """acquire/release 可通过 async context manager 使用。"""
        scheduler = FairScheduler(per_target_min=2, global_max=30)
        scheduler.register("italy")

        async with scheduler.slot("italy"):
            pass

        async with scheduler.slot("italy"):
            pass
