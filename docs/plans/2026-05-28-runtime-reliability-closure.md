# Runtime Reliability Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 收口当前已验证的运行时可靠性修复，并继续定位新闻采集新鲜度停滞的真实阻塞点。

**Architecture:** 保持现有 CLI / FastAPI / Vanilla JS 架构不变。本阶段只触碰运行链路必要文件：异步 collect/judge 的 provider factory 传递、SQLite 备份一致性、真实 target 配置加载回归，以及采集新鲜度诊断所需的最小测试和修复。前端视觉、公开门户、管理后台样式不纳入本阶段。

**Tech Stack:** Python 3.11+ / Pydantic v2 / pytest / ruff / existing FastAPI runtime.

---

## Scope

本阶段分两步：

1. 先收口当前工作树中已经存在且测试通过的 runtime 修复：
   - `src/news_sentry/core/async_run.py`
   - `src/news_sentry/core/async_store.py`
   - `tests/unit/test_async_run.py`
   - `tests/unit/test_config.py`
2. 再继续排查采集新鲜度：
   - 当前服务健康状态。
   - 最近 run logs。
   - `data/*` 下最新事件时间。
   - collector config/status/diagnostics。
   - scheduler 或 trigger 是否实际执行 collect/filter/judge/output。

明确排除：

- `src/news_sentry/static/public.css` 的本地样式 diff。
- `.omx/`。
- `docs/plans/frontend-redesign-analysis.md`、`docs/plans/plan-phase-74-feed-redesign.md`、`docs/plans/plan-phase-75-public-news-workbench.md`。
- `config/sources/japan/api/`、`config/sources/japan/opencli/`，除非采集新鲜度证据明确指向 Japan source 缺失。

## Task 1: Commit Existing Runtime Fixes

**Files:**
- Modify: `src/news_sentry/core/async_run.py`
- Modify: `src/news_sentry/core/async_store.py`
- Modify: `tests/unit/test_async_run.py`
- Modify: `tests/unit/test_config.py`

- [ ] **Step 1: Inspect the current runtime diff**

Run:

```bash
git diff -- src/news_sentry/core/async_run.py src/news_sentry/core/async_store.py tests/unit/test_async_run.py tests/unit/test_config.py
```

Expected: diff only shows provider factory forwarding, SQLite backup implementation, and focused tests.

- [ ] **Step 2: Verify the targeted tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_async_run.py::TestRunCollectAsync::test_collect_translation_uses_provider_factory tests/unit/test_async_run.py::TestRunJudgeAsync::test_judge_async_tiered_success tests/unit/test_config.py::TestLoadTarget::test_real_configured_targets_load -q
```

Expected: all selected tests pass.

- [ ] **Step 3: Run runtime regression checks**

Run:

```bash
ruff check src/news_sentry/core/async_run.py src/news_sentry/core/async_store.py tests/unit/test_async_run.py tests/unit/test_config.py
.venv/bin/python -m pytest tests/unit/test_async_run.py tests/unit/test_config.py -q
```

Expected: ruff passes and both unit test files pass.

- [ ] **Step 4: Commit only runtime files**

Run:

```bash
git add src/news_sentry/core/async_run.py src/news_sentry/core/async_store.py tests/unit/test_async_run.py tests/unit/test_config.py
git diff --cached --name-only
git commit -m "fix: restore async runtime provider wiring"
```

Expected staged files are exactly the four runtime/test files listed above.

## Task 2: Gather Collection Freshness Evidence

**Files:**
- Read: `data/`
- Read: `logs/`
- Read: `config/runtime/collector.yaml`
- Read: `src/news_sentry/core/api_server.py`
- Read: `src/news_sentry/core/scheduler.py`
- Read: `src/news_sentry/cli/serve.py`

- [ ] **Step 1: Check service health and collector endpoints**

Run:

```bash
curl --noproxy '*' -s http://127.0.0.1:8765/api/v1/health
curl --noproxy '*' -s http://127.0.0.1:8765/api/v1/collector/config
curl --noproxy '*' -s http://127.0.0.1:8765/api/v1/collector/status
curl --noproxy '*' -s http://127.0.0.1:8765/api/v1/collector/diagnostics
```

Expected: health is `ok`; collector responses reveal whether auto collection is enabled, running, and blocked by missing key/config/runtime errors.

- [ ] **Step 2: Inspect data freshness by target**

Run:

```bash
find data -type f \( -path '*/raw/*' -o -path '*/evaluated/*' -o -path '*/drafts/*' \) -name '*.md' -print0 | xargs -0 stat -f '%Sm %N' -t '%Y-%m-%d %H:%M:%S' | sort | tail -30
```

Expected: output shows newest event files and which target/stage last changed.

- [ ] **Step 3: Inspect run logs**

Run:

```bash
find logs data -type f \( -name '*.log' -o -name '*run*.json' -o -name '*.jsonl' \) -print | sort | tail -80
```

Expected: identifies the latest run records available for tracing.

- [ ] **Step 4: Form one root-cause hypothesis**

Use the evidence to choose exactly one hypothesis:

- Scheduler not running.
- Collector disabled.
- Collector running but collect phase has no eligible sources.
- Collect succeeds but filter/judge/output stops.
- Provider/API key issue blocks translation or judge.
- Data is fresh on disk but public feed query filters it out.

Do not implement a fix until one hypothesis is supported by evidence.

## Task 3: Fix the Freshness Blocker

**Files:**
- Modify only files implicated by Task 2 evidence.
- Add or modify tests adjacent to the implicated module.

- [ ] **Step 1: Write a failing test for the confirmed blocker**

Run the narrow test command for the implicated module before implementation.

Expected: failure reproduces the confirmed blocker rather than a broad unrelated failure.

- [ ] **Step 2: Implement the smallest fix**

Change only the module responsible for the confirmed blocker. Avoid frontend changes unless Task 2 proves the disk data is fresh and only the public feed query/render path is stale.

- [ ] **Step 3: Verify the fix**

Run:

```bash
ruff check src/news_sentry/core tests/unit
.venv/bin/python -m pytest tests/unit/test_api_server.py tests/unit/test_async_run.py tests/unit/test_config.py -q
```

Expected: relevant tests pass. If the full command is too broad due existing unrelated failures, run the smallest failing module and document the broader blocker.

- [ ] **Step 4: Browser/API smoke**

Run:

```bash
curl --noproxy '*' -s http://127.0.0.1:8765/api/v1/health
curl --noproxy '*' -s 'http://127.0.0.1:8765/api/v1/events/feed?target_id=italy&page_size=5'
```

Expected: health is ok and feed returns a stable JSON payload without authentication or loading deadlock.
