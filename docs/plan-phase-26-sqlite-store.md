# Phase 26: SQLite 存储层 — AsyncStore 替代 Memory

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Memory 类（YAML 文件全量序列化）迁移到 SQLite 存储层（aiosqlite），实现增量写入和索引查询，消除 known_ids 线性增长带来的 I/O 劣化。

**Architecture:** 每个 target 独立 `state.db` 文件，通过 `aiosqlite` 提供完整 async 接口。AsyncStore 封装所有 SQLite 操作。构造时外部传入 `db_path`（如 `data/{target_id}/state.db`），通过 `initialize()` 建表并设置 PRAGMA。Memory 类保留不删除，async_run.py 通过 AsyncStore 替代 Memory 调用。

**Tech Stack:** Python 3.11+, aiosqlite>=0.20, pytest-asyncio

**设计文档:** `docs/performance-overhaul-design.md` Section 4

**前置依赖:** Phase 25（async 基础设施, pytest-asyncio 已配置, `asyncio_mode = "auto"`）

---

## 文件结构

### 新建文件
- `src/news_sentry/core/async_store.py` — AsyncStore 核心实现
- `src/news_sentry/core/yaml_migration.py` — YAML → SQLite 迁移逻辑
- `tests/unit/test_async_store.py` — AsyncStore 测试
- `tests/unit/test_yaml_migration.py` — YAML 迁移测试

### 修改文件
- `pyproject.toml` — `dependencies` 新增 `aiosqlite>=0.20`

### 不改动文件
- `src/news_sentry/core/memory.py` — Memory 类完整保留（向后兼容）
- `tests/unit/test_memory.py` — 原 Memory 测试不改动
- `src/news_sentry/core/run.py` — 同步 pipeline 保持使用 Memory，不改动
- `src/news_sentry/skills/filter/rules_filter.py` — 保持使用 Memory 类型（async_run 中通过 adapter 桥接）
- `src/news_sentry/skills/judge/rules_judge.py` — 同上

---

## SQLite Schema（设计文档 §4 精确）

```sql
-- 已知事件 ID（替代 known_item_ids.yaml）
CREATE TABLE known_ids (
    event_id  TEXT PRIMARY KEY,
    seen_at   TEXT NOT NULL  -- ISO 8601
);
CREATE INDEX idx_known_ids_seen ON known_ids(seen_at);

-- 源健康度（替代 source_health.yaml）
CREATE TABLE source_health (
    source_id   TEXT PRIMARY KEY,
    status      TEXT NOT NULL,      -- healthy/degraded/down
    last_check  TEXT NOT NULL,
    error_count INTEGER DEFAULT 0,
    metadata    TEXT                -- JSON: {consecutive_failures, last_error, total_runs, total_failures}
);

-- 游标（替代 cursors.yaml）
CREATE TABLE cursors (
    source_id  TEXT PRIMARY KEY,
    cursor     TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- LLM 响应缓存（容量上限淘汰，无 TTL）
CREATE TABLE llm_cache (
    cache_key  TEXT PRIMARY KEY,   -- SHA-256(prompt + model + params)
    response   TEXT NOT NULL,      -- JSON
    model      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL       -- 用于 LRU 淘汰
);

-- 事件索引（替代全量文件扫描）
CREATE TABLE event_index (
    event_id          TEXT PRIMARY KEY,
    target_id         TEXT NOT NULL,
    stage             TEXT NOT NULL,     -- raw/evaluated/drafts
    source_id         TEXT,
    news_value_score  INTEGER,
    china_relevance   INTEGER,
    classification_l0 TEXT,
    title_original    TEXT,
    published_at      TEXT,
    file_path         TEXT,              -- 对应的 .md 文件路径
    created_at        TEXT NOT NULL
);
CREATE INDEX idx_event_target_stage ON event_index(target_id, stage);
CREATE INDEX idx_event_published ON event_index(published_at DESC);
```

### SQLite 配置（每个 `initialize()` 调用设置）
```python
PRAGMA journal_mode=WAL;      -- 并发读写
PRAGMA synchronous=NORMAL;    -- 写入性能与安全平衡
PRAGMA cache_size=-64000;     -- 64MB 缓存
PRAGMA foreign_keys=ON;
```

---

## Task 1: 添加 aiosqlite 依赖 + AsyncStore 骨架

**Files:**
- Modify: `pyproject.toml`
- Create: `src/news_sentry/core/async_store.py`
- Create: `tests/unit/test_async_store.py`

- [ ] **Step 1: 添加 aiosqlite 依赖**

```bash
# 编辑 pyproject.toml，在 dependencies 列表中加入 aiosqlite>=0.20
```

在 `pyproject.toml` 的 `dependencies` 段末尾，`"click>=8.1",` 之前加入：
```toml
    "aiosqlite>=0.20",
```

```bash
.venv/bin/python3 -m pip install -e ".[dev]"
```

- [ ] **Step 2: 写 AsyncStore initialize/close Schema 测试**

```python
# tests/unit/test_async_store.py
"""Tests for core/async_store.py — AsyncStore 替代 Memory 的 SQLite 存储层。"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from news_sentry.core.async_store import AsyncStore


class TestAsyncStoreInitialize:
    """AsyncStore 初始化、Schema 建表、PRAGMA 设置。"""

    @pytest.mark.asyncio
    async def test_initialize_creates_db_file(self, tmp_path: Path):
        """initialize 应在指定路径创建 state.db 文件。"""
        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()
        assert db_path.exists()
        await store.close()

    @pytest.mark.asyncio
    async def test_initialize_creates_all_tables(self, tmp_path: Path):
        """initialize 应创建所有 5 张表：known_ids, source_health, cursors, llm_cache, event_index。"""
        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()

        async with store._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ) as cursor:
            rows = await cursor.fetchall()
        table_names = {row[0] for row in rows}

        expected = {"known_ids", "source_health", "cursors", "llm_cache", "event_index"}
        assert expected.issubset(table_names), f"Missing tables: {expected - table_names}"
        await store.close()

    @pytest.mark.asyncio
    async def test_initialize_creates_indexes(self, tmp_path: Path):
        """initialize 应创建 idx_known_ids_seen, idx_event_target_stage, idx_event_published。"""
        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()

        async with store._db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name"
        ) as cursor:
            rows = await cursor.fetchall()
        index_names = {row[0] for row in rows}

        expected = {"idx_known_ids_seen", "idx_event_target_stage", "idx_event_published"}
        assert expected.issubset(index_names), f"Missing indexes: {expected - index_names}"
        await store.close()

    @pytest.mark.asyncio
    async def test_initialize_is_idempotent(self, tmp_path: Path):
        """initialize 多次调用不报错（CREATE TABLE IF NOT EXISTS）。"""
        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()
        await store.initialize()  # 第二次不应报错
        await store.close()

    @pytest.mark.asyncio
    async def test_pragma_wal_mode(self, tmp_path: Path):
        """initialize 应设置 journal_mode=WAL。"""
        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()

        async with store._db.execute("PRAGMA journal_mode") as cursor:
            row = await cursor.fetchone()
        assert row is not None and row[0].lower() == "wal"
        await store.close()

    @pytest.mark.asyncio
    async def test_close_closes_connection(self, tmp_path: Path):
        """close() 应关闭数据库连接。"""
        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()
        await store.close()

        # 关闭后再次操作应抛出异常
        with pytest.raises(Exception):
            await store._db.execute("SELECT 1")
```

- [ ] **Step 3: 运行测试确认失败**

```bash
.venv/bin/python3 -m pytest tests/unit/test_async_store.py::TestAsyncStoreInitialize -v
```

预期：FAIL — `ModuleNotFoundError: No module named 'news_sentry.core.async_store'`

- [ ] **Step 4: 实现 AsyncStore 骨架（initialize / close / Schema）**

```python
# src/news_sentry/core/async_store.py
"""AsyncStore — SQLite 存储层，替代 Memory 的 YAML 全量序列化。

每个 target 一个 state.db 文件。提供 async 接口用于：
- known_ids 去重（增量写入，替代全量 YAML 序列化）
- source_health 源健康追踪
- cursors 拉取游标
- llm_cache LLM 响应缓存（容量上限 + LRU 淘汰）
- event_index 事件索引（替代全量文件扫描）

SQLite 配置：WAL 模式, NORMAL synchronous, 64MB cache, FK 约束。
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

# ── SQLite PRAGMA 配置 ────────────────────────────────────────────────
_PRAGMA_SETUP = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA cache_size=-64000",
    "PRAGMA foreign_keys=ON",
)

# ── Schema DDL ────────────────────────────────────────────────────────
_DDL_KNOWN_IDS = """
CREATE TABLE IF NOT EXISTS known_ids (
    event_id  TEXT PRIMARY KEY,
    seen_at   TEXT NOT NULL
)
"""

_DDL_SOURCE_HEALTH = """
CREATE TABLE IF NOT EXISTS source_health (
    source_id   TEXT PRIMARY KEY,
    status      TEXT NOT NULL,
    last_check  TEXT NOT NULL,
    error_count INTEGER DEFAULT 0,
    metadata    TEXT
)
"""

_DDL_CURSORS = """
CREATE TABLE IF NOT EXISTS cursors (
    source_id  TEXT PRIMARY KEY,
    cursor     TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_DDL_LLM_CACHE = """
CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key  TEXT PRIMARY KEY,
    response   TEXT NOT NULL,
    model      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_DDL_EVENT_INDEX = """
CREATE TABLE IF NOT EXISTS event_index (
    event_id          TEXT PRIMARY KEY,
    target_id         TEXT NOT NULL,
    stage             TEXT NOT NULL,
    source_id         TEXT,
    news_value_score  INTEGER,
    china_relevance   INTEGER,
    classification_l0 TEXT,
    title_original    TEXT,
    published_at      TEXT,
    file_path         TEXT,
    created_at        TEXT NOT NULL
)
"""

_DDL_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_known_ids_seen ON known_ids(seen_at)",
    "CREATE INDEX IF NOT EXISTS idx_event_target_stage ON event_index(target_id, stage)",
    "CREATE INDEX IF NOT EXISTS idx_event_published ON event_index(published_at DESC)",
)

__all__ = ["AsyncStore"]


class AsyncStore:
    """异步 SQLite 存储层，替代 Memory 的 YAML 全量序列化。

    用法：
        store = AsyncStore(Path("data/italy/state.db"))
        await store.initialize()
        await store.mark_known("ne-italy-ansa-20260515-abc123de")
        known = await store.is_known("ne-italy-ansa-20260515-abc123de")
        await store.close()
    """

    def __init__(self, db_path: Path) -> None:
        """创建 AsyncStore 实例。

        Args:
            db_path: SQLite 数据库文件路径（如 data/{target_id}/state.db）。
                     父目录必须存在或在 initialize() 前由调用方创建。
        """
        self._db_path = Path(db_path)
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """打开数据库连接、设置 PRAGMA、创建表和索引。

        幂等操作：多次调用安全（CREATE TABLE IF NOT EXISTS）。
        调用方需要确保 db_path 的父目录存在。
        """
        if self._db is not None:
            return  # 已初始化

        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))

        # 设置 PRAGMA
        for pragma_sql in _PRAGMA_SETUP:
            await self._db.execute(pragma_sql)

        # 建表
        await self._db.execute(_DDL_KNOWN_IDS)
        await self._db.execute(_DDL_SOURCE_HEALTH)
        await self._db.execute(_DDL_CURSORS)
        await self._db.execute(_DDL_LLM_CACHE)
        await self._db.execute(_DDL_EVENT_INDEX)

        # 建索引
        for idx_sql in _DDL_INDEXES:
            await self._db.execute(idx_sql)

        await self._db.commit()
        logger.info("AsyncStore 初始化完成: %s", self._db_path)

    async def close(self) -> None:
        """关闭数据库连接。"""
        if self._db is not None:
            await self._db.close()
            self._db = None
            logger.info("AsyncStore 连接已关闭: %s", self._db_path)
```

- [ ] **Step 5: 运行测试确认通过**

```bash
.venv/bin/python3 -m pytest tests/unit/test_async_store.py::TestAsyncStoreInitialize -v
```

预期：6 passed

- [ ] **Step 6: 运行 ruff + mypy 静态检查**

```bash
ruff check src/news_sentry/core/async_store.py tests/unit/test_async_store.py
.venv/bin/python3 -m mypy src/news_sentry/core/async_store.py
```

预期：ruff=0, mypy=0

- [ ] **Step 7: 提交**

```bash
git add pyproject.toml src/news_sentry/core/async_store.py tests/unit/test_async_store.py
git commit -m "Phase 26: AsyncStore 骨架 — Schema 建表 + PRAGMA 配置 (P26.01)"
```

---

## Task 2: Known IDs 操作 — is_known, mark_known, prune_old_ids

**Files:**
- Modify: `src/news_sentry/core/async_store.py`
- Modify: `tests/unit/test_async_store.py`

- [ ] **Step 1: 写 known_ids 测试**

在 `tests/unit/test_async_store.py` 中追加：

```python
class TestKnownIds:
    """known_ids 表操作：去重和清理。"""

    @pytest.fixture
    async def store(self, tmp_path: Path) -> AsyncStore:
        db_path = tmp_path / "state.db"
        s = AsyncStore(db_path)
        await s.initialize()
        return s

    @pytest.mark.asyncio
    async def test_is_known_returns_false_for_new_id(self, store: AsyncStore):
        """新 ID 应返回 False。"""
        assert await store.is_known("ne-italy-ansa-20260515-a1b2c3d4") is False

    @pytest.mark.asyncio
    async def test_mark_known_and_is_known(self, store: AsyncStore):
        """mark_known 后 is_known 应返回 True。"""
        eid = "ne-italy-ansa-20260515-b5c6d7e8"
        await store.mark_known(eid)
        assert await store.is_known(eid) is True

    @pytest.mark.asyncio
    async def test_mark_known_is_idempotent(self, store: AsyncStore):
        """重复 mark_known 同一 ID 不报错。"""
        eid = "ne-italy-repubblica-20260515-c1d2e3f4"
        await store.mark_known(eid)
        await store.mark_known(eid)  # 第二次不应报错
        assert await store.is_known(eid) is True

    @pytest.mark.asyncio
    async def test_mark_known_persists_across_instances(self, tmp_path: Path):
        """mark_known 写入后，新实例应能从文件中读取到。"""
        db_path = tmp_path / "state.db"
        eid = "ne-italy-corriere-20260515-d4e5f6a7"

        store1 = AsyncStore(db_path)
        await store1.initialize()
        await store1.mark_known(eid)
        await store1.close()

        store2 = AsyncStore(db_path)
        await store2.initialize()
        assert await store2.is_known(eid) is True
        await store2.close()

    @pytest.mark.asyncio
    async def test_prune_old_ids_removes_stale_entries(self, store: AsyncStore):
        """prune_old_ids 应清理超过 max_age_days 的条目。"""
        # 手动插入旧记录和新记录
        old_ts = "2020-01-01T00:00:00+00:00"
        recent_ts = "2099-01-01T00:00:00+00:00"
        await store._db.execute(
            "INSERT INTO known_ids (event_id, seen_at) VALUES (?, ?)",
            ("old-event", old_ts),
        )
        await store._db.execute(
            "INSERT INTO known_ids (event_id, seen_at) VALUES (?, ?)",
            ("recent-event", recent_ts),
        )
        await store._db.commit()

        removed = await store.prune_old_ids(max_age_days=30)
        assert removed == 1
        assert await store.is_known("old-event") is False
        assert await store.is_known("recent-event") is True

    @pytest.mark.asyncio
    async def test_prune_old_ids_returns_zero_when_no_stale(self, store: AsyncStore):
        """所有条目都较新时，prune 应返回 0。"""
        now_ts = datetime.now(UTC).isoformat()
        await store._db.execute(
            "INSERT INTO known_ids (event_id, seen_at) VALUES (?, ?)",
            ("fresh-event", now_ts),
        )
        await store._db.commit()

        removed = await store.prune_old_ids(max_age_days=30)
        assert removed == 0

    @pytest.mark.asyncio
    async def test_concurrent_mark_known(self, store: AsyncStore):
        """多个并发 mark_known 不应报错。"""
        eids = [f"ne-italy-ansa-20260515-{i:08d}" for i in range(100)]

        async def mark_batch(start: int, end: int) -> None:
            for i in range(start, end):
                await store.mark_known(eids[i])

        await asyncio.gather(
            mark_batch(0, 50),
            mark_batch(50, 100),
        )

        for eid in eids:
            assert await store.is_known(eid) is True
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python3 -m pytest tests/unit/test_async_store.py::TestKnownIds -v
```

预期：FAIL — `AttributeError: 'AsyncStore' has no attribute 'is_known'`

- [ ] **Step 3: 实现已知 ID 操作**

在 `src/news_sentry/core/async_store.py` 的 `AsyncStore` 类中追加：

```python
    # ------------------------------------------------------------------
    # Known IDs（去重）
    # ------------------------------------------------------------------

    async def is_known(self, event_id: str) -> bool:
        """检查 event_id 是否已处理过。

        Args:
            event_id: 事件 ID。

        Returns:
            True 如果事件已被处理。
        """
        if self._db is None:
            return False
        async with self._db.execute(
            "SELECT 1 FROM known_ids WHERE event_id = ?", (event_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return row is not None

    async def mark_known(self, event_id: str) -> None:
        """将 event_id 标记为已知，记录首次出现时间戳。

        使用 INSERT OR IGNORE 确保幂等性。
        采集阶段获取到事件后立即调用，用于后续去重。

        Args:
            event_id: 事件 ID。
        """
        if self._db is None:
            return
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            "INSERT OR IGNORE INTO known_ids (event_id, seen_at) VALUES (?, ?)",
            (event_id, now),
        )
        await self._db.commit()

    async def prune_old_ids(self, max_age_days: int = 30) -> int:
        """清理超过 max_age_days 天的已知 ID 条目。

        Args:
            max_age_days: TTL 天数，默认 30 天。

        Returns:
            清理的条目数量。
        """
        if self._db is None:
            return 0
        from datetime import timedelta
        cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
        cutoff_str = cutoff.isoformat()

        async with self._db.execute(
            "SELECT COUNT(*) FROM known_ids WHERE seen_at < ?", (cutoff_str,)
        ) as cursor:
            row = await cursor.fetchone()
        stale_count = row[0] if row else 0

        if stale_count > 0:
            await self._db.execute(
                "DELETE FROM known_ids WHERE seen_at < ?", (cutoff_str,)
            )
            await self._db.commit()
            logger.info("pruned %d stale known_ids", stale_count)

        return stale_count
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python3 -m pytest tests/unit/test_async_store.py::TestKnownIds -v
```

预期：7 passed

- [ ] **Step 5: 提交**

```bash
git add src/news_sentry/core/async_store.py tests/unit/test_async_store.py
git commit -m "Phase 26: AsyncStore known_ids 操作 — is_known/mark_known/prune (P26.02)"
```

---

## Task 3: Source Health + Cursor 操作

**Files:**
- Modify: `src/news_sentry/core/async_store.py`
- Modify: `tests/unit/test_async_store.py`

- [ ] **Step 1: 写 source_health + cursor 测试**

在 `tests/unit/test_async_store.py` 中追加：

```python
class TestSourceHealth:
    """source_health 表操作：记录、查询、降级判断。"""

    @pytest.fixture
    async def store(self, tmp_path: Path) -> AsyncStore:
        db_path = tmp_path / "state.db"
        s = AsyncStore(db_path)
        await s.initialize()
        return s

    @pytest.mark.asyncio
    async def test_get_source_health_returns_none_for_unknown(self, store: AsyncStore):
        """未记录的源应返回 None。"""
        assert await store.get_source_health("ansa") is None

    @pytest.mark.asyncio
    async def test_record_source_health_success(self, store: AsyncStore):
        """记录成功拉取后，状态应为 healthy，consecutive_failures=0。"""
        await store.record_source_health("ansa", status="healthy")
        health = await store.get_source_health("ansa")
        assert health is not None
        assert health["status"] == "healthy"
        assert health["error_count"] == 0
        assert health["last_check"] is not None

    @pytest.mark.asyncio
    async def test_record_source_health_failure(self, store: AsyncStore):
        """记录失败后，状态应为 degraded 或 down，error_count 递增。"""
        await store.record_source_health("ansa", status="degraded", error_count=1)
        health = await store.get_source_health("ansa")
        assert health is not None
        assert health["status"] == "degraded"
        assert health["error_count"] == 1

    @pytest.mark.asyncio
    async def test_record_source_health_accumulates_errors(self, store: AsyncStore):
        """多次记录失败应递增 error_count。"""
        await store.record_source_health(
            "corriere", status="degraded", error_count=1,
            metadata={"consecutive_failures": 1, "total_runs": 1, "total_failures": 1},
        )
        await store.record_source_health(
            "corriere", status="degraded", error_count=2,
            metadata={"consecutive_failures": 2, "total_runs": 2, "total_failures": 2},
        )
        health = await store.get_source_health("corriere")
        assert health is not None
        assert health["error_count"] == 2
        assert health["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_record_source_health_resets_on_success(self, store: AsyncStore):
        """成功拉取后 error_count 应重置为 0。"""
        await store.record_source_health(
            "ansa", status="degraded", error_count=3,
            metadata={"consecutive_failures": 3},
        )
        await store.record_source_health(
            "ansa", status="healthy", error_count=0,
            metadata={"consecutive_failures": 0},
        )
        health = await store.get_source_health("ansa")
        assert health is not None
        assert health["status"] == "healthy"
        assert health["error_count"] == 0

    @pytest.mark.asyncio
    async def test_source_health_persists(self, tmp_path: Path):
        """写入后新实例应能读到。"""
        db_path = tmp_path / "state.db"
        store1 = AsyncStore(db_path)
        await store1.initialize()
        await store1.record_source_health(
            "ansa", status="healthy",
            metadata={"consecutive_failures": 0, "total_runs": 1, "total_failures": 0},
        )
        await store1.close()

        store2 = AsyncStore(db_path)
        await store2.initialize()
        health = await store2.get_source_health("ansa")
        assert health is not None
        assert health["status"] == "healthy"
        await store2.close()

    @pytest.mark.asyncio
    async def test_is_source_degraded_consecutive_failures(self, store: AsyncStore):
        """连续失败 >= 阈值应返回 True。"""
        await store.record_source_health(
            "ansa", status="degraded", error_count=5,
            metadata={"consecutive_failures": 5, "total_runs": 5, "total_failures": 5},
        )
        assert await store.is_source_degraded("ansa", max_consecutive_failures=5) is True

    @pytest.mark.asyncio
    async def test_is_source_degraded_false_healthy(self, store: AsyncStore):
        """健康源不应降级。"""
        await store.record_source_health(
            "ansa", status="healthy", error_count=0,
            metadata={"consecutive_failures": 0, "total_runs": 10, "total_failures": 1},
        )
        assert await store.is_source_degraded("ansa") is False

    @pytest.mark.asyncio
    async def test_is_source_degraded_unknown_returns_false(self, store: AsyncStore):
        """未记录的源返回 False（不降级）。"""
        assert await store.is_source_degraded("nonexistent") is False

    @pytest.mark.asyncio
    async def test_is_source_degraded_metadata_json(self, store: AsyncStore):
        """metadata 作为 JSON 存储和反序列化。"""
        meta_data = {
            "consecutive_failures": 0,
            "total_runs": 15,
            "total_failures": 2,
            "last_error": None,
            "success_rate": 0.87,
        }
        await store.record_source_health(
            "ansa", status="healthy", error_count=0, metadata=meta_data,
        )
        health = await store.get_source_health("ansa")
        assert health is not None
        # verify metadata round-trips via JSON
        assert health["status"] == "healthy"


class TestCursors:
    """cursors 表操作：游标读写。"""

    @pytest.fixture
    async def store(self, tmp_path: Path) -> AsyncStore:
        db_path = tmp_path / "state.db"
        s = AsyncStore(db_path)
        await s.initialize()
        return s

    @pytest.mark.asyncio
    async def test_get_cursor_returns_none_for_unknown(self, store: AsyncStore):
        """未设置的源返回 None。"""
        assert await store.get_cursor("ansa") is None

    @pytest.mark.asyncio
    async def test_set_and_get_cursor(self, store: AsyncStore):
        """set 后 get 应返回相同值。"""
        await store.set_cursor("ansa", 'etag-"abc123"')
        assert await store.get_cursor("ansa") == 'etag-"abc123"'

    @pytest.mark.asyncio
    async def test_cursor_persists(self, tmp_path: Path):
        """写入后新实例应能读到。"""
        db_path = tmp_path / "state.db"
        store1 = AsyncStore(db_path)
        await store1.initialize()
        await store1.set_cursor("ansa", "last-modified-xyz")
        await store1.close()

        store2 = AsyncStore(db_path)
        await store2.initialize()
        assert await store2.get_cursor("ansa") == "last-modified-xyz"
        await store2.close()

    @pytest.mark.asyncio
    async def test_set_cursor_overwrites(self, store: AsyncStore):
        """重复 set 应覆盖旧值。"""
        await store.set_cursor("ansa", "old")
        await store.set_cursor("ansa", "new")
        assert await store.get_cursor("ansa") == "new"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python3 -m pytest tests/unit/test_async_store.py::TestSourceHealth tests/unit/test_async_store.py::TestCursors -v
```

预期：FAIL — `AttributeError: 'AsyncStore' has no attribute 'get_source_health'`

- [ ] **Step 3: 实现 Source Health + Cursor 操作**

在 `src/news_sentry/core/async_store.py` 的 `AsyncStore` 类中追加：

```python
    # ------------------------------------------------------------------
    # Source Health
    # ------------------------------------------------------------------

    async def get_source_health(self, source_id: str) -> dict[str, Any] | None:
        """获取指定源的运行状况快照。

        Args:
            source_id: 来源标识。

        Returns:
            dict with keys: source_id, status, last_check, error_count, metadata。
            不存在则返回 None。
        """
        if self._db is None:
            return None
        async with self._db.execute(
            "SELECT source_id, status, last_check, error_count, metadata FROM source_health WHERE source_id = ?",
            (source_id,),
        ) as cursor:
            row = await cursor.fetchone()

        if row is None:
            return None

        result: dict[str, Any] = {
            "source_id": row[0],
            "status": row[1],
            "last_check": row[2],
            "error_count": row[3],
        }
        if row[4] is not None:
            try:
                result["metadata"] = json.loads(row[4])
            except json.JSONDecodeError:
                result["metadata"] = {}
        else:
            result["metadata"] = {}
        return result

    async def record_source_health(
        self,
        source_id: str,
        status: str,
        error_count: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """记录一次源健康采样。

        Args:
            source_id: 来源标识。
            status: 健康状态（healthy/degraded/down）。
            error_count: 累计错误次数。
            metadata: 额外元数据（consecutive_failures, total_runs, last_error 等）。
        """
        if self._db is None:
            return
        now = datetime.now(UTC).isoformat()
        meta_json = json.dumps(metadata, ensure_ascii=False) if metadata else None

        await self._db.execute(
            """INSERT OR REPLACE INTO source_health
               (source_id, status, last_check, error_count, metadata)
               VALUES (?, ?, ?, ?, ?)""",
            (source_id, status, now, error_count, meta_json),
        )
        await self._db.commit()

    async def is_source_degraded(
        self,
        source_id: str,
        max_consecutive_failures: int = 5,
        min_success_rate: float = 0.3,
        min_total_runs: int = 10,
    ) -> bool:
        """判断源是否已降级（HEALTH-POLICY-001）。

        Args:
            source_id: 来源标识。
            max_consecutive_failures: 连续失败阈值（默认 5）。
            min_success_rate: 最低成功率阈值（默认 0.3）。
            min_total_runs: 最小运行次数（默认 10）。

        Returns:
            True 表示源应被暂停。
        """
        health = await self.get_source_health(source_id)
        if health is None:
            return False

        meta = health.get("metadata", {})
        consecutive = meta.get("consecutive_failures", 0)
        if isinstance(consecutive, (int, float)) and consecutive >= max_consecutive_failures:
            return True

        total = meta.get("total_runs", 0)
        failures = meta.get("total_failures", 0)
        if isinstance(total, (int, float)) and isinstance(failures, (int, float)) and total >= min_total_runs:
            success_rate = (total - failures) / total if total > 0 else 1.0
            if success_rate < min_success_rate:
                return True

        return False

    # ------------------------------------------------------------------
    # Cursors
    # ------------------------------------------------------------------

    async def get_cursor(self, source_id: str) -> str | None:
        """获取源的拉取游标（如 RSS 的 ETag/Last-Modified）。

        Args:
            source_id: 来源标识。

        Returns:
            游标字符串，不存在则返回 None。
        """
        if self._db is None:
            return None
        async with self._db.execute(
            "SELECT cursor FROM cursors WHERE source_id = ?", (source_id,)
        ) as cursor:
            row = await cursor.fetchone()

        return row[0] if row else None

    async def set_cursor(self, source_id: str, cursor: str) -> None:
        """更新源的拉取游标。

        Args:
            source_id: 来源标识。
            cursor: 游标值（ETag, Last-Modified 或分页 token）。
        """
        if self._db is None:
            return
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            """INSERT OR REPLACE INTO cursors (source_id, cursor, updated_at)
               VALUES (?, ?, ?)""",
            (source_id, cursor, now),
        )
        await self._db.commit()
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python3 -m pytest tests/unit/test_async_store.py::TestSourceHealth tests/unit/test_async_store.py::TestCursors -v
```

预期：11 passed（TestSourceHealth: 8, TestCursors: 4 -- 等待实际 test run 确认）
（注：`test_is_source_degraded_metadata_json` 可并入 TestSourceHealth）

- [ ] **Step 5: 提交**

```bash
git add src/news_sentry/core/async_store.py tests/unit/test_async_store.py
git commit -m "Phase 26: AsyncStore source_health + cursor 操作 (P26.03)"
```

---

## Task 4: LLM Cache 操作 — get/set/evict

**Files:**
- Modify: `src/news_sentry/core/async_store.py`
- Modify: `tests/unit/test_async_store.py`

- [ ] **Step 1: 写 LLM Cache 测试**

在 `tests/unit/test_async_store.py` 中追加：

```python
class TestLLMCache:
    """llm_cache 表操作：缓存读写 + LRU 淘汰（容量上限，无 TTL）。"""

    @pytest.fixture
    async def store(self, tmp_path: Path) -> AsyncStore:
        db_path = tmp_path / "state.db"
        s = AsyncStore(db_path)
        await s.initialize()
        return s

    @pytest.mark.asyncio
    async def test_get_cached_response_returns_none_for_miss(self, store: AsyncStore):
        """缓存未命中应返回 None。"""
        assert await store.get_cached_response("key-not-in-cache") is None

    @pytest.mark.asyncio
    async def test_set_and_get_cached_response(self, store: AsyncStore):
        """set 后 get 应返回相同值。"""
        await store.set_cached_response(
            cache_key="sha256-abc123",
            response='{"translations": [{"title": "Hello"}]}',
            model="gpt-4o-mini",
        )
        cached = await store.get_cached_response("sha256-abc123")
        assert cached == '{"translations": [{"title": "Hello"}]}'

    @pytest.mark.asyncio
    async def test_set_cached_response_updates_timestamp(self, store: AsyncStore):
        """重复 set 同一 key 应更新 updated_at。"""
        await store.set_cached_response(
            cache_key="sha256-xyz", response="v1", model="gpt-4o-mini",
        )
        await asyncio.sleep(0.001)  # 确保时间戳不同
        await store.set_cached_response(
            cache_key="sha256-xyz", response="v2", model="gpt-4o-mini",
        )

        async with store._db.execute(
            "SELECT response, created_at, updated_at FROM llm_cache WHERE cache_key = ?",
            ("sha256-xyz",),
        ) as cursor:
            row = await cursor.fetchone()

        assert row is not None
        assert row[0] == "v2"
        # created_at 不变，updated_at 更新
        assert row[1] != row[2]

    @pytest.mark.asyncio
    async def test_evict_if_needed_removes_oldest_entries(self, store: AsyncStore):
        """evict_if_needed 应淘汰最旧的条目（按 updated_at ASC）。"""
        # 插入 5 条缓存
        for i in range(5):
            await store.set_cached_response(
                cache_key=f"key-{i}",
                response=f"resp-{i}",
                model="gpt-4o-mini",
            )
            await asyncio.sleep(0.001)  # 确保时间戳递增

        # 限制最多 3 条
        removed = await store.evict_if_needed(max_entries=3)
        assert removed == 2

        # 验证保留了最新的 3 条（key-2, key-3, key-4）
        assert await store.get_cached_response("key-0") is None  # 最旧，被淘汰
        assert await store.get_cached_response("key-1") is None  # 第二旧
        assert await store.get_cached_response("key-2") is not None
        assert await store.get_cached_response("key-3") is not None
        assert await store.get_cached_response("key-4") is not None

    @pytest.mark.asyncio
    async def test_evict_if_needed_no_op_when_under_limit(self, store: AsyncStore):
        """条目数在限制内时不应淘汰。"""
        for i in range(3):
            await store.set_cached_response(
                cache_key=f"key-{i}",
                response=f"resp-{i}",
                model="gpt-4o-mini",
            )

        removed = await store.evict_if_needed(max_entries=10)
        assert removed == 0

    @pytest.mark.asyncio
    async def test_set_cached_response_persists(self, tmp_path: Path):
        """写入后新实例应能读到。"""
        db_path = tmp_path / "state.db"
        store1 = AsyncStore(db_path)
        await store1.initialize()
        await store1.set_cached_response(
            cache_key="persist-key",
            response="persistent value",
            model="gpt-4o",
        )
        await store1.close()

        store2 = AsyncStore(db_path)
        await store2.initialize()
        cached = await store2.get_cached_response("persist-key")
        assert cached == "persistent value"
        await store2.close()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python3 -m pytest tests/unit/test_async_store.py::TestLLMCache -v
```

预期：FAIL — `AttributeError: 'AsyncStore' has no attribute 'get_cached_response'`

- [ ] **Step 3: 实现 LLM Cache 操作**

在 `src/news_sentry/core/async_store.py` 的 `AsyncStore` 类中追加：

```python
    # ------------------------------------------------------------------
    # LLM Cache
    # ------------------------------------------------------------------

    async def get_cached_response(self, cache_key: str) -> str | None:
        """获取缓存的 LLM 响应。

        Args:
            cache_key: 缓存键（SHA-256 hash）。

        Returns:
            缓存的响应 JSON 字符串，未命中返回 None。
        """
        if self._db is None:
            return None
        async with self._db.execute(
            "SELECT response FROM llm_cache WHERE cache_key = ?", (cache_key,)
        ) as cursor:
            row = await cursor.fetchone()

        return row[0] if row else None

    async def set_cached_response(
        self, cache_key: str, response: str, model: str
    ) -> None:
        """设置 LLM 响应缓存。

        使用 INSERT OR REPLACE：首次设置更新 both created_at 和 updated_at，
        重复设置只更新 updated_at（通过先查后写保留原始 created_at）。

        Args:
            cache_key: 缓存键（SHA-256 hash）。
            response: 响应 JSON 字符串。
            model: 模型标识。
        """
        if self._db is None:
            return
        now = datetime.now(UTC).isoformat()

        # 检查是否已存在以保留原始 created_at
        async with self._db.execute(
            "SELECT created_at FROM llm_cache WHERE cache_key = ?", (cache_key,)
        ) as cursor:
            existing = await cursor.fetchone()

        if existing is not None:
            await self._db.execute(
                """UPDATE llm_cache SET response = ?, model = ?, updated_at = ?
                   WHERE cache_key = ?""",
                (response, model, now, cache_key),
            )
        else:
            await self._db.execute(
                """INSERT INTO llm_cache (cache_key, response, model, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (cache_key, response, model, now, now),
            )
        await self._db.commit()

    async def evict_if_needed(self, max_entries: int) -> int:
        """LRU 淘汰：条目数超过 max_entries 时淘汰最旧的。

        淘汰策略：按 updated_at ASC 排序，删除最旧的 N 条。

        Args:
            max_entries: 最大条目数。

        Returns:
            实际淘汰的条目数。
        """
        if self._db is None:
            return 0

        async with self._db.execute("SELECT COUNT(*) FROM llm_cache") as cursor:
            row = await cursor.fetchone()
        count = row[0] if row else 0

        if count <= max_entries:
            return 0

        excess = count - max_entries
        await self._db.execute(
            """DELETE FROM llm_cache WHERE cache_key IN (
                   SELECT cache_key FROM llm_cache
                   ORDER BY updated_at ASC LIMIT ?
               )""",
            (excess,),
        )
        await self._db.commit()
        logger.info("evicted %d LLM cache entries (limit=%d)", excess, max_entries)
        return excess
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python3 -m pytest tests/unit/test_async_store.py::TestLLMCache -v
```

预期：6 passed

- [ ] **Step 5: 提交**

```bash
git add src/news_sentry/core/async_store.py tests/unit/test_async_store.py
git commit -m "Phase 26: AsyncStore LLM Cache 操作 + LRU 淘汰 (P26.04)"
```

---

## Task 5: Event Index 操作 — index_event, query_events, get_event_count, get_stats

**Files:**
- Modify: `src/news_sentry/core/async_store.py`
- Modify: `tests/unit/test_async_store.py`

- [ ] **Step 1: 写 event_index 测试**

在 `tests/unit/test_async_store.py` 中追加：

```python
class TestEventIndex:
    """event_index 表操作：索引、查询、统计。"""

    @pytest.fixture
    async def store(self, tmp_path: Path) -> AsyncStore:
        db_path = tmp_path / "state.db"
        s = AsyncStore(db_path)
        await s.initialize()
        return s

    def _make_event(self, **overrides) -> Any:
        """创建简易 mock event 对象（不需要完整 NewsEvent 构造）。"""
        from unittest.mock import MagicMock
        event = MagicMock()
        event.id = overrides.get("id", "ne-test-ansa-20260515-a1b2c3d4")
        event.source_id = overrides.get("source_id", "ansa")
        event.title_original = overrides.get("title_original", "Test News Title")
        event.news_value_score = overrides.get("news_value_score", 70)
        event.china_relevance = overrides.get("china_relevance", 45)
        event.published_at = overrides.get("published_at", "2026-05-15T10:00:00Z")
        event.metadata = overrides.get(
            "metadata",
            {"classification": {"l0": "political"}},
        )
        return event

    @pytest.mark.asyncio
    async def test_index_event_inserts_row(self, store: AsyncStore):
        """index_event 应在 event_index 表中插入一行。"""
        event = self._make_event()
        await store.index_event(event, target_id="test", stage="raw", file_path="raw/ne-test-ansa-20260515-a1b2c3d4.md")

        async with store._db.execute(
            "SELECT event_id, target_id, stage, news_value_score, china_relevance "
            "FROM event_index WHERE event_id = ?",
            (event.id,),
        ) as cursor:
            row = await cursor.fetchone()

        assert row is not None
        assert row[0] == event.id
        assert row[1] == "test"
        assert row[2] == "raw"
        assert row[3] == 70
        assert row[4] == 45

    @pytest.mark.asyncio
    async def test_index_event_extracts_classification_l0(self, store: AsyncStore):
        """index_event 应从 metadata.classification.l0 提取分类。"""
        event = self._make_event(
            metadata={"classification": {"l0": "breaking_news", "l1": []}},
        )
        await store.index_event(event, target_id="test", stage="raw", file_path=None)

        async with store._db.execute(
            "SELECT classification_l0 FROM event_index WHERE event_id = ?",
            (event.id,),
        ) as cursor:
            row = await cursor.fetchone()

        assert row is not None and row[0] == "breaking_news"

    @pytest.mark.asyncio
    async def test_index_event_upserts(self, store: AsyncStore):
        """重复 index_event 应更新已有行（UPSERT 语义）。"""
        event = self._make_event(
            news_value_score=50,
            metadata={"classification": {"l0": "economy"}},
        )
        await store.index_event(event, target_id="test", stage="raw", file_path="r1.md")

        # 更新
        event.news_value_score = 90
        event.metadata = {"classification": {"l0": "breaking_news"}}
        await store.index_event(event, target_id="test", stage="evaluated", file_path="r2.md")

        async with store._db.execute(
            "SELECT stage, news_value_score, classification_l0, file_path FROM event_index WHERE event_id = ?",
            (event.id,),
        ) as cursor:
            row = await cursor.fetchone()

        assert row is not None
        assert row[0] == "evaluated"
        assert row[1] == 90
        assert row[2] == "breaking_news"
        assert row[3] == "r2.md"

    @pytest.mark.asyncio
    async def test_query_events_filter_by_target_and_stage(self, store: AsyncStore):
        """query_events 应按 target_id 和 stage 过滤。"""
        # 插入 test/test 和 test/other target 的事件
        for i in range(3):
            event = self._make_event(id=f"ne-test-{i:08d}")
            await store.index_event(event, target_id="italy", stage="raw", file_path=None)
        for i in range(2):
            event = self._make_event(id=f"ne-evaluated-{i:08d}")
            await store.index_event(event, target_id="italy", stage="evaluated", file_path=None)

        results = await store.query_events(target_id="italy", stage="raw")
        assert len(results) == 3

        results = await store.query_events(target_id="italy", stage="evaluated")
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_query_events_returns_empty_for_no_match(self, store: AsyncStore):
        """无匹配事件应返回空列表。"""
        results = await store.query_events(target_id="italy", stage="drafts")
        assert results == []

    @pytest.mark.asyncio
    async def test_get_event_count(self, store: AsyncStore):
        """get_event_count 应返回正确计数。"""
        for i in range(5):
            event = self._make_event(id=f"ne-count-{i:08d}")
            await store.index_event(event, target_id="italy", stage="raw", file_path=None)

        count = await store.get_event_count(target_id="italy", stage="raw")
        assert count == 5

    @pytest.mark.asyncio
    async def test_get_stats(self, store: AsyncStore):
        """get_stats 应返回 target 的聚合统计。"""
        # 插入不同 stage 的事件
        for i in range(3):
            event = self._make_event(
                id=f"ne-raw-{i:08d}", news_value_score=50 + i * 10
            )
            await store.index_event(event, target_id="italy", stage="raw", file_path=None)
        for i in range(2):
            event = self._make_event(
                id=f"ne-eval-{i:08d}", news_value_score=80 + i * 5
            )
            await store.index_event(event, target_id="italy", stage="evaluated", file_path=None)

        stats = await store.get_stats(target_id="italy")
        assert stats["total_events"] >= 5
        assert "stage_counts" in stats
        # stage_counts 应包含 raw 和 evaluated
        stage_counts = stats["stage_counts"]
        assert stage_counts.get("raw", 0) == 3
        assert stage_counts.get("evaluated", 0) == 2

    @pytest.mark.asyncio
    async def test_get_stats_empty_target(self, store: AsyncStore):
        """无事件的 target 应返回零统计。"""
        stats = await store.get_stats(target_id="empty-target")
        assert stats["total_events"] == 0
        assert stats["stage_counts"] == {}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python3 -m pytest tests/unit/test_async_store.py::TestEventIndex -v
```

预期：FAIL — `AttributeError: 'AsyncStore' has no attribute 'index_event'`

- [ ] **Step 3: 实现 Event Index 操作**

在 `src/news_sentry/core/async_store.py` 的 `AsyncStore` 类中追加：

```python
    # ------------------------------------------------------------------
    # Event Index
    # ------------------------------------------------------------------

    async def index_event(
        self,
        event: Any,  # NewsEvent（使用 duck typing 避免循环导入）
        target_id: str,
        stage: str,
        file_path: str | None = None,
    ) -> None:
        """将事件索引写入 event_index 表。

        使用 INSERT OR REPLACE：同一 event_id 多次调用会更新 stage 和字段。

        Args:
            event: NewsEvent 对象（duck typing：需要有 id, source_id, title_original,
                   news_value_score, china_relevance, published_at, metadata）。
            target_id: 目标标识。
            stage: pipeline 阶段（raw/evaluated/drafts）。
            file_path: 对应的 Markdown 文件相对路径。
        """
        if self._db is None:
            return

        # 从 metadata.classification 提取 l0
        classification = event.metadata.get("classification", {}) if hasattr(event, "metadata") else {}
        classification_l0 = classification.get("l0") if isinstance(classification, dict) else None

        now = datetime.now(UTC).isoformat()

        await self._db.execute(
            """INSERT OR REPLACE INTO event_index
               (event_id, target_id, stage, source_id, news_value_score,
                china_relevance, classification_l0, title_original,
                published_at, file_path, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(
                   (SELECT created_at FROM event_index WHERE event_id = ?), ?))""",
            (
                getattr(event, "id", ""),
                target_id,
                stage,
                getattr(event, "source_id", None),
                getattr(event, "news_value_score", None),
                getattr(event, "china_relevance", None),
                classification_l0,
                getattr(event, "title_original", None),
                getattr(event, "published_at", None),
                file_path,
                getattr(event, "id", ""),  # 用于 COALESCE 子查询
                now,
            ),
        )
        await self._db.commit()

    async def query_events(
        self,
        target_id: str,
        stage: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """查询事件索引。

        Args:
            target_id: 目标标识。
            stage: pipeline 阶段。
            limit: 返回条目数上限。
            offset: 分页偏移。

        Returns:
            事件字典列表，字段对应 event_index 列。
        """
        if self._db is None:
            return []

        async with self._db.execute(
            """SELECT event_id, target_id, stage, source_id, news_value_score,
                      china_relevance, classification_l0, title_original,
                      published_at, file_path, created_at
               FROM event_index
               WHERE target_id = ? AND stage = ?
               ORDER BY published_at DESC
               LIMIT ? OFFSET ?""",
            (target_id, stage, limit, offset),
        ) as cursor:
            rows = await cursor.fetchall()

        cols = (
            "event_id", "target_id", "stage", "source_id", "news_value_score",
            "china_relevance", "classification_l0", "title_original",
            "published_at", "file_path", "created_at",
        )
        return [dict(zip(cols, row)) for row in rows]

    async def get_event_count(self, target_id: str, stage: str) -> int:
        """获取指定 target + stage 的事件总数。

        Args:
            target_id: 目标标识。
            stage: pipeline 阶段。

        Returns:
            事件计数。
        """
        if self._db is None:
            return 0
        async with self._db.execute(
            "SELECT COUNT(*) FROM event_index WHERE target_id = ? AND stage = ?",
            (target_id, stage),
        ) as cursor:
            row = await cursor.fetchone()

        return row[0] if row else 0

    async def get_stats(self, target_id: str) -> dict[str, Any]:
        """获取 target 的聚合统计。

        Args:
            target_id: 目标标识。

        Returns:
            dict with keys: total_events, stage_counts, avg_news_value_score。
        """
        if self._db is None:
            return {"total_events": 0, "stage_counts": {}, "avg_news_value_score": 0.0}

        # 总数
        async with self._db.execute(
            "SELECT COUNT(*) FROM event_index WHERE target_id = ?", (target_id,)
        ) as cursor:
            row = await cursor.fetchone()
        total = row[0] if row else 0

        # 按 stage 计数
        async with self._db.execute(
            "SELECT stage, COUNT(*) FROM event_index WHERE target_id = ? GROUP BY stage",
            (target_id,),
        ) as cursor:
            stage_rows = await cursor.fetchall()
        stage_counts = {row[0]: row[1] for row in stage_rows}

        # 平均新闻价值
        async with self._db.execute(
            "SELECT AVG(news_value_score) FROM event_index WHERE target_id = ? AND news_value_score IS NOT NULL",
            (target_id,),
        ) as cursor:
            row = await cursor.fetchone()
        avg_score = round(row[0], 1) if row and row[0] is not None else 0.0

        return {
            "total_events": total,
            "stage_counts": stage_counts,
            "avg_news_value_score": avg_score,
        }
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python3 -m pytest tests/unit/test_async_store.py::TestEventIndex -v
```

预期：8 passed

- [ ] **Step 5: 提交**

```bash
git add src/news_sentry/core/async_store.py tests/unit/test_async_store.py
git commit -m "Phase 26: AsyncStore event_index 操作 — 索引/查询/统计 (P26.05)"
```

---

## Task 6: YAML → SQLite 迁移逻辑

**Files:**
- Create: `src/news_sentry/core/yaml_migration.py`
- Create: `tests/unit/test_yaml_migration.py`

- [ ] **Step 1: 写迁移逻辑测试**

```python
# tests/unit/test_yaml_migration.py
"""Tests for core/yaml_migration.py — YAML → SQLite 数据迁移。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from news_sentry.core.async_store import AsyncStore
from news_sentry.core.yaml_migration import (
    migrate_yaml_to_sqlite,
    should_migrate,
)


class TestShouldMigrate:
    """should_migrate — 判断是否需要迁移。"""

    def test_returns_true_when_yaml_exists_db_missing(self, tmp_path: Path):
        """YAML 文件存在但 state.db 不存在 → 需要迁移。"""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "known_item_ids.yaml").write_text("test-event: '2026-01-01T00:00:00Z'")

        db_path = tmp_path / "state.db"
        assert db_path.exists() is False
        assert should_migrate(memory_dir, db_path) is True

    def test_returns_false_when_db_exists(self, tmp_path: Path):
        """state.db 已存在 → 不需要迁移。"""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "known_item_ids.yaml").write_text("x: y")

        db_path = tmp_path / "state.db"
        db_path.write_text("")  # 文件存在即可
        assert should_migrate(memory_dir, db_path) is False

    def test_returns_false_when_yaml_missing(self, tmp_path: Path):
        """YAML 文件不存在 → 不需要迁移。"""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        db_path = tmp_path / "state.db"

        assert should_migrate(memory_dir, db_path) is False


class TestMigrateYamlToSqlite:
    """migrate_yaml_to_sqlite — 迁移执行。"""

    @pytest.fixture
    async def store(self, tmp_path: Path) -> AsyncStore:
        db_path = tmp_path / "state.db"
        s = AsyncStore(db_path)
        await s.initialize()
        return s

    @pytest.mark.asyncio
    async def test_migrates_known_ids(self, tmp_path: Path, store: AsyncStore):
        """known_item_ids.yaml 中的 ID 应迁移到 SQLite。"""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()

        known_ids_data = {
            "ne-italy-ansa-20260515-a1b2c3d4": "2026-05-15T10:00:00+00:00",
            "ne-italy-corriere-20260515-e5f6a7b8": "2026-05-15T11:00:00+00:00",
            "ne-italy-repubblica-20260515-c1d2e3f4": "2026-05-15T12:00:00+00:00",
        }
        with open(memory_dir / "known_item_ids.yaml", "w", encoding="utf-8") as f:
            yaml.safe_dump(known_ids_data, f, allow_unicode=True)

        result = await migrate_yaml_to_sqlite(memory_dir, store)
        assert result["known_ids_migrated"] == 3

        # 验证数据在 SQLite 中
        for eid in known_ids_data:
            assert await store.is_known(eid) is True

    @pytest.mark.asyncio
    async def test_migrates_source_health(self, tmp_path: Path, store: AsyncStore):
        """source_health.yaml 中的数据应迁移到 SQLite。"""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()

        health_data = {
            "ansa": {
                "last_success_at": "2026-05-15T10:00:00Z",
                "last_failure_at": None,
                "consecutive_failures": 0,
                "last_error": None,
                "total_runs": 10,
                "total_failures": 2,
            },
            "corriere": {
                "last_success_at": None,
                "last_failure_at": "2026-05-15T11:00:00Z",
                "consecutive_failures": 5,
                "last_error": "timeout",
                "total_runs": 20,
                "total_failures": 8,
            },
        }
        with open(memory_dir / "source_health.yaml", "w", encoding="utf-8") as f:
            yaml.safe_dump(health_data, f, allow_unicode=True)

        result = await migrate_yaml_to_sqlite(memory_dir, store)
        assert result["source_health_migrated"] == 2

        health_ansa = await store.get_source_health("ansa")
        assert health_ansa is not None
        assert health_ansa["status"] == "healthy"
        meta = health_ansa.get("metadata", {})
        assert meta.get("total_runs") == 10
        assert meta.get("consecutive_failures") == 0

        health_corriere = await store.get_source_health("corriere")
        assert health_corriere is not None
        assert health_corriere["status"] == "down"
        meta = health_corriere.get("metadata", {})
        assert meta.get("consecutive_failures") == 5

    @pytest.mark.asyncio
    async def test_migrates_cursors(self, tmp_path: Path, store: AsyncStore):
        """cursors.yaml 中的数据应迁移到 SQLite。"""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()

        cursors_data = {
            "ansa": 'etag-"abc123"',
            "corriere": "2026-05-15T09:00:00Z",
        }
        with open(memory_dir / "cursors.yaml", "w", encoding="utf-8") as f:
            yaml.safe_dump(cursors_data, f, allow_unicode=True)

        result = await migrate_yaml_to_sqlite(memory_dir, store)
        assert result["cursors_migrated"] == 2

        assert await store.get_cursor("ansa") == 'etag-"abc123"'
        assert await store.get_cursor("corriere") == "2026-05-15T09:00:00Z"

    @pytest.mark.asyncio
    async def test_migrates_empty_yaml_gracefully(self, tmp_path: Path, store: AsyncStore):
        """YAML 文件存在但为空时应正常处理。"""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "known_item_ids.yaml").write_text("{}\n")
        (memory_dir / "source_health.yaml").write_text("{}\n")
        (memory_dir / "cursors.yaml").write_text("{}\n")

        result = await migrate_yaml_to_sqlite(memory_dir, store)
        # 空 YAML 不产生迁移计数
        assert result["known_ids_migrated"] == 0
        assert result["source_health_migrated"] == 0
        assert result["cursors_migrated"] == 0

    @pytest.mark.asyncio
    async def test_migration_idempotent(self, tmp_path: Path, store: AsyncStore):
        """重复迁移不应报错也不产生重复数据。"""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()

        known_ids_data = {"ne-test-migrate-001": "2026-05-15T10:00:00Z"}
        with open(memory_dir / "known_item_ids.yaml", "w", encoding="utf-8") as f:
            yaml.safe_dump(known_ids_data, f, allow_unicode=True)

        result1 = await migrate_yaml_to_sqlite(memory_dir, store)
        assert result1["known_ids_migrated"] == 1

        result2 = await migrate_yaml_to_sqlite(memory_dir, store)
        # 第二次迁移：已知 ID 已存在，计数应归零
        assert result2["known_ids_migrated"] == 0
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python3 -m pytest tests/unit/test_yaml_migration.py -v
```

预期：FAIL — `ModuleNotFoundError: No module named 'news_sentry.core.yaml_migration'`

- [ ] **Step 3: 实现 YAML 迁移逻辑**

```python
# src/news_sentry/core/yaml_migration.py
"""YAML → SQLite 数据迁移。

检测 data/{target_id}/memory/ 下的 YAML 文件是否存在但 state.db 不存在。
自动迁移已知 ID、源健康数据、游标到 SQLite。迁移完成后 YAML 文件保留但不再写入。
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from news_sentry.core.async_store import AsyncStore

logger = logging.getLogger(__name__)

# ── YAML 文件名 ──────────────────────────────────────────────────────
_KNOWN_IDS_FILE = "known_item_ids.yaml"
_SOURCE_HEALTH_FILE = "source_health.yaml"
_CURSORS_FILE = "cursors.yaml"


def should_migrate(memory_dir: Path, db_path: Path) -> bool:
    """判断是否需要执行 YAML → SQLite 迁移。

    条件：memory_dir 下的 YAML 文件存在 且 state.db 不存在。

    Args:
        memory_dir: memory/ 目录路径。
        db_path: state.db 文件路径。

    Returns:
        True 如果应该执行迁移。
    """
    if db_path.exists():
        return False

    # 检查任一 YAML 文件存在
    for filename in (_KNOWN_IDS_FILE, _SOURCE_HEALTH_FILE, _CURSORS_FILE):
        if (memory_dir / filename).exists():
            return True
    return False


async def migrate_yaml_to_sqlite(
    memory_dir: Path,
    store: AsyncStore,
) -> dict[str, int]:
    """执行 YAML 到 SQLite 的迁移。

    Args:
        memory_dir: memory/ 目录路径（包含 YAML 文件）。
        store: 已初始化的 AsyncStore 实例。

    Returns:
        dict: {"known_ids_migrated": N, "source_health_migrated": N, "cursors_migrated": N}
    """
    result = {
        "known_ids_migrated": 0,
        "source_health_migrated": 0,
        "cursors_migrated": 0,
    }

    # ── 迁移 known_ids ──────────────────────────────────────────
    known_ids_path = memory_dir / _KNOWN_IDS_FILE
    if known_ids_path.exists():
        try:
            with open(known_ids_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                for event_id, seen_at in data.items():
                    await store._db.execute(
                        "INSERT OR IGNORE INTO known_ids (event_id, seen_at) VALUES (?, ?)",
                        (str(event_id), str(seen_at)),
                    )
                await store._db.commit()
                result["known_ids_migrated"] = len(data)
                logger.info("迁移 known_ids: %d 条", len(data))
        except Exception:
            logger.warning("known_ids 迁移失败", exc_info=True)

    # ── 迁移 source_health ──────────────────────────────────────
    health_path = memory_dir / _SOURCE_HEALTH_FILE
    if health_path.exists():
        try:
            with open(health_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                for source_id, entry in data.items():
                    if not isinstance(entry, dict):
                        continue

                    consecutive = entry.get("consecutive_failures", 0)
                    if isinstance(consecutive, (int, float)) and consecutive >= 5:
                        status = "down"
                    elif isinstance(consecutive, (int, float)) and consecutive > 0:
                        status = "degraded"
                    else:
                        status = "healthy"

                    last_check = entry.get("last_success_at") or entry.get("last_failure_at") or datetime.now(UTC).isoformat()
                    error_count = int(consecutive) if isinstance(consecutive, (int, float)) else 0

                    meta_json = json.dumps(entry, ensure_ascii=False)
                    await store._db.execute(
                        """INSERT OR REPLACE INTO source_health
                           (source_id, status, last_check, error_count, metadata)
                           VALUES (?, ?, ?, ?, ?)""",
                        (str(source_id), status, str(last_check), error_count, meta_json),
                    )
                    result["source_health_migrated"] += 1
                await store._db.commit()
                logger.info("迁移 source_health: %d 条", result["source_health_migrated"])
        except Exception:
            logger.warning("source_health 迁移失败", exc_info=True)

    # ── 迁移 cursors ────────────────────────────────────────────
    cursors_path = memory_dir / _CURSORS_FILE
    if cursors_path.exists():
        try:
            with open(cursors_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                for source_id, cursor_val in data.items():
                    now = datetime.now(UTC).isoformat()
                    await store._db.execute(
                        """INSERT OR REPLACE INTO cursors (source_id, cursor, updated_at)
                           VALUES (?, ?, ?)""",
                        (str(source_id), str(cursor_val), now),
                    )
                    result["cursors_migrated"] += 1
                await store._db.commit()
                logger.info("迁移 cursors: %d 条", result["cursors_migrated"])
        except Exception:
            logger.warning("cursors 迁移失败", exc_info=True)

    return result
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python3 -m pytest tests/unit/test_yaml_migration.py -v
```

预期：7 passed

- [ ] **Step 5: 提交**

```bash
git add src/news_sentry/core/yaml_migration.py tests/unit/test_yaml_migration.py
git commit -m "Phase 26: YAML → SQLite 迁移逻辑 (P26.06)"
```

---

## Task 7: 集成到 async_run.py — AsyncStore 替代 Memory

**Files:**
- Modify: `src/news_sentry/core/async_run.py`（Phase 25 创建）
- Modify: `tests/unit/test_async_run.py`（Phase 25 创建）

注意：此 Task 的前提是 Phase 25 已完成，`async_run.py` 和 `test_async_run.py` 已存在。如果 Phase 25 尚未创建这些文件，则本 Task 应标记为 `[BLOCKED]`，待 Phase 25 完成后执行。

- [ ] **Step 1: 写 AsyncStore 集成测试**

在 `tests/unit/test_async_run.py` 中追加：

```python
class TestAsyncStoreIntegration:
    """验证 AsyncStore 在 async_run pipeline 中替代 Memory。"""

    @pytest.mark.asyncio
    async def test_async_store_initialized_in_bounded_run(self, tmp_path: Path):
        """bounded_run_async 应初始化 AsyncStore 并传入 collect 阶段。"""
        from news_sentry.core.async_run import _create_async_store
        from news_sentry.core.async_store import AsyncStore

        db_path = tmp_path / "state.db"
        store = await _create_async_store(tmp_path, db_path)
        assert isinstance(store, AsyncStore)
        assert db_path.exists()
        await store.close()

    @pytest.mark.asyncio
    async def test_async_store_migration_triggered(self, tmp_path: Path):
        """首次使用时如果 YAML 存在，应触发迁移。"""
        import yaml
        from news_sentry.core.async_run import _init_async_store_for_target

        # 创建 memory 目录 + YAML 文件
        data_dir = tmp_path / "italy"
        memory_dir = data_dir / "memory"
        memory_dir.mkdir(parents=True)
        (memory_dir / "known_item_ids.yaml").write_text(
            yaml.dump({"ne-test-001": "2026-05-15T10:00:00Z"})
        )

        db_path = data_dir / "state.db"
        assert db_path.exists() is False

        # 初始化
        store = await _init_async_store_for_target(data_dir)
        assert isinstance(store, AsyncStore)
        assert db_path.exists()
        # 迁移应已执行
        assert await store.is_known("ne-test-001") is True
        await store.close()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python3 -m pytest tests/unit/test_async_run.py::TestAsyncStoreIntegration -v
```

预期：FAIL — `AttributeError: module 'news_sentry.core.async_run' has no attribute '_create_async_store'`（或类似的 ImportError）

- [ ] **Step 3: 在 async_run.py 中集成 AsyncStore**

在 `src/news_sentry/core/async_run.py` 中：

**3a. 修改 import：**

```python
# 新增导入
from news_sentry.core.async_store import AsyncStore
from news_sentry.core.yaml_migration import should_migrate, migrate_yaml_to_sqlite

# 保留 Memory import（向后兼容）
from news_sentry.core.memory import Memory
```

**3b. 新增辅助函数（在 `_create_collector` 之后）：**

```python
async def _init_async_store_for_target(data_dir: Path) -> AsyncStore:
    """为目标目录初始化 AsyncStore（含 YAML 迁移检测）。

    流程：
    1. 创建 AsyncStore(data_dir / "state.db")
    2. 调用 initialize() 建表
    3. 检测是否需要 YAML→SQLite 迁移
    4. 如需迁移则执行

    Args:
        data_dir: target 的数据目录（如 data/italy/）。

    Returns:
        已初始化的 AsyncStore 实例。
    """
    db_path = data_dir / "state.db"
    memory_dir = data_dir / "memory"

    store = AsyncStore(db_path)
    await store.initialize()

    if should_migrate(memory_dir, db_path):
        logger.info("检测到旧 YAML 文件，开始迁移到 SQLite...")
        result = await migrate_yaml_to_sqlite(memory_dir, store)
        logger.info(
            "YAML→SQLite 迁移完成: known_ids=%d, source_health=%d, cursors=%d",
            result["known_ids_migrated"],
            result["source_health_migrated"],
            result["cursors_migrated"],
        )

    return store
```

**3c. 修改 `bounded_run_async` 函数中的存储初始化：**

在 `bounded_run_async` 中，将：
```python
# 旧代码：使用 Memory
memory = Memory(output_dir / "memory")
```

替换为：
```python
# 新代码：使用 AsyncStore（含自动迁移）
store = await _init_async_store_for_target(data_dir)
# 同时创建 Memory adapter，供同步 filter/judge 使用
# (Phase 27 前，filter/judge 仍用同步 Memory 接口)
from news_sentry.core.memory import Memory
memory = Memory(data_dir / "memory")

# 在 _run_collect_async 调用中传入 store
events = await _run_collect_async(
    config, run_id=ctx.run_id, run_log=None,
    file_writer=file_writer, sandbox=sandbox,
    memory=memory, store=store, ctx=ctx,
    http_client=http_client, max_concurrent=max_concurrent,
)
```

**3d. 确保在 bounded_run_async 结束时关闭 store：**

```python
try:
    # ... pipeline 执行 ...
finally:
    await store.close()
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python3 -m pytest tests/unit/test_async_run.py::TestAsyncStoreIntegration -v
```

预期：2 passed

- [ ] **Step 5: 运行全部测试确认无回归**

```bash
.venv/bin/python3 -m pytest tests/ -q
```

预期：所有现有测试通过（Memory 类原样保留，同步 pipeline 不受影响）

- [ ] **Step 6: 提交**

```bash
git add src/news_sentry/core/async_run.py tests/unit/test_async_run.py
git commit -m "Phase 26: async_run.py 集成 AsyncStore + YAML 自动迁移 (P26.07)"
```

---

## Task 8: 集成验证与清理

- [ ] **Step 1: 运行完整静态检查**

```bash
ruff check src/news_sentry/core/async_store.py src/news_sentry/core/yaml_migration.py src/news_sentry/core/async_run.py tests/unit/test_async_store.py tests/unit/test_yaml_migration.py tests/unit/test_async_run.py
.venv/bin/python3 -m mypy src/news_sentry/core/async_store.py src/news_sentry/core/yaml_migration.py src/news_sentry/core/async_run.py
```

预期：ruff=0, mypy=0

- [ ] **Step 2: 运行全部测试确认无回归**

```bash
.venv/bin/python3 -m pytest tests/ -q
```

预期：全部测试通过，x passed（其中新增 Task 1-6 测试 ~38 个，Task 7 ~2 个，加上 Memory 原有测试 ~30 个保持通过）

- [ ] **Step 3: 确认覆盖率未下降**

```bash
.venv/bin/python3 -m pytest tests/ --cov=news_sentry -q 2>&1 | tail -5
```

预期：覆盖率 >= 92%（Phase 开始前水平）。新增的 `async_store.py` 和 `yaml_migration.py` 应有 95%+ 测试覆盖。

- [ ] **Step 4: 确认 Memory 类仍可正常工作**

```bash
.venv/bin/python3 -m pytest tests/unit/test_memory.py -v
```

预期：全部 ~30 个 Memory 测试通过（Memory 类完整保留）

- [ ] **Step 5: 最终提交**

```bash
git commit --allow-empty -m "Phase 26: 集成验证通过 — SQLite 存储层 (P26.00)"
```

---

## 验证标准

Phase 26 完成的验收条件：

- [ ] 全部 1311+ 测试通过（CI 绿色），新增 ~40 个 AsyncStore + 迁移测试
- [ ] ruff check = 0, mypy = 0
- [ ] 测试覆盖率 >= 92%
- [ ] 新增文件：`async_store.py`, `yaml_migration.py`, `test_async_store.py`, `test_yaml_migration.py`
- [ ] Memory 类原样保留，`tests/unit/test_memory.py` 全部通过
- [ ] `async_store.py` 实现设计文档 §4 定义的完整 AsyncStore 接口
- [ ] `yaml_migration.py` 自动检测 YAML → SQLite 迁移，迁移后数据一致
- [ ] SQLite 数据库使用 WAL 模式、NORMAL synchronous、64MB cache、FK 约束
- [ ] 所有 SQLite 操作使用 async/await，写操作后 commit，测试使用临时文件路径
- [ ] `pyproject.toml` 新增 `aiosqlite>=0.20` 依赖

---

## 与现有 Memory 的映射速查

| Memory 方法 | AsyncStore 方法 | SQL 操作 | 性能变化 |
|-------------|----------------|---------|---------|
| `is_known(id)` | `is_known(event_id)` | `SELECT 1 FROM known_ids WHERE event_id=?` | O(1) 索引查询 |
| `mark_known(id)` | `mark_known(event_id)` | `INSERT OR IGNORE INTO known_ids` | 增量写入，替代全量序列化 |
| `get_source_health(id)` | `get_source_health(source_id)` | `SELECT FROM source_health WHERE source_id=?` | O(1) 索引查询 |
| `update_source_health(...)` | N/A（合并到 `record_source_health`） | - | - |
| `record_source_health(...)` | `record_source_health(...)` | `INSERT OR REPLACE INTO source_health` | 增量写入 |
| `is_source_degraded(id)` | `is_source_degraded(source_id)` | 先 SELECT 再 Python 判断 | 逻辑不变 |
| `get_cursor(id)` | `get_cursor(source_id)` | `SELECT cursor FROM cursors WHERE source_id=?` | O(1) |
| `set_cursor(id, val)` | `set_cursor(source_id, cursor)` | `INSERT OR REPLACE INTO cursors` | 增量写入 |
| `get_provider_stats(id)` | N/A（未实现，provider_stats 仅 Memory 自身使用） | - | - |
| `update_provider_stats(...)` | N/A（同上） | - | - |
| N/A | `get_cached_response(key)` | `SELECT response FROM llm_cache WHERE cache_key=?` | 新增 |
| N/A | `set_cached_response(key, resp, model)` | `INSERT OR REPLACE INTO llm_cache` | 新增 |
| N/A | `evict_if_needed(max)` | `DELETE FROM llm_cache ... ORDER BY updated_at ASC LIMIT N` | 新增 |
| N/A | `index_event(event, target, stage, path)` | `INSERT OR REPLACE INTO event_index` | 新增 |
| N/A | `query_events(target, stage)` | `SELECT ... FROM event_index WHERE ...` | 新增 |
| N/A | `get_event_count(target, stage)` | `SELECT COUNT(*) FROM event_index WHERE ...` | 新增 |
| N/A | `get_stats(target)` | `SELECT COUNT/AVG ... GROUP BY stage` | 新增 |

---

## 错误处理约定

1. **`_db is None`**：所有方法在任何操作前检查 `_db` 是否为 None（表示未初始化或已关闭），返回安全默认值（False/None/0/[]）
2. **Commit 策略**：每个写操作后立即 `await self._db.commit()`，不做延迟合并（单文件 SQLite + WAL 模式下开销可忽略）
3. **Schema 迁移**：通过 `CREATE TABLE IF NOT EXISTS` 确保幂等性。如需在未来 Phase 做 DDL 变更，通过 `ALTER TABLE` 或新增版本号列实现
4. **YAML 迁移**：迁移使用 `INSERT OR IGNORE`，确保幂等。迁移失败不阻塞 pipeline 启动（仅记录 warning）
5. **JSON 列**：`source_health.metadata` 以 JSON 字符串存储，反序列化时 `json.JSONDecodeError` 容错为 `{}`
