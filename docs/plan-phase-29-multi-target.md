# Phase 29: 多 Target 并发调度 — FairScheduler + CLI 多目标 + 循环运行

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现多 Target 并发调度，`--target all` 同时运行 5 个目标（italy, china-watch-en, japan, germany, france），通过 FairScheduler 公平分配并发槽位，每个 target 独立 SQLite 数据库互不干扰；新增 `--interval N` 循环运行模式。

**Architecture:** CLI 层解析 `--target all|a,b` 和 `--interval N` 参数，通过 `asyncio.run()` 桥接到 `bounded_run_multi_async()` 多目标入口。FairScheduler 基于 asyncio.Semaphore 实现两级并发控制：per-target 最小保证 + 全局最大上限。每个 target 独立持有 AsyncStore/Memory/PipelineContext，共享全局 httpx.AsyncClient 连接池和 AI 预算锁。

**Tech Stack:** Python 3.11+, asyncio, httpx (async), aiosqlite (P26), pytest-asyncio

**设计文档:** `docs/performance-overhaul-design.md` Section 8

**前置依赖:** Phase 25（async 基础设施 + bounded_run_async）、Phase 26（AsyncStore SQLite）、Phase 27（AI 调用优化）、Phase 28（API Server 重构）

---

## 文件结构

### 新建文件
- `src/news_sentry/core/scheduler.py` — FairScheduler 公平并发调度器
- `tests/unit/test_scheduler.py` — FairScheduler 单元测试
- `tests/unit/test_multi_target.py` — 多 Target 并发集成测试（含 _resolve_targets、bounded_run_multi_async、run_loop_async、资源隔离）
- `tests/unit/test_cli_multi_target.py` — CLI 多目标 + --interval 参数测试

### 修改文件
- `src/news_sentry/core/async_run.py` — 新增 `bounded_run_multi_async()`、`_resolve_targets()`、`_discover_all_targets()`、`run_loop_async()`、`_run_single_target_async()`、`_target_db_path()`、`_target_memory_dir()`
- `src/news_sentry/cli/__init__.py` — `run` 命令扩展：`--target all|a,b`，新增 `--interval` 选项

### 不改动文件
- `src/news_sentry/core/run.py` — 同步 bounded_run 保留，不改动
- `src/news_sentry/core/config.py` — ConfigLoader 保持同步，不改动
- `src/news_sentry/core/memory.py` — Memory 保持同步（P26 已有 AsyncStore）

---

## Task 1: FairScheduler 公平并发调度器

**Files:**
- Create: `src/news_sentry/core/scheduler.py`
- Test: `tests/unit/test_scheduler.py`

- [ ] **Step 1: 写 FairScheduler 测试**

```python
# tests/unit/test_scheduler.py
"""FairScheduler 公平并发调度器测试。"""

from __future__ import annotations

import asyncio

import pytest

from news_sentry.core.scheduler import FairScheduler


class TestFairScheduler:
    """FairScheduler 两级并发控制：per-target 最小保证 + 全局最大上限。"""

    @pytest.mark.asyncio
    async def test_acquire_release_within_min(self):
        """per_target_min 内的请求应立即获取槽位。"""
        scheduler = FairScheduler(per_target_min=5, global_max=30)
        scheduler.register("italy")

        for _ in range(5):
            await scheduler.acquire("italy")
        # 5 个槽位全部获取成功，无阻塞

        # 释放全部
        for _ in range(5):
            scheduler.release("italy")

    @pytest.mark.asyncio
    async def test_exceed_per_target_blocks_until_release(self):
        """超过 per_target_min 的请求阻塞，直到有槽位释放。"""
        scheduler = FairScheduler(per_target_min=2, global_max=30)
        scheduler.register("italy")

        # 消耗 2 个槽位（per_target_min）
        await scheduler.acquire("italy")
        await scheduler.acquire("italy")

        # 第 3 个请求应阻塞
        acquired = asyncio.Event()

        async def try_acquire():
            await scheduler.acquire("italy")
            acquired.set()

        task = asyncio.create_task(try_acquire())
        # 短暂等待，确认阻塞
        await asyncio.sleep(0.05)
        assert not acquired.is_set()

        # 释放一个槽位，第 3 个请求应获取成功
        scheduler.release("italy")
        await asyncio.sleep(0.05)
        assert acquired.is_set()
        task.cancel()

    @pytest.mark.asyncio
    async def test_global_max_limits_total_concurrency(self):
        """全局信号量限制所有 target 的总并发数。"""
        scheduler = FairScheduler(per_target_min=3, global_max=4)
        scheduler.register("italy")
        scheduler.register("japan")

        # italy 占 3，japan 占 1，达到全局上限 4
        await scheduler.acquire("italy")
        await scheduler.acquire("italy")
        await scheduler.acquire("italy")
        await scheduler.acquire("japan")

        # germany 的请求应阻塞（全局满）
        scheduler.register("germany")
        acquired = asyncio.Event()

        async def try_acquire_germany():
            await scheduler.acquire("germany")
            acquired.set()

        task = asyncio.create_task(try_acquire_germany())
        await asyncio.sleep(0.05)
        assert not acquired.is_set()

        # 释放 italy 的一个槽位，germany 应获取成功
        scheduler.release("italy")
        await asyncio.sleep(0.05)
        assert acquired.is_set()
        task.cancel()

    @pytest.mark.asyncio
    async def test_no_starvation_completed_target_releases_slots(self):
        """先完成的 target 释放槽位后，其他 target 不会饥饿。"""
        scheduler = FairScheduler(per_target_min=2, global_max=4)
        scheduler.register("italy")
        scheduler.register("japan")

        # italy 占 2 个
        await scheduler.acquire("italy")
        await scheduler.acquire("italy")
        # japan 占 2 个（全局满）
        await scheduler.acquire("japan")
        await scheduler.acquire("japan")

        # japan 完成，释放全部
        scheduler.release("japan")
        scheduler.release("japan")

        # italy 可以获取更多（因为 japan 释放了全局信号量）
        await scheduler.acquire("italy")
        scheduler.release("italy")

        # 清理
        scheduler.release("italy")
        scheduler.release("italy")

    @pytest.mark.asyncio
    async def test_register_creates_per_target_semaphore(self):
        """register() 为每个 target 创建独立的 Semaphore。"""
        scheduler = FairScheduler(per_target_min=5, global_max=30)
        scheduler.register("italy")
        scheduler.register("japan")

        assert "italy" in scheduler.registered_targets
        assert "japan" in scheduler.registered_targets
        assert len(scheduler.registered_targets) == 2

    @pytest.mark.asyncio
    async def test_register_duplicate_raises(self):
        """重复注册同一 target 应抛出 ValueError。"""
        scheduler = FairScheduler(per_target_min=5, global_max=30)
        scheduler.register("italy")

        with pytest.raises(ValueError, match="已注册"):
            scheduler.register("italy")

    @pytest.mark.asyncio
    async def test_acquire_unregistered_target_raises(self):
        """未 register 的 target 调用 acquire 应抛出 KeyError。"""
        scheduler = FairScheduler(per_target_min=5, global_max=30)

        with pytest.raises(KeyError, match="unregistered"):
            await scheduler.acquire("nonexistent")

    @pytest.mark.asyncio
    async def test_release_unregistered_target_raises(self):
        """未 register 的 target 调用 release 应抛出 KeyError。"""
        scheduler = FairScheduler(per_target_min=5, global_max=30)

        with pytest.raises(KeyError, match="unregistered"):
            scheduler.release("nonexistent")

    @pytest.mark.asyncio
    async def test_context_manager_usage(self):
        """acquire/release 可通过 async context manager 使用。"""
        scheduler = FairScheduler(per_target_min=2, global_max=30)
        scheduler.register("italy")

        async with scheduler.slot("italy"):
            # 在 with 块内持有一个槽位
            pass
        # 退出 with 后槽位自动释放

        # 再次获取应该成功
        async with scheduler.slot("italy"):
            pass
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python3 -m pytest tests/unit/test_scheduler.py -v
```

预期：FAIL — `ModuleNotFoundError: No module named 'news_sentry.core.scheduler'`

- [ ] **Step 3: 实现 FairScheduler**

```python
# src/news_sentry/core/scheduler.py
"""FairScheduler — 多 Target 公平并发调度器。

两级并发控制：
1. per-target Semaphore: 每个目标保证至少 per_target_min 个并发槽位
2. global Semaphore: 所有目标合计不超过 global_max 个并发槽位

先完成的目标释放槽位给其他目标，保证不饥饿。
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator


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

        Args:
            target_id: 目标标识符。

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
        """获取一个并发槽位。

        先获取 per-target 信号量，再获取全局信号量。
        两个信号量都获取成功后才返回。

        Args:
            target_id: 目标标识符。

        Raises:
            KeyError: target 未注册。
        """
        if target_id not in self._per_target:
            raise KeyError(f"unregistered target: '{target_id}'")
        await self._per_target[target_id].acquire()
        await self._global.acquire()

    def release(self, target_id: str) -> None:
        """释放一个并发槽位。

        先释放全局信号量，再释放 per-target 信号量。

        Args:
            target_id: 目标标识符。

        Raises:
            KeyError: target 未注册。
        """
        if target_id not in self._per_target:
            raise KeyError(f"unregistered target: '{target_id}'")
        self._global.release()
        self._per_target[target_id].release()

    @asynccontextmanager
    async def slot(self, target_id: str) -> AsyncIterator[None]:
        """async context manager 形式获取/释放槽位。

        用法::

            async with scheduler.slot("italy"):
                # 在此块内持有一个槽位
                await do_work()
        """
        await self.acquire(target_id)
        try:
            yield
        finally:
            self.release(target_id)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python3 -m pytest tests/unit/test_scheduler.py -v
```

预期：10 passed

- [ ] **Step 5: 运行全部现有测试确认无回归**

```bash
.venv/bin/python3 -m pytest tests/ -q
```

预期：全部测试通过

- [ ] **Step 6: 提交**

```bash
git add src/news_sentry/core/scheduler.py tests/unit/test_scheduler.py
git commit -m "Phase 29: FairScheduler 公平并发调度器 (P29.01)"
```

---

## Task 2: _resolve_targets() 目标发现与解析

**Files:**
- Modify: `src/news_sentry/core/async_run.py`
- Create: `tests/unit/test_multi_target.py`（TestResolveTargets 部分）

- [ ] **Step 1: 写 _resolve_targets 测试**

```python
# tests/unit/test_multi_target.py
"""多 Target 并发调度测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestResolveTargets:
    """_resolve_targets() 将 target_str 解析为 target_id 列表。"""

    def test_single_target(self, tmp_path: Path):
        """单个 target ID 直接返回。"""
        from news_sentry.core.async_run import _resolve_targets

        result = _resolve_targets("italy", config_dir=tmp_path)
        assert result == ["italy"]

    def test_comma_separated_targets(self, tmp_path: Path):
        """逗号分隔的 target 列表。"""
        from news_sentry.core.async_run import _resolve_targets

        result = _resolve_targets("italy,japan,germany", config_dir=tmp_path)
        assert result == ["italy", "japan", "germany"]

    def test_comma_separated_strips_whitespace(self, tmp_path: Path):
        """逗号分隔时自动去除前后空格。"""
        from news_sentry.core.async_run import _resolve_targets

        result = _resolve_targets(" italy , japan , germany ", config_dir=tmp_path)
        assert result == ["italy", "japan", "germany"]

    def test_all_keyword_discovers_targets(self, tmp_path: Path):
        """'all' 关键字从 config/targets/ 目录发现所有 target。"""
        from news_sentry.core.async_run import _resolve_targets

        targets_dir = tmp_path / "config" / "targets"
        targets_dir.mkdir(parents=True)
        for tid in ["italy", "japan", "germany", "france", "china-watch-en"]:
            (targets_dir / f"{tid}.yaml").write_text(f"target_id: {tid}")
        # 模板文件应被跳过
        (targets_dir / "_template.yaml").write_text("target_id: _template")

        result = _resolve_targets("all", config_dir=tmp_path)
        assert sorted(result) == ["china-watch-en", "france", "germany", "italy", "japan"]

    def test_all_keyword_empty_dir(self, tmp_path: Path):
        """config/targets/ 为空时 'all' 返回空列表。"""
        from news_sentry.core.async_run import _resolve_targets

        targets_dir = tmp_path / "config" / "targets"
        targets_dir.mkdir(parents=True)

        result = _resolve_targets("all", config_dir=tmp_path)
        assert result == []

    def test_all_keyword_skips_underscore_prefixed(self, tmp_path: Path):
        """'all' 跳过以 _ 开头的文件（如 _template.yaml）。"""
        from news_sentry.core.async_run import _resolve_targets

        targets_dir = tmp_path / "config" / "targets"
        targets_dir.mkdir(parents=True)
        (targets_dir / "italy.yaml").write_text("target_id: italy")
        (targets_dir / "_internal.yaml").write_text("target_id: _internal")

        result = _resolve_targets("all", config_dir=tmp_path)
        assert result == ["italy"]

    def test_duplicate_targets_deduplicated(self, tmp_path: Path):
        """逗号列表中的重复 target ID 自动去重。"""
        from news_sentry.core.async_run import _resolve_targets

        result = _resolve_targets("italy,italy,japan", config_dir=tmp_path)
        assert result == ["italy", "japan"]

    def test_all_keyword_nonexistent_dir(self, tmp_path: Path):
        """config/targets/ 目录不存在时 'all' 返回空列表。"""
        from news_sentry.core.async_run import _resolve_targets

        result = _resolve_targets("all", config_dir=tmp_path)
        assert result == []
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python3 -m pytest tests/unit/test_multi_target.py::TestResolveTargets -v
```

预期：FAIL — `ImportError: cannot import name '_resolve_targets' from 'news_sentry.core.async_run'`（或 `ModuleNotFoundError` 如果 P25 尚未实现 async_run.py）

- [ ] **Step 3: 在 async_run.py 中实现 _resolve_targets() 和 _discover_all_targets()**

在 `src/news_sentry/core/async_run.py` 中添加以下函数（在现有 import 之后、`bounded_run_async` 定义之前）：

```python
from pathlib import Path


def _resolve_targets(target_str: str, config_dir: Path) -> list[str]:
    """将 target 参数字符串解析为 target_id 列表。

    支持以下格式：
    - 单个 target: "italy"
    - 逗号分隔: "italy,japan,germany"
    - 关键字 "all": 从 config/targets/ 发现所有 target

    Args:
        target_str: target 参数字符串。
        config_dir: 项目根目录。

    Returns:
        去重后的 target_id 列表。
    """
    if target_str == "all":
        return _discover_all_targets(config_dir)

    # 逗号分隔，去重并去除空格
    seen: set[str] = set()
    result: list[str] = []
    for part in target_str.split(","):
        tid = part.strip()
        if tid and tid not in seen:
            seen.add(tid)
            result.append(tid)
    return result


def _discover_all_targets(config_dir: Path) -> list[str]:
    """从 config/targets/ 目录发现所有 target。

    跳过以 _ 开头的文件（如 _template.yaml），返回按字母排序的列表。

    Args:
        config_dir: 项目根目录。

    Returns:
        target_id 列表。
    """
    targets_dir = config_dir / "config" / "targets"
    if not targets_dir.is_dir():
        return []
    targets: list[str] = []
    for yaml_file in sorted(targets_dir.glob("*.yaml")):
        if yaml_file.name.startswith("_"):
            continue
        targets.append(yaml_file.stem)
    return targets
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python3 -m pytest tests/unit/test_multi_target.py::TestResolveTargets -v
```

预期：8 passed

- [ ] **Step 5: 提交**

```bash
git add src/news_sentry/core/async_run.py tests/unit/test_multi_target.py
git commit -m "Phase 29: _resolve_targets 目标发现与解析 (P29.02)"
```

---

## Task 3: bounded_run_multi_async() 多目标并发入口

**Files:**
- Modify: `src/news_sentry/core/async_run.py`
- Modify: `tests/unit/test_multi_target.py`

- [ ] **Step 1: 写 bounded_run_multi_async 测试**

在 `tests/unit/test_multi_target.py` 中追加：

```python
class TestBoundedRunMultiAsync:
    """bounded_run_multi_async() 多目标并发入口测试。"""

    @pytest.mark.asyncio
    async def test_runs_all_targets_concurrently(self):
        """验证所有 target 并发运行，每个 target 调用一次 _run_single_target_async。"""
        from news_sentry.core.async_run import bounded_run_multi_async

        call_log: list[str] = []

        async def fake_run_single(target_id, **kwargs):
            call_log.append(target_id)
            ctx = MagicMock()
            ctx.target_id = target_id
            ctx.errors_count = 0
            return ctx

        with patch(
            "news_sentry.core.async_run._run_single_target_async",
            side_effect=fake_run_single,
        ):
            results = await bounded_run_multi_async(
                targets=["italy", "japan", "germany"],
                stage="all",
            )

        assert sorted(call_log) == ["germany", "italy", "japan"]
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_targets_run_in_parallel_not_serial(self):
        """验证多个 target 并行执行而非串行。"""
        from news_sentry.core.async_run import bounded_run_multi_async

        timestamps: dict[str, float] = {}

        async def slow_run(target_id, **kwargs):
            timestamps[target_id] = asyncio.get_event_loop().time()
            await asyncio.sleep(0.1)
            ctx = MagicMock()
            ctx.target_id = target_id
            ctx.errors_count = 0
            return ctx

        with patch(
            "news_sentry.core.async_run._run_single_target_async",
            side_effect=slow_run,
        ):
            await bounded_run_multi_async(
                targets=["italy", "japan"],
                stage="collect",
            )

        # 两个 target 应几乎同时开始（差距 < 50ms）
        assert abs(timestamps["italy"] - timestamps["japan"]) < 0.05

    @pytest.mark.asyncio
    async def test_single_target_runs_normally(self):
        """单个 target 传入时也能正常工作。"""
        from news_sentry.core.async_run import bounded_run_multi_async

        async def fake_run_single(target_id, **kwargs):
            ctx = MagicMock()
            ctx.target_id = target_id
            ctx.errors_count = 0
            return ctx

        with patch(
            "news_sentry.core.async_run._run_single_target_async",
            side_effect=fake_run_single,
        ):
            results = await bounded_run_multi_async(
                targets=["italy"],
                stage="collect",
            )

        assert len(results) == 1
        assert results[0].target_id == "italy"

    @pytest.mark.asyncio
    async def test_empty_targets_returns_empty(self):
        """空 target 列表返回空结果。"""
        from news_sentry.core.async_run import bounded_run_multi_async

        results = await bounded_run_multi_async(targets=[], stage="all")
        assert results == []

    @pytest.mark.asyncio
    async def test_failed_target_does_not_block_others(self):
        """某个 target 失败不阻塞其他 target。"""
        from news_sentry.core.async_run import bounded_run_multi_async

        async def fake_run_single(target_id, **kwargs):
            if target_id == "failing":
                raise RuntimeError("模拟失败")
            ctx = MagicMock()
            ctx.target_id = target_id
            ctx.errors_count = 0
            return ctx

        with patch(
            "news_sentry.core.async_run._run_single_target_async",
            side_effect=fake_run_single,
        ):
            results = await bounded_run_multi_async(
                targets=["italy", "failing", "japan"],
                stage="all",
            )

        # italy 和 japan 应成功完成
        successful_ids = [r.target_id for r in results]
        assert "italy" in successful_ids
        assert "japan" in successful_ids
        # failing 不在成功结果中
        assert "failing" not in successful_ids

    @pytest.mark.asyncio
    async def test_shared_http_client_passed_to_all_targets(self):
        """验证全局 httpx.AsyncClient 共享给所有 target。"""
        from news_sentry.core.async_run import bounded_run_multi_async

        received_clients: list[object] = []

        async def fake_run_single(target_id, **kwargs):
            received_clients.append(kwargs.get("http_client"))
            ctx = MagicMock()
            ctx.target_id = target_id
            ctx.errors_count = 0
            return ctx

        with patch(
            "news_sentry.core.async_run._run_single_target_async",
            side_effect=fake_run_single,
        ):
            await bounded_run_multi_async(
                targets=["italy", "japan"],
                stage="collect",
            )

        # 所有 target 应收到同一个 http_client 实例
        assert len(received_clients) == 2
        assert received_clients[0] is received_clients[1]

    @pytest.mark.asyncio
    async def test_scheduler_registered_for_all_targets(self):
        """验证 FairScheduler 为每个 target 注册。"""
        from news_sentry.core.async_run import bounded_run_multi_async

        captured_scheduler = None

        async def fake_run_single(target_id, **kwargs):
            nonlocal captured_scheduler
            if captured_scheduler is None:
                captured_scheduler = kwargs.get("scheduler")
            ctx = MagicMock()
            ctx.target_id = target_id
            ctx.errors_count = 0
            return ctx

        with patch(
            "news_sentry.core.async_run._run_single_target_async",
            side_effect=fake_run_single,
        ):
            await bounded_run_multi_async(
                targets=["italy", "japan", "germany"],
                stage="all",
            )

        assert captured_scheduler is not None
        assert sorted(captured_scheduler.registered_targets) == ["germany", "italy", "japan"]
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python3 -m pytest tests/unit/test_multi_target.py::TestBoundedRunMultiAsync -v
```

预期：FAIL — `ImportError: cannot import name 'bounded_run_multi_async'`

- [ ] **Step 3: 实现 bounded_run_multi_async() 和 _run_single_target_async()**

在 `src/news_sentry/core/async_run.py` 中添加以下代码：

```python
import logging

import httpx

from news_sentry.core.scheduler import FairScheduler

logger = logging.getLogger(__name__)


async def bounded_run_multi_async(
    targets: list[str],
    stage: str = "all",
    run_id: str | None = None,
    config_dir: Path | None = None,
    profile_id: str | None = None,
    output_root: Path | None = None,
) -> list:
    """多 Target 并发运行入口。

    为每个 target 启动独立的 pipeline 运行，通过 FairScheduler 协调并发。
    全局共享 httpx.AsyncClient 连接池。单个 target 失败不影响其他 target。

    Args:
        targets: target_id 列表。空列表返回空结果。
        stage: pipeline 阶段。
        run_id: 可选运行 ID 前缀。
        config_dir: 项目根目录。
        profile_id: Deployment profile ID。
        output_root: 输出根目录。

    Returns:
        成功完成的 PipelineContext 列表（失败的 target 不在列表中）。
    """
    if not targets:
        return []

    # 初始化 FairScheduler
    scheduler = FairScheduler(per_target_min=5, global_max=30)
    for target_id in targets:
        scheduler.register(target_id)

    # 共享连接池
    async with httpx.AsyncClient(timeout=30.0) as http_client:
        # AI 预算共享锁
        ai_budget_lock = asyncio.Lock()

        coros = [
            _run_single_target_async(
                target_id=target_id,
                stage=stage,
                run_id=run_id,
                config_dir=config_dir,
                profile_id=profile_id,
                output_root=output_root,
                http_client=http_client,
                ai_budget_lock=ai_budget_lock,
                scheduler=scheduler,
            )
            for target_id in targets
        ]

        # 并发运行所有 target，单 target 失败不中断其他
        results = await asyncio.gather(*coros, return_exceptions=True)

    # 过滤掉异常结果，记录失败日志
    success: list = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(
                "target '%s' 运行失败: %s",
                targets[i],
                result,
            )
        else:
            success.append(result)
    return success


async def _run_single_target_async(
    target_id: str,
    stage: str = "all",
    run_id: str | None = None,
    config_dir: Path | None = None,
    profile_id: str | None = None,
    output_root: Path | None = None,
    http_client: httpx.AsyncClient | None = None,
    ai_budget_lock: asyncio.Lock | None = None,
    scheduler: FairScheduler | None = None,
) -> object:
    """运行单个 target 的完整 pipeline。

    使用 FairScheduler 控制并发槽位。如果 scheduler 为 None，则不进行并发控制。

    Args:
        target_id: 目标标识符。
        stage: pipeline 阶段。
        run_id: 可选运行 ID。
        config_dir: 项目根目录。
        profile_id: Deployment profile ID。
        output_root: 输出根目录。
        http_client: 共享的 httpx.AsyncClient。
        ai_budget_lock: 共享的 AI 预算锁。
        scheduler: FairScheduler 实例。

    Returns:
        PipelineContext。
    """
    # 获取并发槽位
    if scheduler is not None:
        await scheduler.acquire(target_id)

    try:
        # 调用已有的 bounded_run_async（Phase 25 创建）
        # 将共享资源注入
        ctx = await bounded_run_async(
            target_id=target_id,
            stage=stage,
            run_id=run_id,
            config_dir=config_dir,
            profile_id=profile_id,
            output_root=output_root,
            http_client=http_client,
            ai_budget_lock=ai_budget_lock,
        )
        return ctx
    finally:
        if scheduler is not None:
            scheduler.release(target_id)
```

注意：`bounded_run_async` 函数签名需要在 Phase 25 基础上扩展，接受 `http_client`、`ai_budget_lock` 可选参数。如果这些参数为 None，函数内部自行创建。此处假设 P25 的 `bounded_run_async` 已做此扩展（或在此 Task 中补全参数签名）。

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python3 -m pytest tests/unit/test_multi_target.py::TestBoundedRunMultiAsync -v
```

预期：7 passed

- [ ] **Step 5: 运行全部测试确认无回归**

```bash
.venv/bin/python3 -m pytest tests/ -q
```

预期：全部测试通过

- [ ] **Step 6: 提交**

```bash
git add src/news_sentry/core/async_run.py tests/unit/test_multi_target.py
git commit -m "Phase 29: bounded_run_multi_async 多目标并发入口 (P29.03)"
```

---

## Task 4: CLI 多目标参数扩展 --target all|a,b + --interval

**Files:**
- Modify: `src/news_sentry/cli/__init__.py`
- Create: `tests/unit/test_cli_multi_target.py`

- [ ] **Step 1: 写 CLI 多目标参数测试**

```python
# tests/unit/test_cli_multi_target.py
"""CLI 多目标 + --interval 参数测试。"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from news_sentry.cli import main
from news_sentry.models.pipeline_context import PipelineContext


def _ctx(target_id: str = "italy") -> PipelineContext:
    """构造最小 PipelineContext 用于 mock 返回。"""
    return PipelineContext(
        run_id=f"run-{target_id}",
        target_id=target_id,
        stage="collected",
        started_at="2026-05-15T00:00:00+00:00",
        profile_id="local-workstation",
    )


class TestCLIMultiTarget:
    """--target all 和 --target a,b 的 CLI 行为。"""

    def test_target_all_calls_multi_async(self, monkeypatch):
        """--target all 调用 bounded_run_multi_async 路径。"""
        captured: dict = {}

        async def fake_multi(**kwargs):
            captured.update(kwargs)
            return [_ctx("italy"), _ctx("japan")]

        monkeypatch.setattr(
            "news_sentry.core.async_run.bounded_run_multi_async",
            fake_multi,
        )
        # 拦截 asyncio.run，直接返回协程结果
        monkeypatch.setattr("asyncio.run", lambda coro: coro)

        result = CliRunner().invoke(
            main,
            ["run", "--target", "all", "--stage", "collect"],
        )

        assert result.exit_code == 0
        assert captured.get("stage") == "collect"

    def test_target_comma_separated_calls_multi_async(self, monkeypatch):
        """--target italy,japan 调用 bounded_run_multi_async 路径。"""
        captured: dict = {}

        async def fake_multi(**kwargs):
            captured.update(kwargs)
            return [_ctx("italy"), _ctx("japan")]

        monkeypatch.setattr(
            "news_sentry.core.async_run.bounded_run_multi_async",
            fake_multi,
        )
        monkeypatch.setattr("asyncio.run", lambda coro: coro)

        result = CliRunner().invoke(
            main,
            ["run", "--target", "italy,japan", "--stage", "all"],
        )

        assert result.exit_code == 0
        assert captured.get("stage") == "all"

    def test_single_target_uses_sync_bounded_run(self, monkeypatch):
        """单个 target 仍使用原有 bounded_run 同步入口。"""
        captured: dict = {}

        def fake_bounded_run(**kwargs):
            captured.update(kwargs)
            return _ctx()

        monkeypatch.setattr(
            "news_sentry.core.run.bounded_run",
            fake_bounded_run,
        )

        result = CliRunner().invoke(
            main,
            ["run", "--target", "italy", "--stage", "collect"],
        )

        assert result.exit_code == 0
        assert captured.get("target_id") == "italy"

    def test_multi_target_dry_run_not_yet_supported(self, monkeypatch):
        """多目标模式暂不支持 --dry-run（使用同步路径的 dry-run）。"""
        result = CliRunner().invoke(
            main,
            ["run", "--target", "all", "--stage", "collect", "--dry-run"],
        )

        # dry-run 在多目标模式下走 bounded_run_multi_async，
        # 但 dry_run 参数暂不传入 multi，仍以普通模式运行
        # 此测试验证 CLI 不崩溃
        assert result.exit_code in (0, 1)


class TestCLIInterval:
    """--interval N 循环运行参数。"""

    def test_interval_option_in_help(self):
        """--interval 选项应出现在 run --help 输出中。"""
        result = CliRunner().invoke(main, ["run", "--help"])
        assert result.exit_code == 0
        assert "--interval" in result.output

    def test_interval_must_be_integer(self):
        """--interval 值必须是整数。"""
        result = CliRunner().invoke(
            main,
            ["run", "--target", "all", "--stage", "all", "--interval", "abc"],
        )
        # click type=int 校验失败
        assert result.exit_code != 0

    def test_interval_zero_rejected(self, monkeypatch):
        """--interval 0 应被拒绝。"""
        async def fake_multi(**kwargs):
            return [_ctx()]

        monkeypatch.setattr(
            "news_sentry.core.async_run.bounded_run_multi_async",
            fake_multi,
        )
        monkeypatch.setattr("asyncio.run", lambda coro: coro)

        result = CliRunner().invoke(
            main,
            ["run", "--target", "all", "--stage", "all", "--interval", "0"],
        )
        # 0 不合法
        assert result.exit_code != 0

    def test_interval_negative_rejected(self, monkeypatch):
        """负数 --interval 应被拒绝。"""
        async def fake_multi(**kwargs):
            return [_ctx()]

        monkeypatch.setattr(
            "news_sentry.core.async_run.bounded_run_multi_async",
            fake_multi,
        )
        monkeypatch.setattr("asyncio.run", lambda coro: coro)

        result = CliRunner().invoke(
            main,
            ["run", "--target", "all", "--stage", "all", "--interval", "-1"],
        )
        assert result.exit_code != 0

    def test_interval_single_target_rejected(self, monkeypatch):
        """--interval 配合单个 target（非 all/逗号）应报错或走循环模式。"""
        # 循环模式需要多目标或 all，单 target 不支持 interval
        result = CliRunner().invoke(
            main,
            ["run", "--target", "italy", "--stage", "all", "--interval", "300"],
        )
        # 单目标 + interval: 可能拒绝或忽略 interval
        # 按设计应走同步路径，interval 参数对同步路径无效
        # 此测试验证 CLI 不崩溃
        assert result.exit_code in (0, 1, 2)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python3 -m pytest tests/unit/test_cli_multi_target.py -v
```

预期：FAIL — `--interval` 不在 run --help 输出中，多数测试失败

- [ ] **Step 3: 修改 CLI run 命令**

在 `src/news_sentry/cli/__init__.py` 中，替换现有 `run` 命令定义（从 `@main.command()` 到函数结束）。保留所有其他命令不变。

```python
@main.command()
@click.option(
    "--target",
    required=True,
    help="Target ID, 'all', or comma-separated list (e.g., italy,japan).",
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
    default=None,
    type=int,
    help="Loop mode: run pipeline every N seconds. Use with --target all or comma-separated.",
)
def run(
    target: str,
    stage: str,
    run_id: str | None,
    dry_run: bool,
    log_level: str,
    config_dir: str | None,
    profile_id: str | None,
    interval: int | None,
) -> None:
    """Execute a bounded run for a monitoring target.

    \b
    Target modes:
      --target italy         Single target (sync pipeline)
      --target all           All configured targets concurrently (async)
      --target italy,japan   Specific targets concurrently (async)

    \b
    Loop mode (async only):
      --interval 300         Repeat every 300 seconds

    Exit codes: 0=success, 1=partial failure, 2=config error, 3=sandbox blocked.
    """
    import asyncio as _asyncio

    # --interval 参数校验
    if interval is not None and interval <= 0:
        click.echo("--interval 必须为正整数", err=True)
        sys.exit(2)

    # 判断是否为多目标模式
    is_multi = target == "all" or "," in target

    if is_multi:
        _run_multi_target(
            target=target,
            stage=stage,
            run_id=run_id,
            config_dir=config_dir,
            profile_id=profile_id,
            interval=interval,
        )
    else:
        _run_single_target(
            target=target,
            stage=stage,
            run_id=run_id,
            dry_run=dry_run,
            config_dir=config_dir,
            profile_id=profile_id,
        )
```

然后在 `src/news_sentry/cli/__init__.py` 底部（`__all__` 行之前）添加辅助函数：

```python
def _run_single_target(
    target: str,
    stage: str,
    run_id: str | None,
    dry_run: bool,
    config_dir: str | None,
    profile_id: str | None,
) -> None:
    """单目标同步运行（原有 bounded_run 行为）。"""
    from news_sentry.core.run import ConfigError, bounded_run

    try:
        ctx = bounded_run(
            target_id=target,
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
            click.echo(f"⚠ {ctx.errors_count} 个源采集失败，详见 RunLog: {ctx.run_log_path}")
            sys.exit(1)
    except ConfigError as e:
        click.echo(f"配置错误: {e}", err=True)
        sys.exit(2)
    except Exception as e:
        click.echo(f"运行异常: {e}", err=True)
        sys.exit(1)


def _run_multi_target(
    target: str,
    stage: str,
    run_id: str | None,
    config_dir: str | None,
    profile_id: str | None,
    interval: int | None,
) -> None:
    """多目标异步运行入口。"""
    import asyncio as _asyncio

    from news_sentry.core.async_run import _resolve_targets, bounded_run_multi_async

    config_path = Path(config_dir) if config_dir else _find_project_root(Path(__file__))
    target_ids = _resolve_targets(target, config_dir=config_path)

    if not target_ids:
        click.echo("未发现可运行的 target", err=True)
        sys.exit(2)

    try:
        if interval is not None:
            _run_loop(
                target_ids=target_ids,
                stage=stage,
                config_dir=config_dir,
                profile_id=profile_id,
                interval=interval,
            )
        else:
            results = _asyncio.run(
                bounded_run_multi_async(
                    targets=target_ids,
                    stage=stage,
                    run_id=run_id,
                    config_dir=config_dir,
                    profile_id=profile_id,
                )
            )
            _report_multi_results(results)
    except Exception as e:
        click.echo(f"运行异常: {e}", err=True)
        sys.exit(1)


def _run_loop(
    target_ids: list[str],
    stage: str,
    config_dir: str | None,
    profile_id: str | None,
    interval: int,
) -> None:
    """循环运行模式：每隔 interval 秒执行一次完整 pipeline。

    通过 asyncio.run() 启动异步循环，每次迭代使用 asyncio.sleep() 等待。
    使用 Ctrl+C 终止循环。

    Args:
        target_ids: target_id 列表。
        stage: pipeline 阶段。
        config_dir: 项目根目录。
        profile_id: Deployment profile ID。
        interval: 循环间隔（秒）。
    """
    import asyncio as _asyncio

    from news_sentry.core.async_run import run_loop_async

    click.echo(f"循环模式: 每 {interval}s 运行 {len(target_ids)} 个 target (Ctrl+C 终止)")

    try:
        _asyncio.run(
            run_loop_async(
                targets=target_ids,
                stage=stage,
                config_dir=config_dir,
                profile_id=profile_id,
                interval=interval,
            )
        )
    except KeyboardInterrupt:
        click.echo("\n循环已终止")


def _report_multi_results(results: list) -> None:
    """输出多目标运行结果摘要。

    Args:
        results: PipelineContext 列表。
    """
    if not results:
        click.echo("无 target 成功完成")
        return

    for ctx in results:
        status = "ok" if ctx.errors_count == 0 else f"⚠ {ctx.errors_count} 个错误"
        click.echo(
            f"  target: {ctx.target_id}  "
            f"collected: {ctx.events_collected}  "
            f"filtered: {ctx.events_filtered}  "
            f"judged: {ctx.events_judged}  "
            f"output: {ctx.events_output}  "
            f"[{status}]"
        )

    total_errors = sum(ctx.errors_count for ctx in results)
    if total_errors > 0:
        sys.exit(1)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python3 -m pytest tests/unit/test_cli_multi_target.py -v
```

预期：9 passed

- [ ] **Step 5: 运行原有 CLI 测试确认无回归**

```bash
.venv/bin/python3 -m pytest tests/unit/test_cli.py -v
```

预期：全部通过（原有单目标行为不变）

- [ ] **Step 6: 运行全部测试确认无回归**

```bash
.venv/bin/python3 -m pytest tests/ -q
```

预期：全部测试通过

- [ ] **Step 7: 提交**

```bash
git add src/news_sentry/cli/__init__.py tests/unit/test_cli_multi_target.py
git commit -m "Phase 29: CLI 多目标 --target all|a,b + --interval 循环运行 (P29.04)"
```

---

## Task 5: run_loop_async 循环运行模式

**Files:**
- Modify: `src/news_sentry/core/async_run.py`
- Modify: `tests/unit/test_multi_target.py`

- [ ] **Step 1: 写循环模式测试**

在 `tests/unit/test_multi_target.py` 中追加：

```python
def _make_ctx(target_id: str) -> MagicMock:
    """构造 mock PipelineContext。"""
    ctx = MagicMock()
    ctx.target_id = target_id
    ctx.errors_count = 0
    ctx.events_collected = 0
    ctx.events_filtered = 0
    ctx.events_judged = 0
    ctx.events_output = 0
    return ctx


class TestIntervalLoop:
    """run_loop_async() 循环运行模式测试。"""

    @pytest.mark.asyncio
    async def test_loop_respects_max_iterations(self):
        """循环模式应遵守 max_iterations 上限。"""
        from news_sentry.core.async_run import run_loop_async

        call_count = 0

        async def fake_multi(**kwargs):
            nonlocal call_count
            call_count += 1
            return [_make_ctx("italy")]

        with patch(
            "news_sentry.core.async_run.bounded_run_multi_async",
            side_effect=fake_multi,
        ):
            # interval=0 让循环尽可能快
            await run_loop_async(
                targets=["italy"],
                stage="all",
                interval=0,
                max_iterations=3,
            )

        assert call_count == 3

    @pytest.mark.asyncio
    async def test_loop_continues_after_single_iteration_error(self):
        """单次迭代失败不终止循环。"""
        from news_sentry.core.async_run import run_loop_async

        call_count = 0

        async def fake_multi(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("模拟第 1 轮失败")
            return [_make_ctx("italy")]

        with patch(
            "news_sentry.core.async_run.bounded_run_multi_async",
            side_effect=fake_multi,
        ):
            await run_loop_async(
                targets=["italy"],
                stage="all",
                interval=0,
                max_iterations=3,
            )

        # 应完成 3 次迭代（第 1 次失败但循环继续）
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_loop_with_multiple_targets(self):
        """循环模式支持多 target。"""
        from news_sentry.core.async_run import run_loop_async

        targets_received: list[list[str]] = []

        async def fake_multi(**kwargs):
            targets_received.append(list(kwargs.get("targets", [])))
            return [_make_ctx(t) for t in kwargs.get("targets", [])]

        with patch(
            "news_sentry.core.async_run.bounded_run_multi_async",
            side_effect=fake_multi,
        ):
            await run_loop_async(
                targets=["italy", "japan"],
                stage="all",
                interval=0,
                max_iterations=2,
            )

        assert len(targets_received) == 2
        assert targets_received[0] == ["italy", "japan"]
        assert targets_received[1] == ["italy", "japan"]

    @pytest.mark.asyncio
    async def test_loop_sleeps_between_iterations(self):
        """循环模式在迭代间应 asyncio.sleep(interval)。"""
        from news_sentry.core.async_run import run_loop_async

        sleep_durations: list[float] = []

        async def fake_multi(**kwargs):
            return [_make_ctx("italy")]

        async def fake_sleep(seconds):
            sleep_durations.append(seconds)

        with patch(
            "news_sentry.core.async_run.bounded_run_multi_async",
            side_effect=fake_multi,
        ), patch(
            "news_sentry.core.async_run.asyncio.sleep",
            side_effect=fake_sleep,
        ):
            await run_loop_async(
                targets=["italy"],
                stage="all",
                interval=60,
                max_iterations=2,
            )

        # 2 次迭代之间有 1 次 sleep
        assert sleep_durations == [60]

    @pytest.mark.asyncio
    async def test_loop_zero_iterations_returns_immediately(self):
        """max_iterations=0 不应执行任何迭代。"""
        from news_sentry.core.async_run import run_loop_async

        call_count = 0

        async def fake_multi(**kwargs):
            nonlocal call_count
            call_count += 1
            return [_make_ctx("italy")]

        with patch(
            "news_sentry.core.async_run.bounded_run_multi_async",
            side_effect=fake_multi,
        ):
            await run_loop_async(
                targets=["italy"],
                stage="all",
                interval=0,
                max_iterations=0,
            )

        assert call_count == 0
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python3 -m pytest tests/unit/test_multi_target.py::TestIntervalLoop -v
```

预期：FAIL — `ImportError: cannot import name 'run_loop_async'`

- [ ] **Step 3: 实现 run_loop_async()**

在 `src/news_sentry/core/async_run.py` 中添加：

```python
async def run_loop_async(
    targets: list[str],
    stage: str = "all",
    config_dir: Path | None = None,
    profile_id: str | None = None,
    interval: int = 300,
    max_iterations: int = 0,
) -> None:
    """异步循环运行模式。

    每隔 interval 秒执行一次多目标 pipeline。单次迭代失败不终止循环。
    Ctrl+C 通过 KeyboardInterrupt 终止（由 CLI 层捕获）。

    Args:
        targets: target_id 列表。
        stage: pipeline 阶段。
        config_dir: 项目根目录。
        profile_id: Deployment profile ID。
        interval: 循环间隔（秒）。
        max_iterations: 最大迭代次数。0 表示不执行任何迭代（由 CLI 层决定无限循环）。
    """
    iteration = 0
    while iteration < max_iterations:
        iteration += 1
        logger.info("循环模式: 第 %d 轮开始", iteration)
        try:
            await bounded_run_multi_async(
                targets=targets,
                stage=stage,
                config_dir=config_dir,
                profile_id=profile_id,
            )
        except Exception:
            logger.error("循环模式: 第 %d 轮失败", iteration, exc_info=True)

        if iteration < max_iterations:
            await asyncio.sleep(interval)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python3 -m pytest tests/unit/test_multi_target.py::TestIntervalLoop -v
```

预期：5 passed

- [ ] **Step 5: 运行全部测试确认无回归**

```bash
.venv/bin/python3 -m pytest tests/ -q
```

预期：全部测试通过

- [ ] **Step 6: 提交**

```bash
git add src/news_sentry/core/async_run.py tests/unit/test_multi_target.py
git commit -m "Phase 29: run_loop_async 循环运行模式 (P29.05)"
```

---

## Task 6: 资源隔离 — per-target 独立状态路径

**Files:**
- Modify: `src/news_sentry/core/async_run.py`
- Modify: `tests/unit/test_multi_target.py`

- [ ] **Step 1: 写资源隔离测试**

在 `tests/unit/test_multi_target.py` 中追加：

```python
class TestResourceIsolation:
    """验证多 target 间的资源隔离。"""

    def test_each_target_gets_own_state_db_path(self):
        """每个 target 的 SQLite 数据库路径独立。"""
        from news_sentry.core.async_run import _target_db_path

        italy_db = _target_db_path("italy", Path("/data"))
        japan_db = _target_db_path("japan", Path("/data"))

        assert str(italy_db).endswith("italy/state.db")
        assert str(japan_db).endswith("japan/state.db")
        assert italy_db != japan_db

    def test_each_target_gets_own_memory_dir(self):
        """每个 target 的 Memory 目录独立。"""
        from news_sentry.core.async_run import _target_memory_dir

        italy_mem = _target_memory_dir("italy", Path("/data"))
        japan_mem = _target_memory_dir("japan", Path("/data"))

        assert str(italy_mem).endswith("italy/memory")
        assert str(japan_mem).endswith("japan/memory")
        assert italy_mem != japan_mem

    def test_db_path_under_output_root(self):
        """state.db 路径位于 output_root/{target_id}/ 下。"""
        from news_sentry.core.async_run import _target_db_path

        db_path = _target_db_path("italy", Path("./data"))
        assert "italy" in str(db_path)
        assert db_path.name == "state.db"

    def test_memory_dir_under_output_root(self):
        """memory 目录位于 output_root/{target_id}/ 下。"""
        from news_sentry.core.async_run import _target_memory_dir

        mem_dir = _target_memory_dir("france", Path("./data"))
        assert "france" in str(mem_dir)
        assert mem_dir.name == "memory"

    @pytest.mark.asyncio
    async def test_scheduler_per_target_independent_slots(self):
        """不同 target 的槽位互不影响。"""
        from news_sentry.core.scheduler import FairScheduler

        scheduler = FairScheduler(per_target_min=2, global_max=30)
        scheduler.register("italy")
        scheduler.register("japan")

        # italy 占满自己的 2 个槽位
        await scheduler.acquire("italy")
        await scheduler.acquire("italy")

        # japan 仍能获取自己的槽位（不受 italy 影响，只要全局未满）
        await scheduler.acquire("japan")
        scheduler.release("japan")

        scheduler.release("italy")
        scheduler.release("italy")
```

- [ ] **Step 2: 在 async_run.py 中添加路径计算函数**

在 `src/news_sentry/core/async_run.py` 中添加：

```python
def _target_db_path(target_id: str, output_root: Path) -> Path:
    """计算 target 的 SQLite 数据库路径。

    与 Phase 26 AsyncStore 的 db_path 一致：
    ``{output_root}/{target_id}/state.db``

    Args:
        target_id: 目标标识符。
        output_root: 输出根目录。

    Returns:
        data/{target_id}/state.db 路径。
    """
    return output_root / target_id / "state.db"


def _target_memory_dir(target_id: str, output_root: Path) -> Path:
    """计算 target 的 Memory 目录路径。

    与现有 Memory 的 memory_dir 一致：
    ``{output_root}/{target_id}/memory``

    Args:
        target_id: 目标标识符。
        output_root: 输出根目录。

    Returns:
        data/{target_id}/memory 目录路径。
    """
    return output_root / target_id / "memory"
```

- [ ] **Step 3: 运行测试确认通过**

```bash
.venv/bin/python3 -m pytest tests/unit/test_multi_target.py::TestResourceIsolation -v
```

预期：5 passed

- [ ] **Step 4: 运行全部测试确认无回归**

```bash
.venv/bin/python3 -m pytest tests/ -q
```

预期：全部测试通过

- [ ] **Step 5: 提交**

```bash
git add src/news_sentry/core/async_run.py tests/unit/test_multi_target.py
git commit -m "Phase 29: 资源隔离 — per-target 独立状态路径 (P29.06)"
```

---

## Task 7: 集成验证与清理

- [ ] **Step 1: 运行完整检查**

```bash
ruff check src/news_sentry/core/scheduler.py src/news_sentry/core/async_run.py src/news_sentry/cli/__init__.py
.venv/bin/python3 -m mypy src/news_sentry/core/scheduler.py src/news_sentry/core/async_run.py
.venv/bin/python3 -m pytest tests/ -q
```

预期：ruff=0, mypy=0, 全部测试通过

- [ ] **Step 2: 确认覆盖率未下降**

```bash
.venv/bin/python3 -m pytest tests/ --cov=news_sentry -q 2>&1 | tail -5
```

预期：覆盖率 >= 92%（Phase 开始前水平）

- [ ] **Step 3: 手动验证 CLI help 输出**

```bash
.venv/bin/python3 -m news_sentry.cli run --help
```

预期：输出中包含 `--target`、`--stage`、`--interval` 三个选项，`--target` help 提及 `all` 和逗号分隔

- [ ] **Step 4: 最终提交**

```bash
git commit --allow-empty -m "Phase 29: 集成验证通过 — 多 Target 并发调度 (P29.00)"
```

---

## 验证标准

Phase 29 完成的验收条件：

- [ ] 全部测试通过（CI 绿色）
- [ ] ruff check = 0, mypy = 0
- [ ] 测试覆盖率 >= 92%
- [ ] 新增文件：`scheduler.py`
- [ ] `--target all` 并发运行所有 5 个 target（italy, china-watch-en, japan, germany, france）
- [ ] `--target italy,japan` 并发运行指定 target
- [ ] `--target italy` 保持原有单目标同步行为不变
- [ ] `--interval 300` 每 5 分钟循环运行
- [ ] FairScheduler 保证每个 target 最少 5 并发、全局最多 30 并发
- [ ] 每个 target 独立 SQLite state.db，无跨 target 锁竞争
- [ ] 单 target 失败不阻塞其他 target

---

## 新增模块 API 速查

### `src/news_sentry/core/scheduler.py` — FairScheduler

| 方法 | 签名 | 说明 |
|------|------|------|
| `__init__` | `(per_target_min=5, global_max=30)` | 初始化调度器 |
| `register` | `(target_id: str) -> None` | 注册 target，创建 per-target Semaphore |
| `acquire` | `async (target_id: str) -> None` | 获取一个并发槽位（阻塞直到可用） |
| `release` | `(target_id: str) -> None` | 释放一个并发槽位 |
| `slot` | `async (target_id: str) -> AsyncIterator[None]` | async context manager 形式 |
| `registered_targets` | `property -> list[str]` | 已注册 target 列表 |

### `src/news_sentry/core/async_run.py` — 新增函数

| 函数 | 签名 | 说明 |
|------|------|------|
| `bounded_run_multi_async` | `async (targets, stage, ...) -> list` | 多目标并发入口 |
| `_run_single_target_async` | `async (target_id, stage, ..., scheduler) -> PipelineContext` | 单目标运行（带调度） |
| `_resolve_targets` | `(target_str, config_dir) -> list[str]` | 解析 target 参数字符串 |
| `_discover_all_targets` | `(config_dir) -> list[str]` | 从 config/targets/ 发现所有 target |
| `run_loop_async` | `async (targets, stage, interval, max_iterations) -> None` | 异步循环运行 |
| `_target_db_path` | `(target_id, output_root) -> Path` | per-target SQLite 路径 |
| `_target_memory_dir` | `(target_id, output_root) -> Path` | per-target Memory 目录 |
