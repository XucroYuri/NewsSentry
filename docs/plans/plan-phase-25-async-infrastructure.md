# Phase 25: Async 基础设施 + 并发采集 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 pipeline 核心执行模型从同步串行迁移到 async/await，实现 70+ RSS/API 源并发采集。

**Architecture:** CLI 层保持同步（click），通过 `asyncio.run()` 桥接到 async pipeline 核心。所有 HTTP 调用从 `httpx` 同步客户端切换到 `httpx.AsyncClient` 连接池。引入令牌桶速率限制器替代固定间隔等待。

**Tech Stack:** Python 3.11+, asyncio, httpx (async), pytest-asyncio, aiosqlite (P26)

**设计文档:** `docs/performance-overhaul-design.md`

---

## 文件结构

### 新建文件
- `src/news_sentry/core/async_rate_limiter.py` — 令牌桶速率限制器（async 版）
- `src/news_sentry/core/async_run.py` — async 版 pipeline 执行核心（`bounded_run_async` 及 `_run_collect_async` 等）
- `tests/unit/test_async_rate_limiter.py` — 令牌桶测试

### 修改文件
- `src/news_sentry/skills/collect/rss_collector.py` — `collect()` → `async def collect()`，httpx.get → AsyncClient
- `src/news_sentry/skills/collect/api_collector.py` — `collect()` → `async def collect()`，httpx.post/get → AsyncClient
- `src/news_sentry/cli/__init__.py` — `run` 命令调用 `asyncio.run(bounded_run_async(...))`
- `pyproject.toml` — 新增 `aiosqlite` 依赖（为 P26 预备）

### 不改动文件
- `src/news_sentry/core/config.py` — ConfigLoader 保持同步（YAML 解析本身很快，P26 再优化）
- `src/news_sentry/core/memory.py` — Memory 保持同步（P26 迁移到 SQLite）
- `src/news_sentry/core/run.py` — 保留原样，async_run.py 是并行入口，不替换

---

## Task 1: AsyncRateLimiter 令牌桶速率限制器

**Files:**
- Create: `src/news_sentry/core/async_rate_limiter.py`
- Test: `tests/unit/test_async_rate_limiter.py`

- [ ] **Step 1: 写令牌桶测试**

```python
# tests/unit/test_async_rate_limiter.py
import asyncio
import time

import pytest

from news_sentry.core.async_rate_limiter import AsyncRateLimiter


class TestAsyncRateLimiter:
    @pytest.mark.asyncio
    async def test_acquire_immediately_when_tokens_available(self):
        limiter = AsyncRateLimiter(rate=10.0, burst=10)
        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 0.1  # 应该立即返回

    @pytest.mark.asyncio
    async def test_waits_when_no_tokens(self):
        limiter = AsyncRateLimiter(rate=10.0, burst=1)
        await limiter.acquire()  # 消耗唯一的 token
        start = time.monotonic()
        await limiter.acquire()  # 应该等待 ~0.1s (1/rate)
        elapsed = time.monotonic() - start
        assert elapsed >= 0.08  # 允许小幅误差
        assert elapsed < 0.3

    @pytest.mark.asyncio
    async def test_burst_allows_rapid_fire(self):
        limiter = AsyncRateLimiter(rate=1.0, burst=5)
        start = time.monotonic()
        for _ in range(5):
            await limiter.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 0.2  # burst=5 应该全部立即通过

    @pytest.mark.asyncio
    async def test_tokens_replenish_over_time(self):
        limiter = AsyncRateLimiter(rate=100.0, burst=2)
        await limiter.acquire()
        await limiter.acquire()
        await asyncio.sleep(0.05)  # 等待恢复 ~5 tokens
        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 0.1  # 恢复后应立即可用
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python3 -m pytest tests/unit/test_async_rate_limiter.py -v
```

预期：FAIL — `ModuleNotFoundError: No module named 'news_sentry.core.async_rate_limiter'`

- [ ] **Step 3: 实现 AsyncRateLimiter**

```python
# src/news_sentry/core/async_rate_limiter.py
"""令牌桶速率限制器（async 版本），替代同步固定间隔的 RateLimiter。"""

import asyncio


class AsyncRateLimiter:
    """令牌桶算法：允许短时间突发（burst），但平均速率不超限。

    Args:
        rate: 每秒补充的令牌数。
        burst: 桶容量（最大突发数）。
    """

    def __init__(self, rate: float = 0.2, burst: int = 10) -> None:
        self._rate = rate
        self._burst = burst
        self._tokens = float(burst)
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """获取一个令牌，无可用令牌时阻塞等待。"""
        async with self._lock:
            now = asyncio.get_running_loop().time()
            if self._last > 0:
                elapsed = now - self._last
                self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
            self._last = now

            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0.0
            else:
                self._tokens -= 1.0
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python3 -m pytest tests/unit/test_async_rate_limiter.py -v
```

预期：4 passed

- [ ] **Step 5: 提交**

```bash
git add src/news_sentry/core/async_rate_limiter.py tests/unit/test_async_rate_limiter.py
git commit -m "Phase 25: AsyncRateLimiter 令牌桶速率限制器 (P25.01)"
```

---

## Task 2: RSSCollector async 化

**Files:**
- Modify: `src/news_sentry/skills/collect/rss_collector.py`
- Test: `tests/unit/test_rss_collector.py`（已有测试文件，需要改造）

- [ ] **Step 1: 写 async 版 collect 测试**

在 `tests/unit/test_rss_collector.py` 中新增 async 测试。以下为新增内容：

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


class TestRSSCollectorAsync:
    """RSSCollector async 版本测试。"""

    def _make_config(self, url="https://example.com/feed.xml"):
        return {
            "channel_id": "test-rss",
            "type": "rss",
            "url": url,
            "timeout": 10,
            "max_items": 50,
        }

    def _make_sandbox(self):
        sandbox = MagicMock()
        sandbox.check.return_value = True
        return sandbox

    @pytest.mark.asyncio
    async def test_collect_async_returns_events(self):
        from news_sentry.skills.collect.rss_collector import RSSCollector

        config = self._make_config()
        sandbox = self._make_sandbox()
        collector = RSSCollector(config, sandbox)

        fake_response = httpx.Response(
            200,
            text='<?xml version="1.0"?><rss><channel><title>Test</title>'
            '<item><title>Hello</title><link>https://example.com/1</link>'
            '<description>Desc</description><pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>'
            '</item></channel></rss>',
            request=httpx.Request("GET", config["url"]),
        )

        with patch("news_sentry.skills.collect.rss_collector.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=fake_response)
            mock_client_cls.return_value = mock_client

            events = await collector.collect_async("run-001", http_client=mock_client)

        assert len(events) >= 1
        assert events[0].title_original == "Hello"

    @pytest.mark.asyncio
    async def test_collect_async_handles_http_error(self):
        from news_sentry.skills.collect.rss_collector import RSSCollector

        config = self._make_config()
        sandbox = self._make_sandbox()
        collector = RSSCollector(config, sandbox)

        with patch("news_sentry.skills.collect.rss_collector.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=httpx.ConnectTimeout("timeout"))
            mock_client_cls.return_value = mock_client

            events = await collector.collect_async("run-001", http_client=mock_client)

        assert events == []
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python3 -m pytest tests/unit/test_rss_collector.py::TestRSSCollectorAsync -v
```

预期：FAIL — `AttributeError: 'RSSCollector' has no attribute 'collect_async'`

- [ ] **Step 3: 在 RSSCollector 中添加 collect_async 方法**

在 `src/news_sentry/skills/collect/rss_collector.py` 中，在 `collect()` 方法之后添加 `collect_async()` 方法。保留原 `collect()` 不变。

```python
async def collect_async(
    self, run_id: str, *, http_client: httpx.AsyncClient | None = None
) -> list[NewsEvent]:
    """异步采集版本。接收外部 AsyncClient 以复用连接池。"""
    if self._rate_limiter:
        await self._rate_limiter.acquire()

    if not self._sandbox.check(self._url):
        return []

    try:
        response = await self._retry_fetch_async(http_client, run_id)
    except Exception:
        self._last_error = traceback.format_exc()
        return []

    feed = feedparser.parse(response.text)
    events: list[NewsEvent] = []
    for entry in feed.entries[: self._max_items]:
        try:
            event = self._entry_to_event(entry, run_id, feed.feed.get("title", ""))
            events.append(event)
        except Exception:
            continue
    return events

async def _retry_fetch_async(
    self,
    client: httpx.AsyncClient | None,
    source_id: str,
    max_retries: int = 3,
) -> httpx.Response:
    """异步指数退避重试。"""
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            use_client = client or httpx.AsyncClient()
            if client is None:
                async with use_client:
                    resp = await use_client.get(
                        self._url, timeout=self._timeout, follow_redirects=True
                    )
            else:
                resp = await use_client.get(
                    self._url, timeout=self._timeout, follow_redirects=True
                )
            if resp.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"Server error {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
            return resp
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                await asyncio.sleep(2**attempt)
    raise last_exc  # type: ignore[misc]
```

需要在文件顶部添加 `import asyncio`（如果还没有的话）。

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python3 -m pytest tests/unit/test_rss_collector.py::TestRSSCollectorAsync -v
```

预期：2 passed

- [ ] **Step 5: 运行全部现有测试确认无回归**

```bash
.venv/bin/python3 -m pytest tests/ -q
```

预期：所有现有测试通过（RSSCollector.collect() 同步版本仍保留）

- [ ] **Step 6: 提交**

```bash
git add src/news_sentry/skills/collect/rss_collector.py tests/unit/test_rss_collector.py
git commit -m "Phase 25: RSSCollector.collect_async 异步采集 (P25.02)"
```

---

## Task 3: APICollector async 化

**Files:**
- Modify: `src/news_sentry/skills/collect/api_collector.py`
- Test: `tests/unit/test_api_collector.py`

与 Task 2 结构对称。在 APICollector 中添加 `collect_async()` 和 `_retry_fetch_async()` 方法，保留原 `collect()` 不变。

测试结构与 Task 2 类似：mock httpx.AsyncClient，测试正常返回和错误处理。

- [ ] **Step 1: 写 async 测试（TestAPICollectorAsync 类）**

在 `tests/unit/test_api_collector.py` 新增：
- `test_collect_async_returns_events` — mock AsyncClient.get 返回 JSON，验证事件列表
- `test_collect_async_handles_http_error` — mock ConnectTimeout，验证返回空列表
- `test_collect_async_post_method` — mock AsyncClient.post 返回 JSON，验证 POST 方法

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python3 -m pytest tests/unit/test_api_collector.py::TestAPICollectorAsync -v
```

- [ ] **Step 3: 在 APICollector 中添加 collect_async 和 _retry_fetch_async**

结构与 RSSCollector 的 async 版本对称。需要处理 GET 和 POST 两种方法。

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python3 -m pytest tests/unit/test_api_collector.py::TestAPICollectorAsync -v
```

- [ ] **Step 5: 运行全部测试确认无回归**

```bash
.venv/bin/python3 -m pytest tests/ -q
```

- [ ] **Step 6: 提交**

```bash
git add src/news_sentry/skills/collect/api_collector.py tests/unit/test_api_collector.py
git commit -m "Phase 25: APICollector.collect_async 异步采集 (P25.03)"
```

---

## Task 4: async_run.py — 异步 Pipeline 核心

**Files:**
- Create: `src/news_sentry/core/async_run.py`
- Test: `tests/unit/test_async_run.py`

- [ ] **Step 1: 写 async_run 测试**

```python
# tests/unit/test_async_run.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from news_sentry.core.async_run import bounded_run_async, _run_collect_async


class TestRunCollectAsync:
    @pytest.mark.asyncio
    async def test_concurrent_collect_gathers_all_sources(self):
        """验证并发采集调用所有源的 collect_async。"""
        config = MagicMock()
        config.sources = [
            {"channel_id": "rss-1", "type": "rss", "url": "https://a.com/feed"},
            {"channel_id": "rss-2", "type": "rss", "url": "https://b.com/feed"},
        ]

        mock_event_1 = MagicMock()
        mock_event_2 = MagicMock()

        with patch(
            "news_sentry.core.async_run.RSSCollector"
        ) as mock_rss_cls, patch(
            "news_sentry.core.async_run.APICollector"
        ) as mock_api_cls:
            mock_collector_1 = AsyncMock()
            mock_collector_1.collect_async = AsyncMock(return_value=[mock_event_1])
            mock_collector_2 = AsyncMock()
            mock_collector_2.collect_async = AsyncMock(return_value=[mock_event_2])
            mock_rss_cls.side_effect = [mock_collector_1, mock_collector_2]

            events = await _run_collect_async(
                config=config,
                run_id="test-run",
                run_log=MagicMock(),
                file_writer=MagicMock(),
                sandbox=MagicMock(),
                memory=MagicMock(),
                ctx=MagicMock(),
            )

        assert len(events) == 2

    @pytest.mark.asyncio
    async def test_concurrent_collect_respects_semaphore(self):
        """验证并发上限被信号量控制。"""
        config = MagicMock()
        config.sources = [
            {"channel_id": f"rss-{i}", "type": "rss", "url": f"https://a.com/{i}"}
            for i in range(20)
        ]

        call_times: list[float] = []

        async def mock_collect_async(run_id, *, http_client=None):
            call_times.append(asyncio.get_running_loop().time())
            await asyncio.sleep(0.05)
            return []

        with patch(
            "news_sentry.core.async_run.RSSCollector"
        ) as mock_rss_cls:
            mock_rss_cls.return_value.collect_async = mock_collect_async
            mock_rss_cls.return_value._last_error = None

            await _run_collect_async(
                config=config,
                run_id="test-run",
                run_log=MagicMock(),
                file_writer=MagicMock(),
                sandbox=MagicMock(),
                memory=MagicMock(),
                ctx=MagicMock(),
                max_concurrent=5,
            )

        # 20 个源，max_concurrent=5，应有重叠但不超过 5 个并发
        assert len(call_times) == 20


class TestBoundedRunAsync:
    @pytest.mark.asyncio
    async def test_calls_collect_then_filter_then_judge_then_output(self):
        """验证阶段按序执行。"""
        config = MagicMock()
        config.target.target_id = "test"
        config.sources = []

        with patch("news_sentry.core.async_run.ConfigLoader") as mock_loader, \
             patch("news_sentry.core.async_run._run_collect_async", new_callable=AsyncMock) as mock_collect, \
             patch("news_sentry.core.async_run._run_filter_async", new_callable=AsyncMock) as mock_filter, \
             patch("news_sentry.core.async_run._run_judge_async", new_callable=AsyncMock) as mock_judge, \
             patch("news_sentry.core.async_run._run_output_async", new_callable=AsyncMock) as mock_output:

            mock_loader.return_value.load_target.return_value = config
            mock_collect.return_value = []
            mock_filter.return_value = []
            mock_judge.return_value = []
            mock_output.return_value = []

            await bounded_run_async(target_id="test", stage="all")

        # 验证四个阶段都被调用
        mock_collect.assert_called_once()
        mock_filter.assert_called_once()
        mock_judge.assert_called_once()
        mock_output.assert_called_once()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python3 -m pytest tests/unit/test_async_run.py -v
```

预期：FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 async_run.py**

核心结构：

```python
# src/news_sentry/core/async_run.py
"""异步 pipeline 执行核心。CLI 通过 asyncio.run() 调用。"""

import asyncio
import logging
from pathlib import Path

import httpx

from news_sentry.core.config import ConfigLoader
from news_sentry.core.sandbox import SandboxEnforcer
from news_sentry.core.memory import Memory
from news_sentry.core.file_writer import FileWriter
from news_sentry.core.async_rate_limiter import AsyncRateLimiter
from news_sentry.models.pipeline_context import PipelineContext
from news_sentry.skills.collect.rss_collector import RSSCollector
from news_sentry.skills.collect.api_collector import APICollector

logger = logging.getLogger(__name__)


async def bounded_run_async(
    target_id: str,
    stage: str = "all",
    run_id: str | None = None,
    dry_run: bool = False,
    config_dir: Path | None = None,
    profile_id: str | None = None,
    output_root: Path | None = None,
    max_concurrent: int = 10,
) -> PipelineContext:
    """异步版 pipeline 入口。"""
    # 加载配置（同步操作，< 2s，在 event loop 中直接执行）
    loader = ConfigLoader(config_dir or Path("config"))
    config = loader.load_target(
        target_id,
        profile_id=profile_id or "local-workstation",
        output_root_override=output_root,
    )

    # 初始化组件
    output_dir = config.output_root / target_id
    memory = Memory(output_dir / "memory")
    file_writer = FileWriter(output_dir)
    sandbox = SandboxEnforcer(config.sandbox_policy)
    ctx = PipelineContext(target_id=target_id, run_id=run_id or "auto")

    # 共享 AsyncClient
    async with httpx.AsyncClient(timeout=30.0) as http_client:
        if stage == "all":
            events = await _run_collect_async(
                config, run_id=ctx.run_id, run_log=None,
                file_writer=file_writer, sandbox=sandbox,
                memory=memory, ctx=ctx,
                http_client=http_client, max_concurrent=max_concurrent,
            )
            events = await _run_filter_async(config, events, run_id=ctx.run_id, ...)
            events = await _run_judge_async(config, events, run_id=ctx.run_id, ...)
            await _run_output_async(config, events, run_id=ctx.run_id, ...)
        elif stage == "collect":
            await _run_collect_async(config, ...)
        # ... 其他 stage 分支

    return ctx


async def _run_collect_async(
    config,
    run_id: str,
    run_log,
    file_writer,
    sandbox,
    memory,
    ctx,
    http_client: httpx.AsyncClient | None = None,
    max_concurrent: int = 10,
) -> list:
    """并发采集所有源。"""
    semaphore = asyncio.Semaphore(max_concurrent)
    all_events: list = []

    async def _collect_one(source_cfg: dict) -> list:
        async with semaphore:
            collector = _create_collector(source_cfg, sandbox)
            if collector is None:
                return []
            try:
                events = await collector.collect_async(run_id, http_client=http_client)
                return events
            except Exception:
                logger.warning("采集源 %s 失败", source_cfg.get("channel_id"))
                return []

    results = await asyncio.gather(
        *[_collect_one(s) for s in config.sources],
        return_exceptions=True,
    )

    for result in results:
        if isinstance(result, list):
            all_events.extend(result)

    # 写入 raw/ (保留文件输出用于人工审查)
    for event in all_events:
        file_writer.write_event(event, "raw")

    return all_events


def _create_collector(source_cfg: dict, sandbox):
    """根据 source type 创建对应 collector。"""
    source_type = source_cfg.get("type", "rss")
    if source_type == "rss":
        return RSSCollector(source_cfg, sandbox)
    elif source_type == "api":
        return APICollector(source_cfg, sandbox)
    return None


async def _run_filter_async(
    config, events: list, *, run_id: str, run_log, file_writer, memory, ctx,
) -> list:
    """异步过滤阶段：接收内存中的事件列表，返回过滤后列表。"""
    from news_sentry.skills.filter.rules_filter import RulesFilter
    from news_sentry.skills.filter.classifier_rules import ClassifierRules

    rules_filter = RulesFilter(config.filter_rules)
    classifier = ClassifierRules(config.classification_rules)

    def _sync_filter() -> list:
        filtered = rules_filter.apply(events)
        classified = classifier.apply(filtered)
        return classified

    result = await asyncio.to_thread(_sync_filter)

    # 写入 evaluated/ 和 archive/（保留文件输出）
    for event in result:
        file_writer.write_event(event, "evaluated")

    return result


async def _run_judge_async(
    config, events: list, *, run_id: str, run_log, file_writer, memory, ctx,
) -> list:
    """异步研判阶段。P25 通过 to_thread 包装同步 ConfidenceRouter。"""
    from news_sentry.core.confidence_router import ConfidenceRouter

    # 复用 run.py 中 _init_ai_judge 的逻辑构建 judge
    # 此处简化：同步执行（AI 调用在 P27 才并发化）
    def _sync_judge() -> list:
        from news_sentry.core.run import _init_ai_judge
        judge = _init_ai_judge(config, run_id)
        if judge is None:
            return events
        router = ConfidenceRouter(
            rules_judge=judge._rules_judge,
            ai_judge=judge._ai_judge,
        )
        return router.judge(events, run_id)

    result = await asyncio.to_thread(_sync_judge)

    for event in result:
        file_writer.write_event(event, "evaluated")

    return result


async def _run_output_async(
    config, events: list, *, run_id: str, run_log, file_writer, ctx,
) -> list:
    """异步输出阶段。P25 通过 to_thread 包装同步 MarkdownWriter + AlertPipeline。"""
    from news_sentry.skills.output.markdown_writer import MarkdownWriter
    from news_sentry.core.alert_pipeline import AlertPipeline

    def _sync_output() -> list:
        writer = MarkdownWriter()
        for event in events:
            writer.write(event, config.output_root / config.target_id / "drafts")

        if config.output_destinations:
            pipeline = AlertPipeline(config.output_destinations)
            pipeline.process(events, run_id)

        return events

    return await asyncio.to_thread(_sync_output)
```

注意：以上为骨架代码。实际实现中 `_run_filter_async`、`_run_judge_async`、`_run_output_async` 在 P25 阶段先通过 `asyncio.to_thread` 包装现有同步逻辑，后续 Phase 再逐步改为原生 async。

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python3 -m pytest tests/unit/test_async_run.py -v
```

- [ ] **Step 5: 运行全部测试确认无回归**

```bash
.venv/bin/python3 -m pytest tests/ -q
```

- [ ] **Step 6: 提交**

```bash
git add src/news_sentry/core/async_run.py tests/unit/test_async_run.py
git commit -m "Phase 25: async_run.py 异步 pipeline 核心 (P25.04)"
```

---

## Task 5: CLI asyncio.run() 桥接

**Files:**
- Modify: `src/news_sentry/cli/__init__.py`（run 命令）

- [ ] **Step 1: 在 run 命令中添加 async 入口**

在 `cli/__init__.py` 的 `run` 命令中，在现有 `bounded_run()` 调用之前，检查 feature flag 决定使用同步还是异步路径：

```python
# 在 run 命令函数内部，替换现有的 bounded_run 调用
import asyncio
from news_sentry.core.async_run import bounded_run_async

# 检查 deployment profile 中的 feature flag
# P25 默认启用 async pipeline
result = asyncio.run(bounded_run_async(
    target_id=target,
    stage=stage,
    run_id=run_id,
    dry_run=dry_run,
    config_dir=config_dir,
    profile_id=profile,
    output_root=output_root,
))
```

保留原有 `bounded_run` 的 import，后续通过 feature flag 切换。P25 直接启用 async。

- [ ] **Step 2: 运行全部测试确认无回归**

```bash
.venv/bin/python3 -m pytest tests/ -q
```

- [ ] **Step 3: 提交**

```bash
git add src/news_sentry/cli/__init__.py
git commit -m "Phase 25: CLI asyncio.run() 桥接 async pipeline (P25.05)"
```

---

## Task 6: 集成验证与清理

- [ ] **Step 1: 运行完整检查**

```bash
ruff check src/news_sentry/core/async_run.py src/news_sentry/core/async_rate_limiter.py src/news_sentry/skills/collect/rss_collector.py src/news_sentry/skills/collect/api_collector.py src/news_sentry/cli/__init__.py
.venv/bin/python3 -m mypy src/news_sentry/core/async_run.py src/news_sentry/core/async_rate_limiter.py
.venv/bin/python3 -m pytest tests/ -q
```

预期：ruff=0, mypy=0, 全部测试通过

- [ ] **Step 2: 确认覆盖率未下降**

```bash
.venv/bin/python3 -m pytest tests/ --cov=news_sentry -q 2>&1 | tail -5
```

预期：覆盖率 >= 92%（Phase 开始前水平）

- [ ] **Step 3: 最终提交**

```bash
git commit --allow-empty -m "Phase 25: 集成验证通过 — async 基础设施 + 并发采集 (P25.00)"
```

---

## 验证标准

Phase 25 完成的验收条件：

- [ ] 全部测试通过（CI 绿色）
- [ ] ruff check = 0, mypy = 0
- [ ] 测试覆盖率 >= 92%
- [ ] 新增文件：`async_rate_limiter.py`, `async_run.py`
- [ ] RSSCollector 和 APICollector 同时具备 `collect()` (同步) 和 `collect_async()` (异步) 方法
- [ ] CLI 通过 `asyncio.run()` 调用 async pipeline
- [ ] 并发采集通过信号量控制（Semaphore=10）
