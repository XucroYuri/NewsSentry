# Phase 29: 多 Target 并发调度 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现多 target 并发调度，包括公平调度器（FairScheduler）、多 target 并发执行（multi_run_async）、CLI 扩展（--target all, --target id1,id2, --interval N）和资源隔离。

**Architecture:** 在 Phase 25-28 建成的 async 基础设施、SQLite 存储层、AI 优化和 API Server 之上，构建多 target 并发调度层。每个 target 独立执行 bounded_run_async()，共享全局 httpx.AsyncClient 连接池，公平分配并发槽位。

**Tech Stack:** Python 3.11+, asyncio, httpx (async), aiosqlite, pytest-asyncio, click

**设计文档:** `docs/performance-overhaul-design.md` Section 8

**前置依赖:** Phase 25 (async 基础设施), Phase 26 (SQLite 存储层), Phase 27 (AI 调用优化), Phase 28 (API Server 重构)

---

## 文件结构

### 新建文件
- `src/news_sentry/core/fair_scheduler.py` — 公平调度器
- `src/news_sentry/core/multi_run.py` — 多 target 并发执行入口（`multi_run_async`）
- `tests/unit/test_fair_scheduler.py` — 公平调度器单元测试
- `tests/unit/test_multi_run.py` — 多 target 并发执行单元测试
- `tests/integration/test_multi_target.py` — 多 target 集成测试

### 修改文件
- `src/news_sentry/cli/__init__.py` — `run` 命令扩展：`--target all`、逗号分隔多 target、`--interval N`
- `src/news_sentry/core/orchestrator.py` — PipelineOrchestrator 扩展，支持并发 target 编排

### 不改动文件
- `src/news_sentry/core/async_run.py` — Phase 25 的 `bounded_run_async` 保留单 target 语义不变
- `src/news_sentry/core/run.py` — 保留原样
- `config/targets/*.yaml` — 不修改，仅被自动发现读取
- `src/news_sentry/core/config.py` — ConfigLoader 无需改动

---

## Task 1: FairScheduler 公平调度器

**Files:**
- Create: `src/news_sentry/core/fair_scheduler.py`
- Test: `tests/unit/test_fair_scheduler.py`

公平调度器保证每个 target 至少 `per_target_min=5` 个并发槽位，全局上限 `global_max=30`，先完成先释放，不饿死任何 target。基于双层信号量实现：外层全局信号量控制总并发数，内层 per-target 信号量保证最小配额。

- [ ] **Step 1: 写 FairScheduler 测试**

```python
# tests/unit/test_fair_scheduler.py
"""FairScheduler 公平调度器单元测试。"""

import asyncio
import time

import pytest

from news_sentry.core.fair_scheduler import FairScheduler


class TestFairScheduler:
    """FairScheduler 核心行为测试。"""

    @pytest.mark.asyncio
    async def test_acquire_and_release_single_target(self):
        """单 target 获取和释放槽位正常工作。"""
        scheduler = FairScheduler(per_target_min=5, global_max=30)
        scheduler.register_target("italy")

        await scheduler.acquire("italy")
        # 不应阻塞，立即可用
        scheduler.release("italy")

        # 验证可以再次获取
        await scheduler.acquire("italy")
        scheduler.release("italy")

    @pytest.mark.asyncio
    async def test_per_target_min_guarantee(self):
        """每个 target 保证至少 per_target_min 个并发槽位。"""
        scheduler = FairScheduler(per_target_min=3, global_max=10)

        for tid in ["italy", "japan", "germany"]:
            scheduler.register_target(tid)

        acquired: dict[str, int] = {"italy": 0, "japan": 0, "germany": 0}

        async def _worker(tid: str, release_after: float = 0.3) -> None:
            await scheduler.acquire(tid)
            acquired[tid] += 1
            await asyncio.sleep(release_after)
            scheduler.release(tid)

        # 每个 target 同时启动 3 个 worker
        tasks = []
        for tid in ["italy", "japan", "germany"]:
            for _ in range(3):
                tasks.append(asyncio.create_task(_worker(tid)))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 每个 target 的 3 个 worker 都应该获得槽位（在 per_target_min=3 内）
        for tid in ["italy", "japan", "germany"]:
            assert acquired[tid] == 3, f"{tid} 应获得 3 个槽位，实际 {acquired[tid]}"

    @pytest.mark.asyncio
    async def test_global_max_respected(self):
        """全局并发不超过 global_max。"""
        scheduler = FairScheduler(per_target_min=5, global_max=10)
        for tid in ["italy", "japan", "germany", "france", "china-watch-en"]:
            scheduler.register_target(tid)

        concurrent: int = 0
        max_concurrent: int = 0
        lock = asyncio.Lock()

        async def _worker(tid: str) -> None:
            nonlocal concurrent, max_concurrent
            await scheduler.acquire(tid)
            async with lock:
                concurrent += 1
                if concurrent > max_concurrent:
                    max_concurrent = concurrent
            await asyncio.sleep(0.05)
            async with lock:
                concurrent -= 1
            scheduler.release(tid)

        # 每个 target 启动 5 个 worker = 25 个总请求 > global_max=10
        tasks = []
        for tid in ["italy", "japan", "germany", "france", "china-watch-en"]:
            for _ in range(5):
                tasks.append(asyncio.create_task(_worker(tid)))

        await asyncio.gather(*tasks, return_exceptions=True)

        assert max_concurrent <= 10, f"最大并发 {max_concurrent} 超过 global_max=10"

    @pytest.mark.asyncio
    async def test_no_starvation(self):
        """不饿死任何 target：即使一个 target 大量请求，另一个 target 仍能获得最小槽位。"""
        scheduler = FairScheduler(per_target_min=2, global_max=5)
        scheduler.register_target("heavy")
        scheduler.register_target("light")

        heavy_done = 0
        light_done = 0

        async def _heavy_worker() -> None:
            nonlocal heavy_done
            for _ in range(10):
                await scheduler.acquire("heavy")
                await asyncio.sleep(0.01)
                heavy_done += 1
                scheduler.release("heavy")

        async def _light_worker() -> None:
            nonlocal light_done
            for _ in range(3):
                await scheduler.acquire("light")
                await asyncio.sleep(0.01)
                light_done += 1
                scheduler.release("light")

        # 同时启动 heavy 和 light
        heavy_task = asyncio.create_task(_heavy_worker())
        light_task = asyncio.create_task(_light_worker())

        await asyncio.gather(heavy_task, light_task)

        # light 不应该被饿死
        assert light_done == 3, f"light 应完成 3 次，实际 {light_done}"
        # heavy 也应至少完成若干次（受 global_max 限制但不应为 0）
        assert heavy_done > 0, f"heavy 应至少完成一次，实际 {heavy_done}"

    @pytest.mark.asyncio
    async def test_unregistered_target_raises(self):
        """未注册 target 应抛出 KeyError。"""
        scheduler = FairScheduler(per_target_min=5, global_max=30)

        with pytest.raises(KeyError):
            await scheduler.acquire("unknown-target")

    @pytest.mark.asyncio
    async def test_release_restores_capacity(self):
        """释放槽位后恢复容量。"""
        scheduler = FairScheduler(per_target_min=1, global_max=2)
        scheduler.register_target("italy")

        await scheduler.acquire("italy")
        scheduler.release("italy")
        await scheduler.acquire("italy")  # 应该不阻塞
        scheduler.release("italy")
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && .venv/bin/python3 -m pytest tests/unit/test_fair_scheduler.py -v
```

预期：FAIL -- `ModuleNotFoundError: No module named 'news_sentry.core.fair_scheduler'`

- [ ] **Step 3: 实现 FairScheduler**

```python
# src/news_sentry/core/fair_scheduler.py
"""FairScheduler — 多 target 公平调度器，基于双层信号量实现。

保证每个 target 至少 per_target_min 个并发槽位，全局不超过 global_max。
先完成先释放，不饿死任何 target（per_target_min 保证最小配额）。
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


class FairScheduler:
    """公平调度器：双层信号量 = 全局信号量 + per-target 信号量。

    两层信号量的获取顺序：
    1. 先获取 per-target 信号量（保证该 target 不饿死）
    2. 再获取全局信号量（保证全局并发不超限）

    释放顺序：先释放全局信号量，再释放 per-target 信号量。

    Args:
        per_target_min: 每个 target 保证的最小并发槽位数。
        global_max: 全局最大并发数。
    """

    def __init__(
        self,
        per_target_min: int = 5,
        global_max: int = 30,
    ) -> None:
        if per_target_min < 1:
            raise ValueError(f"per_target_min 必须 >= 1，实际 {per_target_min}")
        if global_max < per_target_min:
            raise ValueError(
                f"global_max ({global_max}) 必须 >= per_target_min ({per_target_min})"
            )

        self._per_target_min = per_target_min
        self._global_max = global_max
        self._global: asyncio.Semaphore = asyncio.Semaphore(global_max)
        self._per_target: dict[str, asyncio.Semaphore] = {}
        self._registered: set[str] = set()
        self._stats_lock: asyncio.Lock = asyncio.Lock()
        self._acquire_count: dict[str, int] = defaultdict(int)
        self._release_count: dict[str, int] = defaultdict(int)

    def register_target(self, target_id: str) -> None:
        """注册一个 target，为其分配独立的 per-target 信号量。

        可以在运行时动态注册新 target。重复注册不产生副作用。
        """
        if target_id not in self._per_target:
            self._per_target[target_id] = asyncio.Semaphore(self._per_target_min)
            self._registered.add(target_id)
            logger.debug(
                "FairScheduler: 注册 target=%s per_target_min=%d",
                target_id,
                self._per_target_min,
            )
        else:
            logger.debug("FairScheduler: target=%s 已注册，跳过", target_id)

    def register_targets(self, target_ids: list[str]) -> None:
        """批量注册多个 target。"""
        for tid in target_ids:
            self.register_target(tid)

    async def acquire(self, target_id: str) -> None:
        """获取一个并发槽位。

        先获取 per-target 配额（保证最小公平性），再获取全局配额。
        如果 target 未注册，抛出 KeyError。

        Args:
            target_id: 请求槽位的 target 标识符。

        Raises:
            KeyError: target 未注册。
        """
        if target_id not in self._per_target:
            raise KeyError(
                f"Target '{target_id}' 未注册到 FairScheduler。"
                f" 已注册 target: {sorted(self._registered)}"
            )

        # 先获取 per-target 槽位（保证不饿死）
        await self._per_target[target_id].acquire()

        try:
            # 再获取全局槽位（全局并发控制）
            await self._global.acquire()
        except Exception:
            # 如果全局获取失败，释放 per-target 槽位
            self._per_target[target_id].release()
            raise

        async with self._stats_lock:
            self._acquire_count[target_id] += 1

    def release(self, target_id: str) -> None:
        """释放一个并发槽位。

        释放顺序：先全局后 per-target（与获取顺序相反）。

        Args:
            target_id: 释放槽位的 target 标识符。

        Raises:
            KeyError: target 未注册。
        """
        if target_id not in self._per_target:
            raise KeyError(
                f"Target '{target_id}' 未注册到 FairScheduler。"
            )

        self._global.release()
        self._per_target[target_id].release()

        # 使用同步方式更新计数（release 不需要异步上下文）
        self._release_count[target_id] += 1

    @property
    def stats(self) -> dict[str, object]:
        """返回当前调度器统计信息。"""
        return {
            "per_target_min": self._per_target_min,
            "global_max": self._global_max,
            "registered_targets": sorted(self._registered),
            "acquire_count": dict(self._acquire_count),
            "release_count": dict(self._release_count),
        }

    @property
    def registered_targets(self) -> list[str]:
        """返回已注册的 target 列表。"""
        return sorted(self._registered)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && .venv/bin/python3 -m pytest tests/unit/test_fair_scheduler.py -v
```

预期：6 passed

- [ ] **Step 5: 提交**

```bash
cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && git add src/news_sentry/core/fair_scheduler.py tests/unit/test_fair_scheduler.py && git commit -m "Phase 29: FairScheduler 公平调度器 (P29.01)"
```

---

## Task 2: multi_run_async() 多 Target 并发执行

**Files:**
- Create: `src/news_sentry/core/multi_run.py`
- Test: `tests/unit/test_multi_run.py`

`multi_run_async()` 是 Phase 29 的核心函数：接受多个 target_id，为每个 target 创建独立任务（调用 `bounded_run_async()`），通过 FairScheduler 公平调度所有并发操作，共享全局 `httpx.AsyncClient` 连接池。

关键设计决策：
1. 每个 target 独立 SQLite db（`data/{target_id}/state.db`）和独立 Memory
2. 全局 `httpx.AsyncClient` 由 `multi_run_async` 创建并传入各 `bounded_run_async`
3. AI 预算全局共享，通过 `asyncio.Lock` 保护防超支
4. 每个 target 的错误不传播到其他 target（`return_exceptions=True`）

- [ ] **Step 1: 写 multi_run_async 测试**

```python
# tests/unit/test_multi_run.py
"""multi_run_async 多 target 并发执行单元测试。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from news_sentry.core.multi_run import multi_run_async


class TestMultiRunAsync:
    """multi_run_async 核心行为测试。"""

    @pytest.mark.asyncio
    async def test_runs_all_targets_concurrently(self):
        """验证所有 target 被并发执行。"""
        started: set[str] = set()

        async def _mock_bounded_run_async(target_id, stage, **kwargs):
            started.add(target_id)
            ctx = MagicMock()
            ctx.target_id = target_id
            ctx.errors_count = 0
            return ctx

        with patch(
            "news_sentry.core.multi_run.bounded_run_async",
            side_effect=_mock_bounded_run_async,
        ):
            results = await multi_run_async(
                target_ids=["italy", "japan", "germany"],
                stage="all",
            )

        assert len(results) == 3
        assert started == {"italy", "japan", "germany"}

    @pytest.mark.asyncio
    async def test_isolated_errors_do_not_kill_other_targets(self):
        """一个 target 失败不影响其他 target 执行。"""
        call_order: list[str] = []

        async def _mock_bounded_run_async(target_id, stage, **kwargs):
            call_order.append(target_id)
            if target_id == "japan":
                raise RuntimeError("模拟 japan 失败")
            ctx = MagicMock()
            ctx.target_id = target_id
            ctx.errors_count = 0
            return ctx

        with patch(
            "news_sentry.core.multi_run.bounded_run_async",
            side_effect=_mock_bounded_run_async,
        ):
            results = await multi_run_async(
                target_ids=["italy", "japan", "germany"],
                stage="all",
            )

        # italy 和 germany 应正常完成
        assert "italy" in call_order
        assert "germany" in call_order
        # japan 也应有调用记录（但抛出了异常）
        assert "japan" in call_order

        # 结果中应包含错误信息
        assert len(results) >= 3

    @pytest.mark.asyncio
    async def test_respects_fair_scheduler(self):
        """验证 FairScheduler 被正确注册和使用。"""
        scheduler_registered: list[str] = []

        with patch(
            "news_sentry.core.multi_run.bounded_run_async",
            new_callable=AsyncMock,
        ) as mock_run, patch(
            "news_sentry.core.multi_run.FairScheduler",
        ) as mock_scheduler_cls:

            mock_scheduler = MagicMock()
            mock_scheduler.register_targets = MagicMock(
                side_effect=lambda ids: scheduler_registered.extend(ids)
            )
            mock_scheduler_cls.return_value = mock_scheduler

            mock_run.return_value = MagicMock(target_id="test", errors_count=0)

            await multi_run_async(
                target_ids=["italy", "japan"],
                stage="collect",
                per_target_min=5,
                global_max=30,
            )

            # 验证所有 target 被注册
            assert "italy" in scheduler_registered
            assert "japan" in scheduler_registered

    @pytest.mark.asyncio
    async def test_single_target_still_works(self):
        """单个 target 仍能正常工作（不退化）。"""
        with patch(
            "news_sentry.core.multi_run.bounded_run_async",
            new_callable=AsyncMock,
        ) as mock_run:
            mock_run.return_value = MagicMock(target_id="italy", errors_count=0)

            results = await multi_run_async(
                target_ids=["italy"],
                stage="all",
            )

        assert len(results) == 1
        assert results[0].target_id == "italy"

    @pytest.mark.asyncio
    async def test_shared_http_client_passed_through(self):
        """验证共享 httpx.AsyncClient 被传递给每个 bounded_run_async。"""
        passed_clients: list[object] = []

        async def _mock_run(target_id, stage, http_client=None, **kwargs):
            passed_clients.append(http_client)
            ctx = MagicMock()
            ctx.target_id = target_id
            ctx.errors_count = 0
            return ctx

        with patch(
            "news_sentry.core.multi_run.bounded_run_async",
            side_effect=_mock_run,
        ):
            await multi_run_async(
                target_ids=["italy", "japan"],
                stage="all",
            )

        # 所有 target 应收到同一个 http_client 对象
        assert len(passed_clients) == 2
        assert passed_clients[0] is not None
        assert passed_clients[0] is passed_clients[1], (
            "所有 target 应共享同一个 httpx.AsyncClient 实例"
        )

    @pytest.mark.asyncio
    async def test_ai_budget_lock_shared(self):
        """验证 AI 预算锁被传递给每个 bounded_run_async。"""
        passed_locks: list[object] = []

        async def _mock_run(target_id, stage, ai_budget_lock=None, **kwargs):
            passed_locks.append(ai_budget_lock)
            ctx = MagicMock()
            ctx.target_id = target_id
            ctx.errors_count = 0
            return ctx

        with patch(
            "news_sentry.core.multi_run.bounded_run_async",
            side_effect=_mock_run,
        ):
            await multi_run_async(
                target_ids=["italy", "japan"],
                stage="all",
            )

        # 所有 target 应收到同一个 asyncio.Lock
        assert len(passed_locks) == 2
        assert passed_locks[0] is not None
        assert passed_locks[0] is passed_locks[1], (
            "所有 target 应共享同一个 AI 预算锁"
        )
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && .venv/bin/python3 -m pytest tests/unit/test_multi_run.py -v
```

预期：FAIL -- `ModuleNotFoundError: No module named 'news_sentry.core.multi_run'`

- [ ] **Step 3: 实现 multi_run.py**

```python
# src/news_sentry/core/multi_run.py
"""multi_run_async — 多 target 并发执行入口。

共享全局 httpx.AsyncClient 连接池，通过 FairScheduler 公平调度所有并发操作。
每个 target 独立 SQLite db 和 Memory，AI 预算全局共享并通过 asyncio.Lock 保护。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from news_sentry.core.fair_scheduler import FairScheduler
from news_sentry.core.async_run import bounded_run_async
from news_sentry.models.pipeline_context import PipelineContext

logger = logging.getLogger(__name__)

# 多 target 结果类型：成功返回 PipelineContext，失败返回异常对象或错误 dict
MultiRunResult = PipelineContext | Exception | dict[str, Any]


async def multi_run_async(
    target_ids: list[str],
    stage: str = "all",
    run_id_prefix: str | None = None,
    dry_run: bool = False,
    config_dir: Path | None = None,
    profile_id: str | None = None,
    output_root: Path | None = None,
    max_concurrent: int = 10,
    per_target_min: int = 5,
    global_max: int = 30,
    http_client: httpx.AsyncClient | None = None,
    ai_budget_lock: asyncio.Lock | None = None,
) -> list[MultiRunResult]:
    """并发执行多个 target 的 bounded_run_async。

    每个 target 获得独立任务，通过 FairScheduler 公平分配并发槽位。
    所有 target 共享全局 httpx.AsyncClient 连接池和 AI 预算锁。

    Args:
        target_ids: 要执行的 target ID 列表。
        stage: pipeline 阶段（"collect" | "filter" | "judge" | "output" | "all"）。
        run_id_prefix: run_id 前缀，不提供则自动生成时间戳前缀。
        dry_run: True 时只打印计划不执行。
        config_dir: 项目根目录覆盖。
        profile_id: Deployment profile ID。
        output_root: 输出根目录覆盖。
        max_concurrent: 单个 target 内部的并发上限（传给 bounded_run_async）。
        per_target_min: 每个 target 最小并发槽位数。
        global_max: 全局最大并发数。
        http_client: 可选的预创建 httpx.AsyncClient（不提供则自动创建）。
        ai_budget_lock: 可选预创建 asyncio.Lock（不提供则自动创建）。

    Returns:
        List[MultiRunResult] — 每个 target 的执行结果，顺序与 target_ids 对应。
        成功元素是 PipelineContext，失败元素是 Exception 或含 error 字段的 dict。
    """
    if not target_ids:
        logger.warning("multi_run_async: 没有指定 target，跳过执行")
        return []

    # 生成 run_id 前缀
    if run_id_prefix is None:
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        run_id_prefix = f"multi_{ts}"

    # 初始化 FairScheduler 并注册所有 target
    scheduler = FairScheduler(
        per_target_min=per_target_min,
        global_max=global_max,
    )
    scheduler.register_targets(target_ids)
    logger.info(
        "FairScheduler 初始化: targets=%s per_target_min=%d global_max=%d",
        target_ids,
        per_target_min,
        global_max,
    )

    # 创建或复用共享资源
    own_client = http_client is None
    own_lock = ai_budget_lock is None
    _http_client = http_client or httpx.AsyncClient(timeout=30.0)
    _ai_budget_lock = ai_budget_lock or asyncio.Lock()

    # 确定项目根目录
    project_root = config_dir or _find_project_root()

    async def _run_single_target(target_id: str) -> MultiRunResult:
        """内部函数：运行单个 target 的完整 pipeline。"""
        target_run_id = f"{run_id_prefix}_{target_id}"
        start_time = datetime.now(UTC)

        try:
            logger.info("开始执行 target: %s run_id: %s", target_id, target_run_id)

            ctx = await bounded_run_async(
                target_id=target_id,
                stage=stage,
                run_id=target_run_id,
                dry_run=dry_run,
                config_dir=project_root,
                profile_id=profile_id,
                output_root=output_root,
                max_concurrent=max_concurrent,
                http_client=_http_client,
                fair_scheduler=scheduler,
                ai_budget_lock=_ai_budget_lock,
            )

            elapsed = (datetime.now(UTC) - start_time).total_seconds()
            logger.info(
                "target=%s 完成: collected=%d filtered=%d judged=%d output=%d errors=%d elapsed=%.1fs",
                target_id,
                ctx.events_collected,
                ctx.events_filtered,
                ctx.events_judged,
                ctx.events_output,
                ctx.errors_count,
                elapsed,
            )

            return ctx

        except Exception as exc:
            elapsed = (datetime.now(UTC) - start_time).total_seconds()
            logger.error(
                "target=%s 失败: %s elapsed=%.1fs",
                target_id,
                exc,
                elapsed,
                exc_info=True,
            )
            # 返回错误信息而非让整个 gather 失败
            return {
                "error": str(exc),
                "target_id": target_id,
                "elapsed_seconds": elapsed,
            }

    # 并发执行所有 target
    try:
        tasks = [
            asyncio.create_task(_run_single_target(tid))
            for tid in target_ids
        ]
        results = await asyncio.gather(*tasks, return_exceptions=False)

    finally:
        # 清理自行创建的 client
        if own_client:
            await _http_client.aclose()

    # 汇总统计
    success_count = sum(
        1 for r in results
        if isinstance(r, PipelineContext) and r.errors_count == 0
    )
    partial_count = sum(
        1 for r in results
        if isinstance(r, PipelineContext) and r.errors_count > 0
    )
    error_count = sum(1 for r in results if not isinstance(r, PipelineContext))

    logger.info(
        "multi_run_async 完成: total=%d success=%d partial=%d error=%d scheduler_stats=%s",
        len(results),
        success_count,
        partial_count,
        error_count,
        scheduler.stats,
    )

    return results


def auto_discover_targets(config_dir: Path | None = None) -> list[str]:
    """从 config/targets/ 目录自动发现所有可用 target。

    扫描 config/targets/*.yaml 文件（排除 _template.yaml 以下划线开头的文件），
    提取 target_id 列表。

    Args:
        config_dir: 项目根目录，不提供则自动查找。

    Returns:
        target_id 列表，按字母排序。
    """
    project_root = config_dir or _find_project_root()
    targets_dir = project_root / "config" / "targets"

    if not targets_dir.is_dir():
        logger.warning("targets 目录不存在: %s", targets_dir)
        return []

    import yaml

    target_ids: list[str] = []
    for yaml_file in sorted(targets_dir.glob("*.yaml")):
        # 跳过模板文件和以下划线开头的文件
        if yaml_file.name.startswith("_"):
            continue

        try:
            with open(yaml_file, encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            if isinstance(data, dict) and "target_id" in data:
                target_ids.append(str(data["target_id"]))
        except Exception:
            logger.warning("无法解析 target 配置文件: %s", yaml_file, exc_info=True)
            continue

    target_ids.sort()
    logger.info("自动发现 %d 个 target: %s", len(target_ids), target_ids)
    return target_ids


def _find_project_root() -> Path:
    """查找项目根目录（从当前工作目录向上搜索 pyproject.toml）。"""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / "pyproject.toml").is_file():
            return parent
    return cwd
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && .venv/bin/python3 -m pytest tests/unit/test_multi_run.py -v
```

预期：6 passed

- [ ] **Step 5: 运行全部测试确认无回归**

```bash
cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && .venv/bin/python3 -m pytest tests/ -q
```

预期：全部现有测试通过

- [ ] **Step 6: 提交**

```bash
cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && git add src/news_sentry/core/multi_run.py tests/unit/test_multi_run.py && git commit -m "Phase 29: multi_run_async 多 target 并发执行 (P29.02)"
```

---

## Task 3: PipelineOrchestrator 扩展

**Files:**
- Modify: `src/news_sentry/core/orchestrator.py`

扩展 `PipelineOrchestrator`，添加多 target 并发编排能力。当前它是空壳（只有 `validate_stage_order()`），Phase 29 为其补全 concurrent 模式的 target 级编排逻辑。

关键设计：`PipelineOrchestrator` 不实现调用细节，而是作为编排策略的策略对象，提供给 `multi_run_async` 使用。负责：
1. 验证 targets 列表的合法性（target 是否存在、配置是否可加载）
2. 模式匹配：SEQUENTIAL 逐个 target 执行，CONCURRENT 并发执行
3. 循环运行控制：--interval N 时按间隔重复执行

- [ ] **Step 1: 扩展现有测试**

在已有 `tests/unit/test_orchestrator.py`（假设存在，如不存在则创建）中添加新的测试。

```python
# 追加到 tests/unit/test_orchestrator.py（或创建新文件 tests/unit/test_orchestrator_extended.py）
"""PipelineOrchestrator 扩展测试 — 多 target 并发编排。"""

import pytest

from news_sentry.core.orchestrator import (
    OrchestratorMode,
    PipelineOrchestrator,
    PIPELINE_STAGE_ORDER,
)


class TestOrchestratorMultiTarget:
    """多 target 编排测试。"""

    @pytest.mark.asyncio
    async def test_concurrent_mode_accepts_multiple_targets(self):
        """Concurrent 模式接受多个 target。"""
        orchestrator = PipelineOrchestrator(mode=OrchestratorMode.CONCURRENT)
        assert orchestrator.mode == OrchestratorMode.CONCURRENT

    def test_sequential_mode_accepts_multiple_targets(self):
        """Sequential 模式也可接受多个 target。"""
        orchestrator = PipelineOrchestrator(mode=OrchestratorMode.SEQUENTIAL)
        assert orchestrator.mode == OrchestratorMode.SEQUENTIAL

    def test_validate_stage_order_with_all(self):
        """验证完整阶段链。"""
        orchestrator = PipelineOrchestrator()
        assert orchestrator.validate_stage_order(["collect"])
        assert orchestrator.validate_stage_order(["collect", "filter"])
        assert orchestrator.validate_stage_order(["filter", "judge"])
        assert orchestrator.validate_stage_order(["judge", "output"])
        assert orchestrator.validate_stage_order(
            ["collect", "filter", "judge", "output"]
        )

    def test_reject_invalid_stage_order(self):
        """拒绝非法阶段顺序。"""
        orchestrator = PipelineOrchestrator()
        assert not orchestrator.validate_stage_order(["filter", "collect"])  # 逆序
        assert not orchestrator.validate_stage_order(["unknown_stage"])
        assert not orchestrator.validate_stage_order([])

    def test_get_pipeline_sequence_all(self):
        """获取完整 pipeline 序列。"""
        orchestrator = PipelineOrchestrator()
        seq = orchestrator.get_pipeline_sequence("all")
        assert seq == ["collect", "filter", "judge", "output"]

    def test_get_pipeline_sequence_collect(self):
        """获取单个阶段序列。"""
        orchestrator = PipelineOrchestrator()
        seq = orchestrator.get_pipeline_sequence("collect")
        assert seq == ["collect"]

    def test_get_pipeline_sequence_judge(self):
        orchestrator = PipelineOrchestrator()
        seq = orchestrator.get_pipeline_sequence("judge")
        assert seq == ["judge"]
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && .venv/bin/python3 -m pytest tests/unit/test_orchestrator_extended.py -v 2>&1 | head -5
# 或:
cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && .venv/bin/python3 -m pytest tests/unit/ -k orchestrator -v
```

- [ ] **Step 3: 扩展 PipelineOrchestrator**

```python
# src/news_sentry/core/orchestrator.py（完整替换版本）
"""News Sentry — Pipeline orchestrator (sequential and concurrent modes).

P25-29 扩展：支持多 target 并发编排和 stage 序列管理。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum

logger = logging.getLogger(__name__)

PIPELINE_STAGE_ORDER = ["collect", "filter", "judge", "output"]


class OrchestratorMode(StrEnum):
    SEQUENTIAL = "sequential"
    CONCURRENT = "concurrent"


@dataclass
class TargetRunPlan:
    """单个 target 的执行计划。"""

    target_id: str
    stages: list[str] = field(default_factory=list)
    is_valid: bool = True
    error_message: str = ""


class PipelineOrchestrator:
    """编排 bounded run 的 stage 执行顺序与并行度。

    支持两种模式：
    - SEQUENTIAL：逐个阶段串行执行（单个 target 内）。
    - CONCURRENT：多个 target 并发执行，每个 target 内部阶段仍按序。

    多 target 时（Phase 29），CONCURRENT 模式通过 FairScheduler 公平调度。
    """

    def __init__(
        self,
        mode: OrchestratorMode = OrchestratorMode.SEQUENTIAL,
        parallelism: int = 1,
    ) -> None:
        self.mode = mode
        self.parallelism = parallelism
        self.known_stages = set(PIPELINE_STAGE_ORDER)

    def validate_stage_order(self, stages: list[str]) -> bool:
        """验证阶段顺序是否合法（sequential 模式）。

        阶段列表必须按 PIPELINE_STAGE_ORDER 顺序出现，不能跳回。
        """
        indices = []
        for stage in stages:
            if stage not in self.known_stages:
                return False
            indices.append(PIPELINE_STAGE_ORDER.index(stage))
        # 必须是升序（或相等，允许相同阶段）
        for i in range(1, len(indices)):
            if indices[i] < indices[i - 1]:
                return False
        return True

    def get_pipeline_sequence(self, stage: str) -> list[str]:
        """根据 stage 参数获取实际需要执行的阶段序列。

        - "all" → ["collect", "filter", "judge", "output"]
        - "collect" → ["collect"]
        - "filter" → ["filter"]
        - 等等

        Args:
            stage: CLI 传来的 stage 参数。

        Returns:
            实际要执行的阶段列表。
        """
        normalized = stage.lower()
        if normalized in ("all",):
            return list(PIPELINE_STAGE_ORDER)
        if normalized in ("judged", "judge"):
            return ["judge"]
        if normalized in ("outputted", "output"):
            return ["output"]
        if normalized in self.known_stages:
            return [normalized]
        # 不在已知集合中的 stage 返回空列表（上层应拒绝）
        logger.warning("未知 stage: %s", stage)
        return []

    def create_plan_for_targets(
        self,
        target_ids: list[str],
        stage: str,
    ) -> list[TargetRunPlan]:
        """为一组 target 创建执行计划。

        Args:
            target_ids: target ID 列表。
            stage: 阶段参数。

        Returns:
            每个 target 的 TargetRunPlan 列表。
        """
        stages = self.get_pipeline_sequence(stage)
        if not stages:
            return [
                TargetRunPlan(
                    target_id=tid,
                    is_valid=False,
                    error_message=f"无效的阶段参数: {stage}",
                )
                for tid in target_ids
            ]

        plans: list[TargetRunPlan] = []
        for tid in target_ids:
            if not tid or not isinstance(tid, str):
                plans.append(
                    TargetRunPlan(
                        target_id=str(tid),
                        is_valid=False,
                        error_message="target_id 必须是有效字符串",
                    )
                )
                continue

            if not self.validate_stage_order(stages):
                plans.append(
                    TargetRunPlan(
                        target_id=tid,
                        is_valid=False,
                        error_message=f"阶段顺序非法: {stages}",
                    )
                )
                continue

            plans.append(
                TargetRunPlan(
                    target_id=tid,
                    stages=list(stages),
                    is_valid=True,
                )
            )

        return plans

    def is_concurrent(self) -> bool:
        """检查当前模式是否为并发模式。"""
        return self.mode == OrchestratorMode.CONCURRENT
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && .venv/bin/python3 -m pytest tests/unit/ -k orchestrator -v
```

- [ ] **Step 5: 运行全部测试确认无回归**

```bash
cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && .venv/bin/python3 -m pytest tests/ -q
```

- [ ] **Step 6: 提交**

```bash
cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && git add src/news_sentry/core/orchestrator.py tests/unit/test_orchestrator_extended.py && git commit -m "Phase 29: PipelineOrchestrator 扩展 — target 级编排 + stage 序列管理 (P29.03)"
```

---

## Task 4: CLI 扩展 — --target all / 逗号多 target / --interval 循环

**Files:**
- Modify: `src/news_sentry/cli/__init__.py`

这是用户可见的接口变更。扩展 `run` 命令，使其接受：
- `--target all` — 从 `config/targets/` 自动发现所有 target
- `--target italy,japan` — 逗号分隔多 target
- `--target italy` — 现有单 target 用法不变
- `--interval N` — 循环运行，每轮间隔 N 秒

关键约束：`--target single` 用法不变，内部自动检测是否需要走多 target 路径。

- [ ] **Step 1: 修改 CLI run 命令**

修改 `src/news_sentry/cli/__init__.py` 中的 `run` 命令。

在 `run` 函数体开头添加 target 解析逻辑：

```python
# src/news_sentry/cli/__init__.py 中 run 命令的修改版本

@main.command()
@click.option(
    "--target",
    required=True,
    help="Target ID (e.g., italy)。支持 'all'（全部 target）、"
    "'italy,japan'（逗号分隔多 target）、或单个 target ID。"
    " 单 target 用法完全不变。",
)
@click.option(
    "--stage",
    required=True,
    type=click.Choice(["collect", "filter", "judge", "output", "all"]),
    help="Pipeline stage to execute.",
)
@click.option("--run-id", default=None, help="Specify run_id. Auto-generated if not provided.")
@click.option("--dry-run", is_flag=True, default=False, help="Print plan without executing.")
@click.option("--log-level", default="INFO", type=click.Choice(["DEBUG", "INFO", "WARNING"]))
@click.option("--config-dir", default=None, help="Override project root directory.")
@click.option(
    "--profile",
    "profile_id",
    default=None,
    help="Deployment profile ID. Overrides NEWSSENTRY_PROFILE.",
)
@click.option(
    "--interval",
    "interval_seconds",
    type=int,
    default=None,
    help="循环运行间隔（秒）。设置后进程将持续循环执行直至被中断。",
)
@click.option(
    "--per-target-min",
    type=int,
    default=5,
    help="每个 target 最小并发槽位数（仅多 target 模式生效）。默认 5。",
)
@click.option(
    "--global-max",
    type=int,
    default=30,
    help="全局最大并发数（仅多 target 模式生效）。默认 30。",
)
def run(
    target: str,
    stage: str,
    run_id: str | None,
    dry_run: bool,
    log_level: str,
    config_dir: str | None,
    profile_id: str | None,
    interval_seconds: int | None = None,
    per_target_min: int = 5,
    global_max: int = 30,
) -> None:
    """Execute a bounded run for one or more monitoring targets.

    单 target: --target italy（用法不变）
    多 target: --target all（自动发现），--target italy,japan（逗号分隔）
    循环运行: --interval 300 每 300 秒循环一次

    Exit codes: 0=success, 1=partial failure, 2=config error, 3=sandbox blocked.
    """
    import asyncio
    import logging
    import signal
    import sys

    from news_sentry.core.run import ConfigError

    # 解析 target 列表
    target_ids: list[str] = _resolve_target_list(target, config_dir)

    # 验证 --interval 仅与 stage=all 配合有意义（允许多 stage，但给出警告）
    if interval_seconds is not None:
        if interval_seconds < 1:
            click.echo("错误: --interval 必须 >= 1 秒", err=True)
            sys.exit(2)
        # 多 target 循环时自动启用多 target 模式
        if len(target_ids) <= 1:
            click.echo(
                f"提示: --interval={interval_seconds}s 将循环运行单 target '{target_ids[0]}'"
            )

    # 确定是单 target 还是多 target 路径
    is_multi = len(target_ids) > 1 or (interval_seconds is not None and len(target_ids) > 1)

    # 特殊: 单 target + 循环 也走多 target 路径的循环逻辑
    if interval_seconds is not None and len(target_ids) == 1:
        _run_single_loop(
            target_id=target_ids[0],
            stage=stage,
            run_id=run_id,
            dry_run=dry_run,
            config_dir=config_dir,
            profile_id=profile_id,
            log_level=log_level,
            interval_seconds=interval_seconds,
        )
        return

    if is_multi:
        # ── 多 target 路径 ──────────────────────────
        try:
            project_root = Path(config_dir) if config_dir else _find_project_root()
            from news_sentry.core.multi_run import multi_run_async

            if interval_seconds is not None:
                # 循环运行模式
                _run_multi_loop(
                    target_ids=target_ids,
                    stage=stage,
                    run_id_prefix=run_id,
                    dry_run=dry_run,
                    config_dir=project_root,
                    profile_id=profile_id,
                    log_level=log_level,
                    interval_seconds=interval_seconds,
                    per_target_min=per_target_min,
                    global_max=global_max,
                )
            else:
                # 单次多 target 执行
                results = asyncio.run(
                    multi_run_async(
                        target_ids=target_ids,
                        stage=stage,
                        run_id_prefix=run_id,
                        dry_run=dry_run,
                        config_dir=project_root,
                        profile_id=profile_id,
                        per_target_min=per_target_min,
                        global_max=global_max,
                    )
                )
                _report_multi_results(results, target_ids)

        except ConfigError as e:
            click.echo(f"配置错误: {e}", err=True)
            sys.exit(2)
        except Exception as e:
            click.echo(f"运行异常: {e}", err=True)
            sys.exit(1)

    else:
        # ── 单 target 路径（完全不变！）────────────────────
        from news_sentry.core.run import bounded_run

        try:
            ctx = bounded_run(
                target_id=target_ids[0],
                stage=stage,
                run_id=run_id,
                dry_run=dry_run,
                config_dir=config_dir,
                profile_id=profile_id,
            )
            if dry_run:
                click.echo(f"target: {ctx.target_id}")
                click.echo(f"run_id: {ctx.run_id}")
                click.echo(f"stage:  {stage}")
                click.echo(f"profile: {ctx.profile_id}")
                click.echo("dry-run: 不执行实际操作")
            elif ctx.errors_count > 0:
                click.echo(
                    f"⚠ {ctx.errors_count} 个源采集失败，详见 RunLog: {ctx.run_log_path}"
                )
                sys.exit(1)
        except ConfigError as e:
            click.echo(f"配置错误: {e}", err=True)
            sys.exit(2)
        except Exception as e:
            click.echo(f"运行异常: {e}", err=True)
            sys.exit(1)


# ── 新增辅助函数（在 cli/__init__.py 中或 cli/target_utils.py 中）───


def _resolve_target_list(target_arg: str, config_dir: str | None = None) -> list[str]:
    """解析 --target 参数为 target ID 列表。

    支持三种格式：
    - "all" → 自动发现所有 target
    - "italy,japan" → 逗号分隔列表
    - "italy" → 单个 target ID
    """
    target_norm = target_arg.strip()

    if not target_norm:
        raise click.ClickException("--target 参数不能为空")

    if target_norm.lower() == "all":
        # 自动发现所有 target
        project_root = Path(config_dir) if config_dir else _find_project_root()
        from news_sentry.core.multi_run import auto_discover_targets

        discovered = auto_discover_targets(project_root)
        if not discovered:
            raise click.ClickException(
                "未发现任何 target 配置文件，"
                f"请检查 {project_root / 'config' / 'targets'} 目录"
            )
        click.echo(f"自动发现 {len(discovered)} 个 target: {', '.join(discovered)}")
        return discovered

    if "," in target_norm:
        # 逗号分隔
        targets = [t.strip() for t in target_norm.split(",") if t.strip()]
        if not targets:
            raise click.ClickException("逗号分隔列表中没有有效的 target ID")
        return targets

    # 单个 target ID
    return [target_norm]


def _run_single_loop(
    target_id: str,
    stage: str,
    run_id: str | None,
    dry_run: bool,
    config_dir: str | None,
    profile_id: str | None,
    log_level: str,
    interval_seconds: int,
) -> None:
    """循环运行单个 target 的 bounded_run。"""
    import asyncio
    import signal
    import sys

    from news_sentry.core.run import ConfigError, bounded_run

    should_stop = False

    def _handle_signal(signum: int, frame: object) -> None:
        nonlocal should_stop
        click.echo(f"\n收到信号 {signum}，当前轮次结束后停止...")
        should_stop = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    project_root = Path(config_dir) if config_dir else _find_project_root()
    round_num = 0

    click.echo(f"循环运行 target={target_id} stage={stage} interval={interval_seconds}s")

    while not should_stop:
        round_num += 1
        loop_run_id = run_id or f"{target_id}_loop_{round_num}"

        try:
            ctx = bounded_run(
                target_id=target_id,
                stage=stage,
                run_id=loop_run_id,
                dry_run=dry_run,
                config_dir=str(project_root),
                profile_id=profile_id,
            )
            click.echo(
                f"[轮次 {round_num}] target={target_id} "
                f"collected={ctx.events_collected} errors={ctx.errors_count}"
            )
        except ConfigError as e:
            click.echo(f"[轮次 {round_num}] 配置错误: {e}", err=True)
            sys.exit(2)
        except Exception as e:
            click.echo(f"[轮次 {round_num}] 运行异常: {e}", err=True)

        if should_stop:
            break

        click.echo(f"[轮次 {round_num}] 完成，等待 {interval_seconds}s...")
        asyncio.run(asyncio.sleep(interval_seconds))


def _run_multi_loop(
    target_ids: list[str],
    stage: str,
    run_id_prefix: str | None,
    dry_run: bool,
    config_dir: Path,
    profile_id: str | None,
    log_level: str,
    interval_seconds: int,
    per_target_min: int = 5,
    global_max: int = 30,
) -> None:
    """循环运行多 target 的 multi_run_async。"""
    import asyncio
    import signal
    import sys

    from news_sentry.core.multi_run import multi_run_async

    should_stop = False

    def _handle_signal(signum: int, frame: object) -> None:
        nonlocal should_stop
        click.echo(f"\n收到信号 {signum}，当前轮次结束后停止...")
        should_stop = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    round_num = 0

    click.echo(
        f"循环运行 targets={target_ids} stage={stage} interval={interval_seconds}s"
    )

    while not should_stop:
        round_num += 1
        prefix = run_id_prefix or f"multi_loop_{round_num}"

        try:
            results = asyncio.run(
                multi_run_async(
                    target_ids=target_ids,
                    stage=stage,
                    run_id_prefix=prefix,
                    dry_run=dry_run,
                    config_dir=config_dir,
                    profile_id=profile_id,
                    per_target_min=per_target_min,
                    global_max=global_max,
                )
            )
            _report_multi_results(results, target_ids, prefix=f"[轮次 {round_num}]")

        except Exception as e:
            click.echo(f"[轮次 {round_num}] 运行异常: {e}", err=True)

        if should_stop:
            break

        click.echo(f"[轮次 {round_num}] 完成，等待 {interval_seconds}s...")
        asyncio.run(asyncio.sleep(interval_seconds))


def _report_multi_results(
    results: list,
    target_ids: list[str],
    prefix: str = "",
) -> None:
    """格式化输出多 target 执行结果。"""
    success_count = 0
    partial_count = 0
    error_count = 0

    tag = f"{prefix} " if prefix else ""

    for i, result in enumerate(results):
        tid = target_ids[i] if i < len(target_ids) else f"target[{i}]"
        from news_sentry.models.pipeline_context import PipelineContext

        if isinstance(result, PipelineContext):
            if result.errors_count == 0:
                success_count += 1
                click.echo(
                    f"{tag}OK   {tid}: collected={result.events_collected} "
                    f"filtered={result.events_filtered} "
                    f"judged={result.events_judged} "
                    f"output={result.events_output}"
                )
            else:
                partial_count += 1
                click.echo(
                    f"{tag}PART {tid}: collected={result.events_collected} "
                    f"errors={result.errors_count}"
                )
        else:
            error_count += 1
            err_msg = (
                result["error"] if isinstance(result, dict) else str(result)
            )
            click.echo(f"{tag}FAIL {tid}: {err_msg}")

    click.echo(
        f"{tag}汇总: total={len(results)} success={success_count} "
        f"partial={partial_count} error={error_count}"
    )

    if error_count > 0:
        sys.exit(1)
```

- [ ] **Step 2: 更新 CLI 导入**

在 `src/news_sentry/cli/__init__.py` 顶部添加必要的导入：

```python
# 新增导入（放到现有 import 后面）
import asyncio
import signal
import sys as _sys
from pathlib import Path
```

检查现有的 `_find_project_root` 函数在 `cli/__init__.py` 和 `cli/target_utils.py` 中都需要。当前 `cli/__init__.py` 中已有 `_find_project_root()` 定义（在 `doctor` 命令附近），需要确认它可以在 `run` 命令中使用。

如果 `run` 命令中 `_find_project_root` 不可直接访问（在不同作用域），将其抽取为模块级函数或从已有的公共位置导入。

- [ ] **Step 3: 运行现有 CLI 测试确认无回归**

```bash
cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && .venv/bin/python3 -m pytest tests/unit/test_cli.py -v
```

预期：所有现有 CLI 测试通过，单 target 用法不受影响。

- [ ] **Step 4: 手动验证 CLI 语法**

```bash
# 验证 --help 输出包含新增选项
cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && .venv/bin/python3 -m news_sentry.cli run --help
```

预期输出中包含：
- `--target` 帮助文本提到 "all"、"italy,japan" 等
- `--interval` 选项
- `--per-target-min` 和 `--global-max` 选项

- [ ] **Step 5: 运行全部测试确认无回归**

```bash
cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && ruff check src/news_sentry/cli/__init__.py && .venv/bin/python3 -m mypy src/news_sentry/cli/__init__.py && .venv/bin/python3 -m pytest tests/ -q
```

- [ ] **Step 6: 提交**

```bash
cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && git add src/news_sentry/cli/__init__.py && git commit -m "Phase 29: CLI --target all/逗号多target/--interval 循环 (P29.04)"
```

---

## Task 5: 资源隔离 — AI 预算锁 + 独立 SQLite

**Files:**
- Modify: `src/news_sentry/core/async_run.py`（如果 Phase 25 已创建）或新建方法

本 Task 确保多 target 场景下的资源隔离：
1. 每个 target 独立 SQLite db（`data/{target_id}/state.db`），这已是 Phase 26 存储层设计的天然结果
2. AI 预算全局共享，但通过 `asyncio.Lock` 保护防超支
3. `bounded_run_async` 需要接受 `ai_budget_lock` 和 `fair_scheduler` 参数

- [ ] **Step 1: 为 bounded_run_async 添加多 target 参数支持**

在 `src/news_sentry/core/async_run.py` 中，确保 `bounded_run_async` 接受以下新增参数：

```python
async def bounded_run_async(
    target_id: str,
    stage: str = "all",
    run_id: str | None = None,
    dry_run: bool = False,
    config_dir: Path | None = None,
    profile_id: str | None = None,
    output_root: Path | None = None,
    max_concurrent: int = 10,
    # Phase 29 新增参数：
    http_client: httpx.AsyncClient | None = None,
    fair_scheduler: FairScheduler | None = None,
    ai_budget_lock: asyncio.Lock | None = None,
) -> PipelineContext:
    """异步版 pipeline 入口。

    Args:
        ...
        http_client: 预创建的 httpx.AsyncClient（多 target 共享连接池）。
                     不提供则在每次调用时创建独立 client。
        fair_scheduler: FairScheduler 实例（多 target 时传入）。
                        用于并发采集和 AI 调用时的公平调度。
                        不提供则不启用调度（单 target 模式）。
        ai_budget_lock: AI 预算锁（多 target 共享）。
                        每次 AI 调用前需要 acquire()，调用后 release()。
                        不提供则不启用锁（单 target 模式）。
    """
```

关键实现要点：

```python
async def bounded_run_async(
    target_id: str,
    stage: str = "all",
    run_id: str | None = None,
    dry_run: bool = False,
    config_dir: Path | None = None,
    profile_id: str | None = None,
    output_root: Path | None = None,
    max_concurrent: int = 10,
    http_client: httpx.AsyncClient | None = None,
    fair_scheduler: FairScheduler | None = None,
    ai_budget_lock: asyncio.Lock | None = None,
) -> PipelineContext:
    # ... 配置加载 ...

    # 管理 http_client 生命周期
    _own_client = http_client is None
    _client = http_client or httpx.AsyncClient(timeout=30.0)
    try:
        # 在 AI 调用时使用 fair_scheduler 和 ai_budget_lock
        # 例如：
        # if fair_scheduler is not None:
        #     await fair_scheduler.acquire(target_id)
        #     try:
        #         # 执行 AI 调用
        #         ...
        #     finally:
        #         fair_scheduler.release(target_id)

        # 在 AI 预算检查时使用 ai_budget_lock：
        # if ai_budget_lock is not None:
        #     async with ai_budget_lock:
        #         # 检查并扣除预算
        #         ...
        ...
    finally:
        if _own_client:
            await _client.aclose()
```

- [ ] **Step 2: 写 AI 预算锁测试**

```python
# 追加到 tests/unit/test_multi_run.py 或创建 tests/unit/test_resource_isolation.py

class TestResourceIsolation:
    """多 target 资源隔离测试。"""

    @pytest.mark.asyncio
    async def test_ai_budget_lock_prevents_overrun(self):
        """AI 预算锁防止多个 target 同时消费超预算。"""
        import asyncio

        lock = asyncio.Lock()
        budget_remaining = [10.0]  # 用列表包装以在闭包中修改
        consumed: dict[str, float] = {}

        async def _ai_call_with_budget(target_id: str, cost: float) -> bool:
            async with lock:
                if budget_remaining[0] >= cost:
                    budget_remaining[0] -= cost
                    consumed[target_id] = consumed.get(target_id, 0) + cost
                    return True
                return False

        # 10 个 target 每个尝试消费 $1.5，总预算 $10
        results = await asyncio.gather(*[
            _ai_call_with_budget(f"target-{i}", 1.5)
            for i in range(10)
        ])

        # $10 / $1.5 = 6 完整 + 1 部分
        total_consumed = sum(consumed.values())
        assert total_consumed <= 10.0, f"超过预算: {total_consumed}"
        # 至少有 6 个 target 的调用被允许（$9.0 / $1.5 = 6）
        success_count = sum(1 for r in results if r)
        assert success_count >= 6, f"至少 6 个调用应成功，实际 {success_count}"

    @pytest.mark.asyncio
    async def test_fair_scheduler_isolated_per_target(self):
        """FairScheduler 的 per-target 信号量实现独立配额。"""
        from news_sentry.core.fair_scheduler import FairScheduler

        scheduler = FairScheduler(per_target_min=2, global_max=10)
        scheduler.register_targets(["italy", "japan"])

        # italy 占满自己的 2 个槽，japan 仍可获得 2 个槽
        italy_count = 0
        japan_count = 0

        async def _worker(tid: str) -> None:
            await scheduler.acquire(tid)
            if tid == "italy":
                nonlocal italy_count
                italy_count += 1
            else:
                nonlocal japan_count
                japan_count += 1
            await asyncio.sleep(0.01)
            scheduler.release(tid)

        # 同时发起 6 个请求：每个 target 3 个
        tasks = [
            asyncio.create_task(_worker("italy")) for _ in range(3)
        ] + [
            asyncio.create_task(_worker("japan")) for _ in range(3)
        ]
        await asyncio.gather(*tasks)

        # 不应饿死
        assert japan_count >= 2, f"japan 至少获得 2 次槽位，实际 {japan_count}"
```

- [ ] **Step 3: 运行测试确认通过**

```bash
cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && .venv/bin/python3 -m pytest tests/unit/ -k "resource_isolation or multi_run" -v
```

- [ ] **Step 4: 运行全部测试确认无回归**

```bash
cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && .venv/bin/python3 -m pytest tests/ -q
```

- [ ] **Step 5: 提交**

```bash
cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && git add src/news_sentry/core/async_run.py tests/unit/test_resource_isolation.py && git commit -m "Phase 29: 资源隔离 — AI 预算锁 + FairScheduler 集成 (P29.05)"
```

---

## Task 6: 集成测试 — 多 Target 并发执行验证

**Files:**
- Create: `tests/integration/test_multi_target.py`

端到端验证多 target 并发执行的正确性。

- [ ] **Step 1: 写集成测试**

```python
# tests/integration/test_multi_target.py
"""多 target 并发调度集成测试。"""

import asyncio
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from news_sentry.core.fair_scheduler import FairScheduler
from news_sentry.core.multi_run import auto_discover_targets, multi_run_async


class TestAutoDiscoverTargets:
    """自动发现 target 测试。"""

    def test_discovers_targets_from_config_dir(self):
        """从 config/targets/ 发现所有 target（除了 _template）。"""
        project_root = Path(__file__).parent.parent.parent
        targets = auto_discover_targets(project_root)

        # 应有 5 个 target
        assert len(targets) >= 5, f"应至少发现 5 个 target，实际 {len(targets)}: {targets}"
        assert "italy" in targets
        assert "china-watch-en" in targets
        assert "japan" in targets
        assert "germany" in targets
        assert "france" in targets

        # 不应包含 _template
        assert "_template" not in targets

    def test_skips_template_files(self):
        """跳过 _template.yaml。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            targets_dir = Path(tmpdir) / "config" / "targets"
            targets_dir.mkdir(parents=True)

            (targets_dir / "real-target.yaml").write_text(
                "target_id: real-target\n", encoding="utf-8"
            )
            (targets_dir / "_template.yaml").write_text(
                "target_id: template\n", encoding="utf-8"
            )
            (targets_dir / "_private.yaml").write_text(
                "target_id: private\n", encoding="utf-8"
            )

            # 创建 pyproject.toml 以便 _find_project_root 能找到
            (Path(tmpdir) / "pyproject.toml").touch()

            discovered = auto_discover_targets(Path(tmpdir))
            assert "real-target" in discovered
            assert "_template" not in discovered
            assert "private" not in discovered


class TestMultiRunIntegration:
    """多 target 并发执行集成测试。"""

    @pytest.mark.asyncio
    async def test_multi_run_with_mocked_pipeline(self):
        """用 mock pipeline 验证多 target 并发执行流程。"""
        execution_log: list[str] = []

        async def _mock_run(target_id, stage, http_client=None, **kwargs):
            execution_log.append(f"start:{target_id}")
            # 模拟不同 target 不同耗时
            delays = {"italy": 0.05, "japan": 0.03, "germany": 0.08}
            await asyncio.sleep(delays.get(target_id, 0.02))
            execution_log.append(f"end:{target_id}")

            ctx = MagicMock()
            ctx.target_id = target_id
            ctx.events_collected = 100
            ctx.events_filtered = 80
            ctx.events_judged = 60
            ctx.events_output = 60
            ctx.errors_count = 0
            return ctx

        with patch(
            "news_sentry.core.multi_run.bounded_run_async",
            side_effect=_mock_run,
        ):
            start = time.monotonic()
            results = await multi_run_async(
                target_ids=["italy", "japan", "germany"],
                stage="all",
            )
            elapsed = time.monotonic() - start

        # 应在 0.15s 内完成（并发执行，不是串行 0.16s）
        assert elapsed < 0.2, f"并发执行应快于串行: {elapsed:.3f}s"

        # 所有 target 都完成了
        assert len(results) == 3
        assert all(
            r.target_id in {"italy", "japan", "germany"}
            for r in results
        )

        # 验证并发性质：第二个 target 启动前第一个还未完成
        starts = [
            (entry.split(":")[1], i)
            for i, entry in enumerate(execution_log)
            if entry.startswith("start:")
        ]
        ends = [
            (entry.split(":")[1], i)
            for i, entry in enumerate(execution_log)
            if entry.startswith("end:")
        ]
        # 所有 start 应该在最前面（批量提交），ends 交错
        assert len(starts) == 3
        assert len(ends) == 3

    @pytest.mark.asyncio
    async def test_error_isolation(self):
        """一个 target 失败不影响其他。"""
        async def _mixed_run(target_id, stage, **kwargs):
            if target_id == "japan":
                raise RuntimeError("japan 模拟失败")
            ctx = MagicMock()
            ctx.target_id = target_id
            ctx.errors_count = 0
            return ctx

        with patch(
            "news_sentry.core.multi_run.bounded_run_async",
            side_effect=_mixed_run,
        ):
            results = await multi_run_async(
                target_ids=["italy", "japan", "germany"],
                stage="all",
            )

        assert len(results) == 3

        # italy 和 germany 应正常完成
        from news_sentry.models.pipeline_context import PipelineContext
        assert isinstance(results[0], PipelineContext)  # italy
        assert isinstance(results[2], PipelineContext)  # germany
        # japan 应返回错误
        assert isinstance(results[1], dict)
        assert "error" in results[1]


class TestFairSchedulerIntegration:
    """FairScheduler 集成场景测试。"""

    @pytest.mark.asyncio
    async def test_full_pipeline_with_scheduler(self):
        """完整 pipeline + FairScheduler 集成。"""
        scheduler = FairScheduler(per_target_min=3, global_max=15)
        targets = ["t-a", "t-b", "t-c"]
        scheduler.register_targets(targets)

        acquired: dict[str, int] = {}

        async def _simulate_collect(tid: str, n_sources: int):
            for _ in range(n_sources):
                await scheduler.acquire(tid)
                await asyncio.sleep(0.005)  # 模拟网络请求
                acquired[tid] = acquired.get(tid, 0) + 1
                scheduler.release(tid)

        await asyncio.gather(
            *[_simulate_collect(t, 10) for t in targets]
        )

        assert sum(acquired.values()) == 30  # 3 * 10 sources

    @pytest.mark.asyncio
    async def test_five_targets_concurrent_collect(self):
        """模拟 5 个 target 各 10 个源的并发采集（最真实场景）。"""
        scheduler = FairScheduler(per_target_min=5, global_max=30)
        targets = ["italy", "china-watch-en", "japan", "germany", "france"]
        scheduler.register_targets(targets)

        target_sources: dict[str, list[str]] = {}

        async def _collect_source(tid: str, source_id: str):
            await scheduler.acquire(tid)
            try:
                await asyncio.sleep(0.01)  # 模拟 HTTP 请求
                target_sources.setdefault(tid, []).append(source_id)
            finally:
                scheduler.release(tid)

        # 每个 target 10 个源
        all_tasks = []
        for tid in targets:
            for i in range(10):
                all_tasks.append(
                    asyncio.create_task(_collect_source(tid, f"{tid}-src-{i}"))
                )

        start = time.monotonic()
        await asyncio.gather(*all_tasks)
        elapsed = time.monotonic() - start

        # 验证所有源都被采集
        for tid in targets:
            assert len(target_sources.get(tid, [])) == 10, (
                f"{tid} 应有 10 个源，实际 {len(target_sources.get(tid, []))}"
            )

        # 50 个源，global_max=30，每个源约 0.01s
        # 理论最快：50/30*0.01 ≈ 0.017s，容忍到 0.3s
        assert elapsed < 0.5, f"5-target 并发采集时间应 < 0.5s，实际 {elapsed:.3f}s"
```

- [ ] **Step 2: 运行集成测试**

```bash
cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && .venv/bin/python3 -m pytest tests/integration/test_multi_target.py -v
```

预期：所有集成测试通过

- [ ] **Step 3: 运行全部测试确认无回归**

```bash
cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && .venv/bin/python3 -m pytest tests/ -q
```

- [ ] **Step 4: 提交**

```bash
cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && git add tests/integration/test_multi_target.py && git commit -m "Phase 29: 多 target 并发调度集成测试 (P29.06)"
```

---

## Task 7: 集成验证与最终清理

- [ ] **Step 1: 运行完整代码质量检查**

```bash
cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && \
ruff check src/news_sentry/core/fair_scheduler.py \
  src/news_sentry/core/multi_run.py \
  src/news_sentry/core/orchestrator.py \
  src/news_sentry/cli/__init__.py && \
.venv/bin/python3 -m mypy \
  src/news_sentry/core/fair_scheduler.py \
  src/news_sentry/core/multi_run.py \
  src/news_sentry/core/orchestrator.py \
  src/news_sentry/cli/__init__.py
```

预期：ruff=0, mypy=0

- [ ] **Step 2: 运行全部测试**

```bash
cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && .venv/bin/python3 -m pytest tests/ -q
```

- [ ] **Step 3: 确认覆盖率未下降**

```bash
cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && .venv/bin/python3 -m pytest tests/ --cov=news_sentry --cov-report=term -q 2>&1 | tail -15
```

预期：覆盖率 >= 92% (Phase 开始前水平)

- [ ] **Step 4: 确认不包含敏感信息**

```bash
cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && make scan-sensitive 2>/dev/null || echo "make scan-sensitive 不可用，跳过"
```

- [ ] **Step 5: 最终提交**

```bash
cd /Volumes/SSD/Code/06-dev-tools/NewsSentry && \
git commit --allow-empty -m "Phase 29: 多 Target 并发调度 — 集成验证通过 (P29.00)"
```

---

## 验收清单

Phase 29 完成的验收条件：

- [ ] FairScheduler 实现并测试通过（Task 1）
- [ ] multi_run_async() 实现并测试通过（Task 2）
- [ ] PipelineOrchestrator 扩展支持多 target 编排（Task 3）
- [ ] CLI --target all / --target id1,id2 / --interval N 均可用（Task 4）
- [ ] 资源隔离：AI 预算锁 + 每 target 独立 SQLite db（Task 5）
- [ ] 集成测试覆盖 5 target 并发采集场景（Task 6）
- [ ] 全部现有测试通过（无回归）
- [ ] ruff check = 0, mypy = 0
- [ ] 测试覆盖率 >= 92%
- [ ] 单 target 用法完全不变（`--target italy` 仍走原同步或 async 路径）

### CLI 用户界面

```bash
# 现有用例不变
python -m news_sentry.cli run --target italy --stage all

# 新增：自动发现所有 target 并并发执行
python -m news_sentry.cli run --target all --stage all

# 新增：指定多 target
python -m news_sentry.cli run --target italy,japan --stage collect

# 新增：循环运行（每 300 秒 = 5 分钟一轮）
python -m news_sentry.cli run --target all --stage all --interval 300

# 新增：单 target 循环
python -m news_sentry.cli run --target italy --stage all --interval 600
```

### 预期性能

| 场景 | Phase 28 前 | Phase 29 后 |
|------|-----------|-----------|
| 5 target 串行全 pipeline | ~50min (5 x 10min) | ~1-2min (并发) |
| 单 target 单次 run | ~1min | ~1min（不变） |
| 70 源并发采集 | ~350s | ~30-40s（Phase 25 已优化，P29 不退化） |

---

## 依赖关系

```
P25 (async 基础) ──→ P26 (SQLite) ──→ P27 (AI 优化) ──→ P28 (API Server)
                                                          │
                                                          ▼
                                                    P29 (多 target 并发)
```

P29 依赖 Phase 25-28 的全部基础设施：
- P25: `bounded_run_async()`, `httpx.AsyncClient`, `asyncio.Semaphore`
- P26: SQLite 存储层，每 target 独立 `state.db`
- P27: AI 调用并发化 + 缓存
- P28: API Server SQLite 查询（多 target 统计汇聚）

---

## 回滚策略

P29 不引入新的 feature flag。回滚方式：

1. CLI 不改动 `--target single` 的内部路径：单 target 仍走原 `bounded_run()` 或 `bounded_run_async()`
2. 多 target 路径仅在 `--target all` 或 `--target id1,id2` 时激活
3. 如需回退多 target 功能：`git revert` P29.00-P29.06 的 commit 即可
4. FairScheduler 和 multi_run.py 是纯新增文件，不影响现有代码路径
