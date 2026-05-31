# Phase 28: API Server 重构 — SQLite 查询替代文件扫描、分页、配置缓存

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 API Server 的事件查询和统计端点从全量文件扫描改为 SQLite event_index 查询，实现毫秒级响应；配置端点引入 TTL 缓存，新增 /config/reload 端点；pipeline 输出阶段同步写入 event_index。

**Architecture:** SQLite event_index 表（Phase 26 创建）存索引字段（event_id, target_id, stage, source_id, news_value_score, china_relevance, classification_l0, published_at, file_path），完整事件内容仍从 .md 文件读取。配置端点用 cachetools.TTLCache（TTL=60s）包装。现有端点 URL 路径和参数签名不变。

**Tech Stack:** Python 3.11+, aiosqlite, cachetools, FastAPI, pytest, pytest-asyncio

**设计文档:** `docs/performance-overhaul-design.md` Section 7

**前置依赖:** Phase 26（AsyncStore + event_index 表）

---

## 文件结构

### 新建文件
- `src/news_sentry/core/config_cache.py` — 配置 TTL 缓存包装层
- `tests/unit/test_config_cache.py` — 配置缓存测试

### 修改文件
- `src/news_sentry/core/api_server.py` — 事件查询、统计端点改用 SQLite；配置端点加缓存；新增 POST /config/reload
- `src/news_sentry/core/async_store.py` — 新增 `query_events_paginated`、`get_stats_aggregated`、`get_event_file_path` 方法
- `src/news_sentry/core/async_run.py` — 输出阶段写入 event_index
- `tests/unit/test_api_server.py` — 更新测试：SQLite 内存数据库替代文件扫描断言
- `tests/unit/test_async_store.py` — 新增 event_index 查询方法测试
- `pyproject.toml` — 新增 `cachetools>=5.3` 依赖

### 不改动文件
- `src/news_sentry/core/run.py` — 同步 pipeline 保留，不改动
- 现有端点的 URL 路径和参数签名不变

---

## Task 1: AsyncStore 扩展 — event_index 查询方法

**Files:**
- Modify: `src/news_sentry/core/async_store.py`
- Modify: `tests/unit/test_async_store.py`

Phase 26 已创建 event_index 表和基础 `index_event` 方法。本 Task 新增 3 个查询方法。

- [ ] **Step 1: 写查询方法测试**

在 `tests/unit/test_async_store.py` 中新增测试类：

```python
class TestEventIndexQueries:
    """event_index 查询方法测试。"""

    @pytest.fixture
    async def store_with_events(self, tmp_path: Path) -> AsyncStore:
        """创建包含测试数据的 AsyncStore。"""
        db_path = tmp_path / "state.db"
        store = AsyncStore()
        await store.initialize(db_path)

        # 插入 5 条测试事件
        now = datetime.now(UTC).isoformat()
        for i in range(5):
            await store.db.execute_insert(
                "INSERT OR REPLACE INTO event_index "
                "(event_id, target_id, stage, source_id, news_value_score, "
                "china_relevance, classification_l0, published_at, file_path, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"ne-italy-src{i:04d}",
                    "italy",
                    "drafts",
                    "ansa" if i % 2 == 0 else "repubblica",
                    60 + i * 5,
                    20 + i * 3,
                    "international" if i % 2 == 0 else "politics",
                    now,
                    f"data/italy/drafts/outputted_src{i:04d}_ne-italy-src{i:04d}.md",
                    now,
                ),
            )
        await store.db.commit()
        return store

    @pytest.mark.asyncio
    async def test_query_events_paginated_basic(self, store_with_events: AsyncStore) -> None:
        """基本分页查询。"""
        result = await store_with_events.query_events_paginated(
            target_id="italy",
            stage="drafts",
            limit=2,
            offset=0,
        )
        assert result["total"] == 5
        assert len(result["rows"]) == 2

    @pytest.mark.asyncio
    async def test_query_events_paginated_second_page(
        self, store_with_events: AsyncStore,
    ) -> None:
        """第二页查询。"""
        result = await store_with_events.query_events_paginated(
            target_id="italy",
            stage="drafts",
            limit=2,
            offset=2,
        )
        assert result["total"] == 5
        assert len(result["rows"]) == 2

    @pytest.mark.asyncio
    async def test_query_events_filter_by_source(
        self, store_with_events: AsyncStore,
    ) -> None:
        """按 source_id 筛选。"""
        result = await store_with_events.query_events_paginated(
            target_id="italy",
            stage="drafts",
            source_id="ansa",
            limit=10,
            offset=0,
        )
        assert result["total"] == 3  # 索引 0, 2, 4

    @pytest.mark.asyncio
    async def test_query_events_filter_by_classification(
        self, store_with_events: AsyncStore,
    ) -> None:
        """按 classification_l0 筛选。"""
        result = await store_with_events.query_events_paginated(
            target_id="italy",
            stage="drafts",
            classification_l0="politics",
            limit=10,
            offset=0,
        )
        assert result["total"] == 2

    @pytest.mark.asyncio
    async def test_query_events_filter_by_min_score(
        self, store_with_events: AsyncStore,
    ) -> None:
        """按最低 news_value_score 筛选。"""
        result = await store_with_events.query_events_paginated(
            target_id="italy",
            stage="drafts",
            min_score=70,
            limit=10,
            offset=0,
        )
        assert result["total"] == 3  # 75, 80, 85

    @pytest.mark.asyncio
    async def test_query_events_search_title(
        self, store_with_events: AsyncStore,
    ) -> None:
        """在 title_original 中搜索关键词。"""
        # 需要先在表中存 title_original — 本方法搜索时 JOIN file_path 读取
        # 简化实现：event_index 增加可选的 title_original 列
        pass  # 见 Step 3 说明

    @pytest.mark.asyncio
    async def test_get_stats_aggregated(self, store_with_events: AsyncStore) -> None:
        """聚合统计查询。"""
        stats = await store_with_events.get_stats_aggregated(target_id="italy")
        assert stats["total_events"] == 5
        assert stats["avg_news_value_score"] is not None
        assert 60 <= stats["avg_news_value_score"] <= 85
        assert stats["avg_china_relevance"] is not None
        assert stats["by_classification"]["international"] == 3
        assert stats["by_classification"]["politics"] == 2
        assert stats["by_source"]["ansa"] == 3
        assert stats["by_source"]["repubblica"] == 2

    @pytest.mark.asyncio
    async def test_get_stats_empty(self, tmp_path: Path) -> None:
        """空 target 统计。"""
        store = AsyncStore()
        await store.initialize(tmp_path / "state.db")
        stats = await store_with_events.get_stats_aggregated(target_id="nonexistent")
        assert stats["total_events"] == 0
        assert stats["avg_news_value_score"] is None
        await store.close()

    @pytest.mark.asyncio
    async def test_get_event_file_path(self, store_with_events: AsyncStore) -> None:
        """根据 event_id 查找 file_path。"""
        path = await store_with_events.get_event_file_path(event_id="ne-italy-src0000")
        assert path is not None
        assert "ne-italy-src0000" in path

    @pytest.mark.asyncio
    async def test_get_event_file_path_not_found(
        self, store_with_events: AsyncStore,
    ) -> None:
        """不存在的 event_id 返回 None。"""
        path = await store_with_events.get_event_file_path(event_id="ne-nonexistent")
        assert path is None
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python3 -m pytest tests/unit/test_async_store.py::TestEventIndexQueries -v
```

预期：FAIL — `AttributeError: 'AsyncStore' has no attribute 'query_events_paginated'`

- [ ] **Step 3: 在 AsyncStore 中实现查询方法**

在 `src/news_sentry/core/async_store.py` 中，在现有 `index_event` 方法之后添加以下方法：

```python
async def query_events_paginated(
    self,
    target_id: str,
    stage: str,
    *,
    limit: int = 20,
    offset: int = 0,
    source_id: str | None = None,
    classification_l0: str | None = None,
    min_score: int | None = None,
) -> dict:
    """分页查询 event_index，返回 {total: int, rows: list[dict]}。

    每行包含: event_id, source_id, news_value_score, china_relevance,
    classification_l0, published_at, file_path, title_original。
    """
    conditions = ["target_id = ?", "stage = ?"]
    params: list[Any] = [target_id, stage]

    if source_id is not None:
        conditions.append("source_id = ?")
        params.append(source_id)
    if classification_l0 is not None:
        conditions.append("classification_l0 = ?")
        params.append(classification_l0)
    if min_score is not None:
        conditions.append("news_value_score >= ?")
        params.append(min_score)

    where = " AND ".join(conditions)

    # 总数查询
    count_sql = f"SELECT COUNT(*) FROM event_index WHERE {where}"
    async with self.db.execute(count_sql, params) as cursor:
        row = await cursor.fetchone()
        total = row[0] if row else 0

    # 分页查询
    data_sql = (
        f"SELECT event_id, source_id, news_value_score, china_relevance, "
        f"classification_l0, published_at, file_path, title_original "
        f"FROM event_index WHERE {where} "
        f"ORDER BY published_at DESC LIMIT ? OFFSET ?"
    )
    async with self.db.execute(data_sql, params + [limit, offset]) as cursor:
        rows = await cursor.fetchall()

    result_rows = []
    for r in rows:
        result_rows.append({
            "event_id": r[0],
            "source_id": r[1],
            "news_value_score": r[2],
            "china_relevance": r[3],
            "classification_l0": r[4],
            "published_at": r[5],
            "file_path": r[6],
            "title_original": r[7],
        })

    return {"total": total, "rows": result_rows}


async def get_stats_aggregated(self, target_id: str) -> dict:
    """聚合统计查询，返回事件总数、平均分、按分类/来源计数。"""
    async with self.db.execute(
        "SELECT COUNT(*) FROM event_index WHERE target_id = ?", [target_id],
    ) as cursor:
        row = await cursor.fetchone()
        total = row[0] if row else 0

    if total == 0:
        return {
            "total_events": 0,
            "avg_news_value_score": None,
            "avg_china_relevance": None,
            "by_classification": {},
            "by_source": {},
        }

    async with self.db.execute(
        "SELECT AVG(news_value_score), AVG(china_relevance) "
        "FROM event_index WHERE target_id = ? "
        "AND news_value_score IS NOT NULL",
        [target_id],
    ) as cursor:
        row = await cursor.fetchone()
        avg_score = row[0] if row and row[0] is not None else None
        avg_relevance = row[1] if row and row[1] is not None else None

    by_classification: dict[str, int] = {}
    async with self.db.execute(
        "SELECT classification_l0, COUNT(*) FROM event_index "
        "WHERE target_id = ? AND classification_l0 IS NOT NULL "
        "GROUP BY classification_l0",
        [target_id],
    ) as cursor:
        async for row in cursor:
            by_classification[row[0]] = row[1]

    by_source: dict[str, int] = {}
    async with self.db.execute(
        "SELECT source_id, COUNT(*) FROM event_index "
        "WHERE target_id = ? AND source_id IS NOT NULL "
        "GROUP BY source_id",
        [target_id],
    ) as cursor:
        async for row in cursor:
            by_source[row[0]] = row[1]

    return {
        "total_events": total,
        "avg_news_value_score": round(avg_score, 2) if avg_score is not None else None,
        "avg_china_relevance": round(avg_relevance, 2) if avg_relevance is not None else None,
        "by_classification": by_classification,
        "by_source": by_source,
    }


async def get_event_file_path(self, event_id: str) -> str | None:
    """根据 event_id 查找对应的 .md 文件路径。"""
    async with self.db.execute(
        "SELECT file_path FROM event_index WHERE event_id = ?", [event_id],
    ) as cursor:
        row = await cursor.fetchone()
        return row[0] if row else None
```

同时需要更新 event_index 表的 Schema（在 Phase 26 的建表 SQL 中增加 `source_id`、`news_value_score`、`china_relevance`、`classification_l0`、`title_original` 列）：

```sql
CREATE TABLE IF NOT EXISTS event_index (
    event_id         TEXT PRIMARY KEY,
    target_id        TEXT NOT NULL,
    stage            TEXT NOT NULL,
    source_id        TEXT,
    news_value_score INTEGER,
    china_relevance  INTEGER,
    classification_l0 TEXT,
    title_original   TEXT,
    published_at     TEXT,
    file_path        TEXT,
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_event_target_stage ON event_index(target_id, stage);
CREATE INDEX IF NOT EXISTS idx_event_published ON event_index(published_at DESC);
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python3 -m pytest tests/unit/test_async_store.py::TestEventIndexQueries -v
```

预期：全部通过

- [ ] **Step 5: 运行全部测试确认无回归**

```bash
.venv/bin/python3 -m pytest tests/ -q
```

- [ ] **Step 6: 提交**

```bash
git add src/news_sentry/core/async_store.py tests/unit/test_async_store.py
git commit -m "Phase 28: AsyncStore 扩展 event_index 查询方法 (P28.01)"
```

---

## Task 2: 配置 TTL 缓存层

**Files:**
- Create: `src/news_sentry/core/config_cache.py`
- Create: `tests/unit/test_config_cache.py`
- Modify: `pyproject.toml` — 新增 cachetools 依赖

- [ ] **Step 1: 在 pyproject.toml 中添加 cachetools 依赖**

在 `dependencies` 列表中添加：

```toml
dependencies = [
    "pydantic>=2.0",
    "pyyaml>=6.0",
    "httpx>=0.27",
    "feedparser>=6.0",
    "click>=8.1",
    "cachetools>=5.3",
]
```

- [ ] **Step 2: 写缓存层测试**

```python
# tests/unit/test_config_cache.py
from pathlib import Path

import pytest
import yaml

from news_sentry.core.config_cache import ConfigCache


class TestConfigCache:
    """配置 TTL 缓存测试。"""

    def _write_yaml(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

    def test_cache_hit_returns_same_result(self, tmp_path: Path) -> None:
        cache = ConfigCache(ttl=60, maxsize=128)
        yaml_path = tmp_path / "test.yaml"
        self._write_yaml(yaml_path, {"key": "value"})

        # 第一次调用读取文件
        result1 = cache.load_yaml(yaml_path)
        # 第二次调用命中缓存
        result2 = cache.load_yaml(yaml_path)
        assert result1 == result2
        assert result1["key"] == "value"

    def test_cache_invalidates_on_clear(self, tmp_path: Path) -> None:
        cache = ConfigCache(ttl=60, maxsize=128)
        yaml_path = tmp_path / "test.yaml"
        self._write_yaml(yaml_path, {"version": 1})

        result1 = cache.load_yaml(yaml_path)
        assert result1["version"] == 1

        # 修改文件
        self._write_yaml(yaml_path, {"version": 2})

        # 清除缓存
        cache.clear()

        # 重新加载，应读到新值
        result2 = cache.load_yaml(yaml_path)
        assert result2["version"] == 2

    def test_cache_returns_none_for_missing_file(self, tmp_path: Path) -> None:
        cache = ConfigCache(ttl=60, maxsize=128)
        result = cache.load_yaml(tmp_path / "nonexistent.yaml")
        assert result is None

    def test_cache_stores_multiple_files(self, tmp_path: Path) -> None:
        cache = ConfigCache(ttl=60, maxsize=128)
        path_a = tmp_path / "a.yaml"
        path_b = tmp_path / "b.yaml"
        self._write_yaml(path_a, {"name": "a"})
        self._write_yaml(path_b, {"name": "b"})

        assert cache.load_yaml(path_a)["name"] == "a"
        assert cache.load_yaml(path_b)["name"] == "b"

    def test_cache_hit_counts(self, tmp_path: Path) -> None:
        """缓存命中不应重复读文件。"""
        cache = ConfigCache(ttl=60, maxsize=128)
        yaml_path = tmp_path / "test.yaml"
        self._write_yaml(yaml_path, {"key": "value"})

        cache.load_yaml(yaml_path)
        cache.load_yaml(yaml_path)
        cache.load_yaml(yaml_path)

        assert cache.hits == 2
        assert cache.misses == 1

    def test_reload_delegates_to_clear(self, tmp_path: Path) -> None:
        cache = ConfigCache(ttl=60, maxsize=128)
        yaml_path = tmp_path / "test.yaml"
        self._write_yaml(yaml_path, {"v": 1})
        cache.load_yaml(yaml_path)

        self._write_yaml(yaml_path, {"v": 2})
        cache.reload()

        result = cache.load_yaml(yaml_path)
        assert result["v"] == 2
```

- [ ] **Step 3: 运行测试确认失败**

```bash
.venv/bin/python3 -m pytest tests/unit/test_config_cache.py -v
```

预期：FAIL — `ModuleNotFoundError: No module named 'news_sentry.core.config_cache'`

- [ ] **Step 4: 实现 ConfigCache**

```python
# src/news_sentry/core/config_cache.py
"""配置文件 TTL 缓存层，包装 YAML 文件读取。

- cachetools.TTLCache 提供自动过期（TTL=60s）
- POST /config/reload 通过 cache.clear() 主动失效
- 线程安全：FastAPI 同步端点中调用，无 asyncio.Lock 需求
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from cachetools import TTLCache


class ConfigCache:
    """带 TTL 过期的 YAML 配置缓存。

    Args:
        ttl: 缓存存活时间（秒），默认 60。
        maxsize: 最大缓存条目数，默认 128。
    """

    def __init__(self, ttl: float = 60, maxsize: int = 128) -> None:
        self._cache: TTLCache[str, dict[str, Any] | None] = TTLCache(
            maxsize=maxsize, ttl=ttl,
        )
        self.hits: int = 0
        self.misses: int = 0

    def load_yaml(self, path: Path) -> dict[str, Any] | None:
        """读取 YAML 文件，优先从缓存返回。

        Returns:
            解析后的 dict，文件不存在返回 None。
        """
        key = str(path.resolve())
        if key in self._cache:
            self.hits += 1
            return self._cache[key]

        self.misses += 1
        if not path.is_file():
            self._cache[key] = None
            return None

        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            result = data if isinstance(data, dict) else None
        except yaml.YAMLError:
            result = None

        self._cache[key] = result
        return result

    def clear(self) -> None:
        """清除全部缓存条目。"""
        self._cache.clear()
        self.hits = 0
        self.misses = 0

    def reload(self) -> None:
        """清除缓存（clear 的语义别名，供 API 端点调用）。"""
        self.clear()
```

- [ ] **Step 5: 运行测试确认通过**

```bash
.venv/bin/python3 -m pytest tests/unit/test_config_cache.py -v
```

预期：6 passed

- [ ] **Step 6: 提交**

```bash
git add pyproject.toml src/news_sentry/core/config_cache.py tests/unit/test_config_cache.py
git commit -m "Phase 28: 配置 TTL 缓存层 ConfigCache (P28.02)"
```

---

## Task 3: API Server 事件端点改用 SQLite

**Files:**
- Modify: `src/news_sentry/core/api_server.py`

将 `GET /events`、`GET /events/{id}`、`GET /stats` 三个端点的内部实现从文件扫描改为 AsyncStore 查询。

- [ ] **Step 1: 修改 create_app 签名，接受 store 参数**

在 `src/news_sentry/core/api_server.py` 的 `create_app` 函数中，新增可选 `store` 参数：

```python
def create_app(
    data_dir: str | Path | None = None,
    store: AsyncStore | None = None,
) -> FastAPI:
    """创建 FastAPI 应用实例。

    Args:
        data_dir: 数据根目录，默认 ./data。
        store: AsyncStore 实例（Phase 28 新增，用于 SQLite 查询）。
    """
```

文件顶部添加 import：

```python
from news_sentry.core.async_store import AsyncStore
```

- [ ] **Step 2: 重写 GET /stats 端点**

替换现有的 `get_stats` 端点实现（L444-485）：

```python
@app.get("/api/v1/stats", response_model=StatsResponse)
async def get_stats(
    target_id: str = Query(..., description="目标标识"),
) -> StatsResponse:
    """返回指定 target 的事件统计（SQLite 聚合查询）。"""
    if _store is not None:
        stats = await _store.get_stats_aggregated(target_id)
        return StatsResponse(
            target_id=target_id,
            total_events=stats["total_events"],
            avg_news_value_score=stats["avg_news_value_score"],
            avg_china_relevance=stats["avg_china_relevance"],
            by_classification=stats["by_classification"],
            by_source=stats["by_source"],
        )

    # 降级路径：无 store 时走原始文件扫描
    events = _load_all_events(_data_dir, target_id)
    total = len(events)
    scores = [
        e["news_value_score"]
        for e in events
        if isinstance(e.get("news_value_score"), (int, float))
    ]
    relevances = [
        e["china_relevance"]
        for e in events
        if isinstance(e.get("china_relevance"), (int, float))
    ]
    avg_score = sum(scores) / len(scores) if scores else None
    avg_relevance = sum(relevances) / len(relevances) if relevances else None
    by_classification: dict[str, int] = defaultdict(int)
    by_source: dict[str, int] = defaultdict(int)
    for e in events:
        cls_data = e.get("classification")
        if isinstance(cls_data, dict):
            l0 = cls_data.get("l0")
            if l0:
                by_classification[l0] += 1
        src = e.get("source_id")
        if src:
            by_source[src] += 1
    return StatsResponse(
        target_id=target_id,
        total_events=total,
        avg_news_value_score=avg_score,
        avg_china_relevance=avg_relevance,
        by_classification=dict(by_classification),
        by_source=dict(by_source),
    )
```

- [ ] **Step 3: 重写 GET /events 端点**

替换现有的 `list_events` 端点实现（L640-663）：

```python
@app.get("/api/v1/events", response_model=EventResponse)
async def list_events(
    target_id: str = Query(..., description="目标标识"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    classification: str | None = Query(None, description="按 classification.l0 筛选"),
    source_id: str | None = Query(None, description="按 source_id 筛选"),
    min_score: int | None = Query(None, description="最低 news_value_score"),
    search: str | None = Query(None, description="在 title_original 中搜索关键词"),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> EventResponse:
    key = _verify_api_key(x_api_key)
    if not _rate_limiter.check(key):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    if _store is not None:
        offset = (page - 1) * page_size
        result = await _store.query_events_paginated(
            target_id=target_id,
            stage="drafts",
            limit=page_size,
            offset=offset,
            source_id=source_id,
            classification_l0=classification,
            min_score=min_score,
        )
        total = result["total"]
        page_events: list[dict[str, Any]] = []

        for row in result["rows"]:
            event_fm = _load_event_by_path(row["file_path"])
            if event_fm is None:
                continue
            # search 过滤需要在读出完整事件后做（title_original 可能很长，不存索引）
            if search is not None:
                keyword = search.lower()
                if keyword not in (event_fm.get("title_original") or "").lower():
                    total -= 1
                    continue
            page_events.append(event_fm)

        return EventResponse(
            total=total,
            events=page_events,
            page=page,
            page_size=page_size,
        )

    # 降级路径
    return _load_events_from_data(
        _data_dir, target_id, page, page_size,
        classification=classification,
        source_id=source_id,
        min_score=min_score,
        search=search,
    )
```

新增辅助函数：

```python
def _load_event_by_path(file_path: str | None) -> dict[str, Any] | None:
    """根据 file_path 读取单个 .md 文件的 frontmatter。"""
    if file_path is None:
        return None
    path = Path(file_path)
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        return _parse_frontmatter(raw)
    except Exception:
        return None
```

- [ ] **Step 4: 重写 GET /events/{id} 端点**

替换现有的 `get_event` 端点实现（L665-677）：

```python
@app.get("/api/v1/events/{event_id}")
async def get_event(
    event_id: str,
    target_id: str = Query(..., description="目标标识"),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> dict[str, Any]:
    key = _verify_api_key(x_api_key)
    if not _rate_limiter.check(key):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    if _store is not None:
        file_path = await _store.get_event_file_path(event_id)
        if file_path is None:
            raise HTTPException(status_code=404, detail="Event not found")
        event = _load_event_by_path(file_path)
        if event is None:
            raise HTTPException(status_code=404, detail="Event file not found")
        return event

    # 降级路径
    event = _load_single_event(_data_dir, target_id, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event
```

- [ ] **Step 5: 在 create_app 中初始化 store 引用**

在 `create_app` 函数体开头，保存 store 引用：

```python
_store = store  # 供端点闭包引用
```

- [ ] **Step 6: 运行全部测试确认无回归**

```bash
.venv/bin/python3 -m pytest tests/unit/test_api_server.py -v
```

预期：全部通过。现有测试不传 store，走降级路径（文件扫描），行为不变。

- [ ] **Step 7: 提交**

```bash
git add src/news_sentry/core/api_server.py
git commit -m "Phase 28: API Server 事件端点改用 SQLite 查询 (P28.03)"
```

---

## Task 4: API Server 配置端点加缓存 + POST /config/reload

**Files:**
- Modify: `src/news_sentry/core/api_server.py`

- [ ] **Step 1: 在 create_app 中初始化 ConfigCache**

在 `create_app` 函数体中，在端点定义之前添加：

```python
from news_sentry.core.config_cache import ConfigCache

_config_cache = ConfigCache(ttl=60, maxsize=128)
```

- [ ] **Step 2: 替换所有 _load_yaml_file 调用为 _config_cache.load_yaml**

将配置端点中的 `_load_yaml_file(config_path)` 调用替换为 `_config_cache.load_yaml(config_path)`：

**get_target_config** (原 L490-496):
```python
@app.get("/api/v1/config/targets/{target_id}")
async def get_target_config(target_id: str) -> dict[str, Any]:
    config_path = Path(f"config/targets/{target_id}.yaml")
    data = _config_cache.load_yaml(config_path)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Target '{target_id}' not found")
    return data
```

**get_filter_rules** (原 L549-568):
```python
@app.get(
    "/api/v1/config/targets/{target_id}/filters",
    response_model=FilterRulesResponse,
)
async def get_filter_rules(target_id: str) -> FilterRulesResponse:
    filter_path = Path(f"config/filters/{target_id}/default.yaml")
    data = _config_cache.load_yaml(filter_path)
    # ... 后续逻辑不变
```

**list_destinations** (原 L574-601):
```python
@app.get(
    "/api/v1/config/output/destinations",
    response_model=DestinationListResponse,
)
async def list_destinations() -> DestinationListResponse:
    dest_path = Path("config/output/destinations.yaml")
    data = _config_cache.load_yaml(dest_path)
    # ... 后续逻辑不变
```

**get_provider_routes** (原 L607-636):
```python
@app.get(
    "/api/v1/config/provider/routes",
    response_model=ProviderRoutesResponse,
)
async def get_provider_routes() -> ProviderRoutesResponse:
    routes_path = Path("config/provider/routes.yaml")
    data = _config_cache.load_yaml(routes_path)
    # ... 后续逻辑不变
```

- [ ] **Step 3: 新增 POST /config/reload 端点**

在配置端点区域末尾添加：

```python
@app.post("/api/v1/config/reload")
async def reload_config(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> dict[str, str]:
    """清除配置缓存，下次请求时重新从文件加载。"""
    key = _verify_api_key(x_api_key)
    if not _rate_limiter.check(key):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    _config_cache.reload()
    return {"status": "ok", "message": "Configuration cache cleared"}
```

- [ ] **Step 4: 运行全部测试确认无回归**

```bash
.venv/bin/python3 -m pytest tests/unit/test_api_server.py -v
```

- [ ] **Step 5: 提交**

```bash
git add src/news_sentry/core/api_server.py
git commit -m "Phase 28: 配置端点 TTL 缓存 + POST /config/reload (P28.04)"
```

---

## Task 5: API Server 测试更新 — SQLite 路径

**Files:**
- Modify: `tests/unit/test_api_server.py`

新增一组使用 AsyncStore 的测试，验证 SQLite 查询路径。

- [ ] **Step 1: 新增 SQLite 路径测试类**

在 `tests/unit/test_api_server.py` 中新增：

```python
import pytest
from news_sentry.core.async_store import AsyncStore


class TestAPIServerSQLite:
    """使用 AsyncStore（SQLite）的 API Server 端点测试。"""

    @pytest.fixture
    async def store_with_data(self, tmp_path: Path) -> AsyncStore:
        """创建包含测试数据的 AsyncStore。"""
        db_path = tmp_path / "state.db"
        store = AsyncStore()
        await store.initialize(db_path)

        now = datetime.now(UTC).isoformat()
        events_data = [
            {
                "event_id": "ne-italy-ansa-20260512-aaa11111",
                "source_id": "ansa",
                "news_value_score": 80,
                "china_relevance": 20,
                "classification_l0": "international",
                "title_original": "Pace in Medio Oriente",
            },
            {
                "event_id": "ne-italy-repubblica-20260512-bbb22222",
                "source_id": "repubblica",
                "news_value_score": 60,
                "china_relevance": 40,
                "classification_l0": "politics",
                "title_original": "Elezioni politiche",
            },
            {
                "event_id": "ne-italy-ansa-20260512-ccc33333",
                "source_id": "ansa",
                "news_value_score": 90,
                "china_relevance": 10,
                "classification_l0": "international",
                "title_original": "Accordo commerciale",
            },
        ]

        # 创建对应的 drafts 文件
        drafts_dir = tmp_path / "italy" / "drafts"
        drafts_dir.mkdir(parents=True, exist_ok=True)

        for ev in events_data:
            file_name = f"outputted_{ev['source_id']}_{ev['event_id']}.md"
            file_path = drafts_dir / file_name
            fm_data = {
                "id": ev["event_id"],
                "source_id": ev["source_id"],
                "url": "https://example.com",
                "title_original": ev["title_original"],
                "news_value_score": ev["news_value_score"],
                "china_relevance": ev["china_relevance"],
                "classification": {"l0": ev["classification_l0"]},
                "pipeline_stage": "outputted",
            }
            fm = yaml.dump(fm_data, allow_unicode=True, default_flow_style=False, sort_keys=False)
            file_path.write_text(
                f"---\n{fm}---\n\n# {ev['title_original']}\n\nBody\n",
                encoding="utf-8",
            )

            await store.db.execute_insert(
                "INSERT OR REPLACE INTO event_index "
                "(event_id, target_id, stage, source_id, news_value_score, "
                "china_relevance, classification_l0, title_original, "
                "published_at, file_path, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ev["event_id"],
                    "italy",
                    "drafts",
                    ev["source_id"],
                    ev["news_value_score"],
                    ev["china_relevance"],
                    ev["classification_l0"],
                    ev["title_original"],
                    now,
                    str(file_path),
                    now,
                ),
            )
        await store.db.commit()
        return store

    def _make_client_with_store(self, tmp_path: Path, store: AsyncStore) -> TestClient:
        app = create_app(data_dir=tmp_path, store=store)
        return TestClient(app)

    def test_stats_with_sqlite(
        self, tmp_path: Path, store_with_data: AsyncStore,
    ) -> None:
        client = self._make_client_with_store(tmp_path, store_with_data)
        resp = client.get("/api/v1/stats", params={"target_id": "italy"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_events"] == 3
        assert data["avg_news_value_score"] is not None
        assert data["by_classification"]["international"] == 2
        assert data["by_classification"]["politics"] == 1
        assert data["by_source"]["ansa"] == 2

    def test_list_events_with_sqlite(
        self, tmp_path: Path, store_with_data: AsyncStore,
    ) -> None:
        client = self._make_client_with_store(tmp_path, store_with_data)
        resp = client.get("/api/v1/events", params={"target_id": "italy"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["events"]) == 3

    def test_list_events_pagination_with_sqlite(
        self, tmp_path: Path, store_with_data: AsyncStore,
    ) -> None:
        client = self._make_client_with_store(tmp_path, store_with_data)
        resp = client.get(
            "/api/v1/events",
            params={"target_id": "italy", "page": 1, "page_size": 2},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["events"]) == 2
        assert data["page"] == 1

    def test_list_events_filter_source_with_sqlite(
        self, tmp_path: Path, store_with_data: AsyncStore,
    ) -> None:
        client = self._make_client_with_store(tmp_path, store_with_data)
        resp = client.get(
            "/api/v1/events",
            params={"target_id": "italy", "source_id": "ansa"},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    def test_list_events_filter_classification_with_sqlite(
        self, tmp_path: Path, store_with_data: AsyncStore,
    ) -> None:
        client = self._make_client_with_store(tmp_path, store_with_data)
        resp = client.get(
            "/api/v1/events",
            params={"target_id": "italy", "classification": "politics"},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_list_events_filter_min_score_with_sqlite(
        self, tmp_path: Path, store_with_data: AsyncStore,
    ) -> None:
        client = self._make_client_with_store(tmp_path, store_with_data)
        resp = client.get(
            "/api/v1/events",
            params={"target_id": "italy", "min_score": 70},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    def test_list_events_search_with_sqlite(
        self, tmp_path: Path, store_with_data: AsyncStore,
    ) -> None:
        client = self._make_client_with_store(tmp_path, store_with_data)
        resp = client.get(
            "/api/v1/events",
            params={"target_id": "italy", "search": "pace"},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_get_single_event_with_sqlite(
        self, tmp_path: Path, store_with_data: AsyncStore,
    ) -> None:
        client = self._make_client_with_store(tmp_path, store_with_data)
        resp = client.get(
            "/api/v1/events/ne-italy-ansa-20260512-aaa11111",
            params={"target_id": "italy"},
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == "ne-italy-ansa-20260512-aaa11111"

    def test_get_single_event_not_found_with_sqlite(
        self, tmp_path: Path, store_with_data: AsyncStore,
    ) -> None:
        client = self._make_client_with_store(tmp_path, store_with_data)
        resp = client.get(
            "/api/v1/events/nonexistent",
            params={"target_id": "italy"},
        )
        assert resp.status_code == 404
```

- [ ] **Step 2: 新增 POST /config/reload 测试**

在 `TestConfigAPI` 类中新增：

```python
def test_config_reload_endpoint(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /config/reload 清除配置缓存。"""
    self._setup_config(tmp_path, monkeypatch)
    config_dir = tmp_path / "config" / "targets"
    _write_target_config(config_dir, "italy", "旧名称", "it", 3)

    client = self._make_client(tmp_path)
    resp = client.get("/api/v1/config/targets/italy")
    assert resp.json()["display_name"] == "旧名称"

    # 修改文件
    _write_target_config(config_dir, "italy", "新名称", "it", 3)

    # 缓存未过期，仍返回旧值（若在 TTL 内）
    # 直接调用 reload 端点
    resp = client.post("/api/v1/config/reload")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    # 缓存已清除，应返回新值
    resp = client.get("/api/v1/config/targets/italy")
    assert resp.json()["display_name"] == "新名称"
```

- [ ] **Step 3: 运行全部测试**

```bash
.venv/bin/python3 -m pytest tests/unit/test_api_server.py -v
```

预期：原有测试 + 新增测试全部通过

- [ ] **Step 4: 提交**

```bash
git add tests/unit/test_api_server.py
git commit -m "Phase 28: API Server SQLite 路径测试 + config/reload 测试 (P28.05)"
```

---

## Task 6: Pipeline 集成 — 输出阶段写入 event_index

**Files:**
- Modify: `src/news_sentry/core/async_run.py`

在 async pipeline 的输出阶段，事件写入 .md 文件后同步写入 event_index。

- [ ] **Step 1: 修改 _run_output_async**

在 `src/news_sentry/core/async_run.py` 的 `_run_output_async` 中，事件写入文件后调用 `store.index_event`：

```python
async def _run_output_async(
    config, events: list, *, run_id: str, run_log, file_writer, ctx,
    store: AsyncStore | None = None,
) -> list:
    """异步输出阶段：写 Markdown + 推送告警 + 更新 event_index。"""
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

    result = await asyncio.to_thread(_sync_output)

    # 同步写入 event_index（SQLite 索引）
    if store is not None:
        for event in result:
            file_name = f"outputted_{event.source_id}_{event.id}.md"
            file_path = str(config.output_root / config.target_id / "drafts" / file_name)
            await store.index_event(
                event=event,
                stage="drafts",
                file_path=file_path,
            )

    return result
```

- [ ] **Step 2: 修改 bounded_run_async 传递 store**

在 `bounded_run_async` 中初始化 store 并传递给各阶段：

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
) -> PipelineContext:
    """异步版 pipeline 入口。"""
    # ... 现有初始化代码 ...

    # 初始化 AsyncStore（P26 基础设施）
    from news_sentry.core.async_store import AsyncStore
    db_path = output_dir / "state.db"
    store = AsyncStore()
    await store.initialize(db_path)

    try:
        async with httpx.AsyncClient(timeout=30.0) as http_client:
            if stage == "all":
                events = await _run_collect_async(...)
                events = await _run_filter_async(...)
                events = await _run_judge_async(...)
                await _run_output_async(
                    config, events, run_id=ctx.run_id,
                    run_log=None, file_writer=file_writer, ctx=ctx,
                    store=store,  # 传递 store
                )
            # ... 其他 stage 分支 ...
    finally:
        await store.close()

    return ctx
```

- [ ] **Step 3: 更新 index_event 方法签名**

确认 `AsyncStore.index_event` 接受 `NewsEvent` 对象并提取字段写入 event_index：

```python
async def index_event(
    self,
    event: NewsEvent,
    stage: str,
    file_path: str | None,
) -> None:
    """将事件索引写入 event_index 表。"""
    classification_l0 = None
    cls_data = event.metadata.get("classification")
    if isinstance(cls_data, dict):
        classification_l0 = cls_data.get("l0")

    await self.db.execute_insert(
        "INSERT OR REPLACE INTO event_index "
        "(event_id, target_id, stage, source_id, news_value_score, "
        "china_relevance, classification_l0, title_original, "
        "published_at, file_path, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            event.id,
            event.metadata.get("target_id", ""),
            stage,
            event.source_id,
            event.news_value_score,
            event.china_relevance,
            classification_l0,
            event.title_original,
            event.published_at,
            file_path,
            datetime.now(UTC).isoformat(),
        ),
    )
    await self.db.commit()
```

- [ ] **Step 4: 运行全部测试确认无回归**

```bash
.venv/bin/python3 -m pytest tests/ -q
```

- [ ] **Step 5: 提交**

```bash
git add src/news_sentry/core/async_run.py src/news_sentry/core/async_store.py
git commit -m "Phase 28: Pipeline 输出阶段同步写入 event_index (P28.06)"
```

---

## Task 7: 集成验证与清理

- [ ] **Step 1: 运行完整检查**

```bash
ruff check src/news_sentry/core/api_server.py src/news_sentry/core/config_cache.py src/news_sentry/core/async_store.py src/news_sentry/core/async_run.py
.venv/bin/python3 -m mypy src/news_sentry/core/api_server.py src/news_sentry/core/config_cache.py src/news_sentry/core/async_store.py
.venv/bin/python3 -m pytest tests/ -q
```

预期：ruff=0, mypy=0, 全部测试通过

- [ ] **Step 2: 确认覆盖率未下降**

```bash
.venv/bin/python3 -m pytest tests/ --cov=news_sentry -q 2>&1 | tail -5
```

预期：覆盖率 >= 92%

- [ ] **Step 3: 最终提交**

```bash
git commit --allow-empty -m "Phase 28: 集成验证通过 — API Server SQLite 查询 + 配置缓存 (P28.00)"
```

---

## 验证标准

Phase 28 完成的验收条件：

- [ ] 全部测试通过（CI 绿色）
- [ ] ruff check = 0, mypy = 0
- [ ] 测试覆盖率 >= 92%
- [ ] GET /events 改用 SQLite 分页查询（store 存在时）
- [ ] GET /stats 改用 SQLite 聚合查询（store 存在时）
- [ ] GET /events/{id} 改用 SQLite file_path 查找（store 存在时）
- [ ] GET /config/* 端点使用 TTLCache（TTL=60s）
- [ ] POST /config/reload 端点清除缓存
- [ ] Pipeline 输出阶段同步写入 event_index
- [ ] 现有端点 URL 路径和参数签名不变
- [ ] 无 store 时降级到原文件扫描路径（向后兼容）
- [ ] 新增文件：`config_cache.py`
- [ ] 新增依赖：`cachetools>=5.3`

### 性能基准预期

| 端点 | 当前（文件扫描） | 优化后（SQLite） |
|------|----------------|----------------|
| GET /events (1000 事件) | ~800ms | <20ms |
| GET /stats (1000 事件) | ~800ms | <5ms |
| GET /events/{id} (1000 事件) | ~400ms | <5ms |
| GET /config/* (连续请求) | ~50ms/次 | <1ms/次（缓存命中） |
