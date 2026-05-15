# NewsSentry 性能全面优化设计

> 日期：2026-05-15
> 状态：设计确认
> 范围：Phase 25-29

## 1. 背景与问题

当前 NewsSentry v1.1.0（1298 tests, 92% coverage）存在以下性能瓶颈：

| 瓶颈 | 原因 | 影响 |
|------|------|------|
| 采集全串行 | 70+ RSS/API 源逐个同步抓取，每源间 ~5s 等待 | 单次采集 ~350s |
| AI 调用全串行 | 翻译/研判逐事件调用 LLM，无批处理无并发 | 70 事件翻译 ~210s |
| 阶段间文件传递 | 每阶段结束写 Markdown，下阶段全量读回解析 | 大量冗余 IO |
| Memory 全量序列化 | 每次 `mark_known()` 将整个 dict 写入 YAML | 随 known_ids 增长线性劣化 |
| API Server 无缓存 | 每次请求全量读取解析所有 drafts 文件 | 事件多时秒级响应 |
| 配置无跨 run 缓存 | 每次运行重新加载 70+ YAML + Schema 校验 | 启动开销 ~2-3s |
| 零 async | 整个后端同步阻塞，仅 FastAPI 端点签名用了 async def | 无法并发 |

## 2. 技术决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 执行模型 | 全面 async/await | ThreadPool 受 GIL 限制，长期天花板低 |
| 存储层 | SQLite (aiosqlite) | 零外部依赖、单文件便携、原生索引 |
| 迁移策略 | 渐进式 Phase 迁移 | 每步可验证、可回滚、可交付 |
| CLI 入口 | 保持同步，asyncio.run() 桥接 | Click 标准做法，改动最小 |
| 批处理格式 | JSON 数组（非行文本） | 避免依赖 LLM 严格按行返回 |
| 研判策略 | 不做批处理，只做并发 | 研判涉及多维度评分，批处理会损失质量 |

## 3. 目标架构

```
CLI (同步) ──asyncio.run()──→ bounded_run_async()
  → ConfigLoader (async, LRU 缓存)
  → Collect  [asyncio.gather 并发采集]
  → Filter   [内存传递 list[NewsEvent]]
  → Judge    [翻译批处理+并发, 研判并发+缓存]
  → Output   [SQLite 持久化 + 并发告警推送]
```

### 异步执行模型

```
┌─────────────────────────────────────────────┐
│                   CLI 层                     │
│  click 命令 (同步) ── asyncio.run() ──────→ │
├─────────────────────────────────────────────┤
│              Async Pipeline 核心              │
│                                             │
│  ConfigLoader ─── async, LRU 缓存跨 run     │
│       │                                     │
│  Collect ─── asyncio.gather(70+ 源并发)      │
│       │        httpx.AsyncClient 连接池复用   │
│       ▼                                     │
│  Filter ─── 内存 list[NewsEvent] 传递        │
│       │        (不再写/读中间文件)             │
│       ▼                                     │
│  Judge ─── 翻译: JSON 数组批处理 + 并发       │
│       │        研判: 逐事件并发 + LLM 缓存     │
│       │        分级模型路由 (低/中/高置信度)    │
│       ▼                                     │
│  Output ─── SQLite 持久化 + 并发告警推送      │
│       │        httpx.AsyncClient for 推送     │
│       ▼                                     │
│  Memory ─── asyncio.Lock + 增量 SQLite 写入  │
├─────────────────────────────────────────────┤
│              存储层                           │
│  SQLite (aiosqlite) ── 状态 + 索引 + 缓存     │
│  文件系统 ── 仅保留 Markdown 输出 (drafts/)   │
│  YAML 配置 ── 不变，加载方式改 async          │
└─────────────────────────────────────────────┘
```

### 关键设计决策

1. **CLI 保持同步入口**：Click 命令不改，通过 `asyncio.run()` 调用 async pipeline。
2. **直接 async 化，不保留同步版本**：避免双接口维护负担。
3. **SQLite 作为统一存储**：事件索引、Memory 状态、LLM 缓存统一走 SQLite。
4. **文件系统保留**：`raw/`、`evaluated/`、`drafts/` 保留用于人工审查和 Markdown 输出，但不再是阶段间数据传递机制。
5. **连接池复用**：全局 `httpx.AsyncClient` 实例，所有 HTTP 操作共享。

## 4. SQLite 存储层设计

### 为什么是 SQLite

- 零外部依赖，Python 内置模块
- 单文件便携：`data/{target_id}/state.db`，与当前目录协议一致
- 本地 SSD 上单次写入 ~0.1ms，查询 ~0.05ms
- aiosqlite 提供完整 async 接口

### Schema

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
    metadata    TEXT                -- JSON
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
    event_id    TEXT PRIMARY KEY,
    target_id   TEXT NOT NULL,
    stage       TEXT NOT NULL,     -- raw/evaluated/drafts
    file_path   TEXT,              -- 对应的 .md 文件路径
    severity    INTEGER,
    confidence  REAL,
    published_at TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX idx_event_target_stage ON event_index(target_id, stage);
CREATE INDEX idx_event_severity ON event_index(severity DESC);
```

### LLM 缓存淘汰策略

- **翻译缓存**：容量上限 10000 条，LRU 淘汰。淘汰 SQL：`DELETE FROM llm_cache WHERE cache_key IN (SELECT cache_key FROM llm_cache ORDER BY updated_at ASC LIMIT N)`
- **研判缓存**：永不过期。同一 event_id + 同一 rules_version 的结果不会变。
- **缓存 key**：`SHA-256(prompt_text + model_id + temperature)`，翻译和研判用不同的 prompt 前缀区分命名空间。

### 存储层接口

```python
class AsyncStore:
    async def initialize(self, db_path: Path) -> None: ...
    async def close(self) -> None: ...

    # Memory 操作
    async def is_known(self, event_id: str) -> bool: ...
    async def mark_known(self, event_id: str) -> None: ...
    async def prune_old_ids(self, max_age_days: int) -> int: ...

    # Source Health
    async def get_source_health(self, source_id: str) -> dict | None: ...
    async def record_source_health(self, source_id: str, status: str, ...) -> None: ...

    # Cursor
    async def get_cursor(self, source_id: str) -> str | None: ...
    async def set_cursor(self, source_id: str, cursor: str) -> None: ...

    # LLM Cache
    async def get_cached_response(self, cache_key: str) -> str | None: ...
    async def set_cached_response(self, cache_key: str, response: str, model: str) -> None: ...
    async def evict_if_needed(self, max_entries: int) -> int: ...

    # Event Index
    async def index_event(self, event: NewsEvent, stage: str, file_path: str | None) -> None: ...
    async def query_events(self, target_id: str, stage: str, **filters) -> list[dict]: ...
    async def get_event_count(self, target_id: str, stage: str) -> int: ...
    async def get_stats(self, target_id: str) -> dict: ...
```

### 与现有 Memory 的映射

| 现有方法 | SQLite 操作 | 性能变化 |
|---------|------------|---------|
| `is_known(id)` | `SELECT 1 FROM known_ids WHERE event_id=?` | O(1) 索引查询 |
| `mark_known(id)` | `INSERT OR IGNORE INTO known_ids` | 增量写入，替代全量序列化 |
| `get_source_health(id)` | `SELECT * FROM source_health WHERE source_id=?` | 同 |
| `record_source_health(...)` | `INSERT OR REPLACE INTO source_health` | 增量写入 |
| `get/set_cursor()` | `SELECT/INSERT cursor` | 增量写入 |

### SQLite 配置

```python
PRAGMA journal_mode=WAL;      -- 并发读写
PRAGMA synchronous=NORMAL;    -- 写入性能与安全平衡
PRAGMA cache_size=-64000;     -- 64MB 缓存
PRAGMA foreign_keys=ON;
```

### 向后兼容

首次运行时自动检测：如果 `data/{target}/memory/known_item_ids.yaml` 存在但 `state.db` 不存在，自动迁移 YAML 数据到 SQLite。迁移完成后 YAML 文件保留但不再写入。

## 5. 并发采集设计

### 执行模型

```
_run_collect_async()
  │
  ├─ httpx.AsyncClient (全局连接池)
  │
  ├─ asyncio.Semaphore(10)  ← 单 target 并发上限
  │
  └─ asyncio.gather(
       collect(rss_source_1),
       collect(rss_source_2),
       ...
       collect(rss_source_70),
     )
```

### 令牌桶速率限制

替代当前固定间隔的 `RateLimiter`：

```python
class AsyncRateLimiter:
    def __init__(self, rate: float, burst: int = 10):
        self._rate = rate          # 令牌/秒
        self._burst = burst        # 桶容量
        self._tokens = burst
        self._last = asyncio.get_event_loop().time()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = asyncio.get_event_loop().time()
            self._tokens = min(self._burst, self._tokens + (now - self._last) * self._rate)
            self._last = now
            if self._tokens < 1:
                await asyncio.sleep((1 - self._tokens) / self._rate)
                self._tokens = 0
            else:
                self._tokens -= 1
```

- 允许短时间突发（burst=10），但平均速率不超限
- 每个源可独立配置速率

### 错误处理

- 每个源独立超时 30s，指数退避重试 3 次（1s, 2s, 4s）
- 单源失败不阻塞其他源，记录到 source_health
- feedparser 解析直接在 event loop 中同步调用（<10ms），大 feed 用 `asyncio.to_thread`

### 预期效果

70+ 源：~350s → ~30-40s（10 并发 x 平均 3s/源 + 令牌桶开销）

## 6. AI 调用优化设计

### 翻译：JSON 数组批处理 + 并发

**批处理 prompt 格式**：

```json
{
  "translations": [
    {"id": 0, "title": "Original title 1", "summary": "..."},
    {"id": 1, "title": "Original title 2", "summary": "..."}
  ]
}
```

期望输出：

```json
{
  "translations": [
    {"id": 0, "title": "翻译标题 1", "summary": "翻译摘要 1"},
    {"id": 1, "title": "翻译标题 2", "summary": "翻译摘要 2"}
  ]
}
```

- 通过 `response_format={"type": "json_object"}` 强制 JSON 输出
- `id` 字段做匹配校验，不依赖返回顺序
- 批次大小可配置（默认 10，通过 `provider_routes.yaml` 的 `batch_size`）
- 批处理失败自动降级为逐条重试

**并发执行**：

```
7 批次 × asyncio.Semaphore(5) = 最差 2 轮
→ 从 ~210s (70x3s 串行) 降至 ~6s
```

### 研判：逐事件并发 + 缓存

研判不做批处理（涉及多维度评分，批处理会损失质量），改为：
- 并发调用：`asyncio.gather` + `Semaphore(5)`
- LLM 缓存：`cache_key = SHA-256(event_id + rules_version + model)`，命中则跳过 API 调用

### 分级模型路由

在 `confidence_router.py` 基础上扩展：

```
规则引擎结果 → confidence >= 0.85 → 直接通过，不调 LLM
             → 0.5 <= confidence < 0.85 → gpt-4o-mini / claude-haiku (快速+便宜)
             → confidence < 0.5 → gpt-4o / claude-sonnet (精准+贵)
```

通过 `provider_routes.yaml` 新增 `confidence_tiers` 配置段实现。

### 三维度叠加效果

```
翻译：70 次 API 调用 → 7 批次 × 2 轮 = ~6s（缓存命中时更快）
研判：按需并发 + 缓存过滤
总体 AI 调用时间：~210s → ~6-10s
```

## 7. API Server 重构设计

### 查询方式变更

| 端点 | 当前 | 优化后 |
|------|------|--------|
| `GET /stats` | 全量读文件 → 计算 | `SELECT COUNT, AVG` 聚合 |
| `GET /events` | 全量读文件 → 过滤 | `SELECT * FROM event_index WHERE ... LIMIT OFFSET` |
| `GET /events/{id}` | 遍历所有文件 | `SELECT file_path FROM event_index WHERE event_id=?` |
| `GET /config/*` | 每次读 YAML | LRU 缓存 (TTL 60s) |

### 配置缓存

- `cachetools.TTLCache`（或自实现带过期的缓存）包装配置加载函数，TTL 60s
- 配置变更通过 `POST /config/reload` 端点主动失效缓存
- 运行时配置（provider_routes、output_destinations）支持热更新

### Markdown 文件保留

SQLite 只存索引字段（event_id, severity, confidence, published_at 等）。完整事件内容仍存在 `drafts/*.md`，通过 `file_path` 字段关联。查询时先从 SQLite 拿索引，需要完整内容再读对应 .md 文件。

## 8. 多 Target 并发调度设计

### 执行模型

```
bounded_run_async(targets=["all"])
  │
  ├─ 全局 httpx.AsyncClient (共享连接池)
  ├─ FairScheduler (公平分配并发槽位)
  │
  └─ asyncio.gather(
       run_target("italy"),           ──→ state.db (it)
       run_target("china-watch-en"),  ──→ state.db (en)
       run_target("japan"),           ──→ state.db (jp)
       run_target("germany"),         ──→ state.db (de)
       run_target("france"),          ──→ state.db (fr)
     )
```

### 公平调度

每个 target 保证至少 5 个并发槽位，剩余槽位按需动态分配。先完成先释放，不饿死任何 target。

```python
class FairScheduler:
    def __init__(self, per_target_min: int = 5, global_max: int = 30):
        self._per_target_min = per_target_min
        self._global = asyncio.Semaphore(global_max)
        self._per_target: dict[str, asyncio.Semaphore] = {}

    async def acquire(self, target_id: str) -> None:
        await self._per_target[target_id].acquire()
        await self._global.acquire()

    def release(self, target_id: str) -> None:
        self._per_target[target_id].release()
        self._global.release()
```

### 资源隔离

- 每个 target 独立 SQLite db，无跨 target 锁竞争
- Memory 状态独立，known_ids 不互相干扰
- AI 预算共享，通过 asyncio.Lock 保护防超支

### CLI 扩展

```bash
# 现有用法不变
python -m news_sentry.cli run --target italy --stage all

# 新增：多 target 并发
python -m news_sentry.cli run --target all --stage all
python -m news_sentry.cli run --target italy,japan --stage collect

# 新增：循环运行（自包含调度）
python -m news_sentry.cli run --target all --stage all --interval 300
```

`--interval N` 让进程以 N 秒为周期循环执行完整 pipeline，用 `asyncio.sleep(interval)` 在轮次间等待。

### 预期效果

5 target 并发运行，总耗时接近单个 target（~40-60s），吞吐量提升 ~4x。

## 9. Phase 迁移路线图

| Phase | 内容 | 关键改动 | 预期性能提升 |
|-------|------|---------|-------------|
| P25 | async 基础设施 + 并发采集 | httpx.AsyncClient, asyncio.gather 采集, asyncio.run() CLI 桥接, 令牌桶 RateLimiter | 采集 ~350s → ~35s |
| P26 | SQLite 存储层 | AsyncStore, Schema 初始化, Memory 重写, YAML→SQLite 迁移, event_index | Memory 增量写入, API 查询基础 |
| P27 | AI 调用优化 | 翻译 JSON 批处理, 并发调用, LLM 缓存, 分级模型路由 | 翻译/研判 ~210s → ~6-10s |
| P28 | API Server 重构 | SQLite 查询替代文件扫描, 分页, 配置 LRU 缓存 | 响应秒级 → 毫秒级 |
| P29 | 多 target 并发调度 | FairScheduler, --target all, --interval 循环运行 | 5 target 吞吐量 ~4x |

### 端到端预期效果

- **单 target 单次 run**：~10min → ~1min
- **5 target 并发总耗时**：~50min → ~1-2min
- **API Server 响应**：秒级 → 毫秒级

### 依赖关系

```
P25 (async 基础) ──→ P26 (SQLite)
                  ──→ P27 (AI 优化，依赖 P25 async + P26 缓存)
P26 (SQLite)     ──→ P28 (API Server，依赖 event_index)
P25 + P26 + P27  ──→ P29 (多 target，依赖全部基础设施)
```

### 回滚策略

每个 Phase 保留旧的同步/YAML 代码路径，通过 feature flag 切换：

- **Feature flag**：`config/deployment/{profile}.yaml` 中新增 `use_async_pipeline: bool` 和 `use_sqlite_store: bool`，默认 `false`。每个 Phase 完成后将对应 flag 翻转为 `true`。
- **YAML 回退**：SQLite 迁移后 YAML 文件保留不删除。如需回退，CLI 新增 `--fallback-yaml` 选项，跳过 SQLite 直接读写原有 YAML 文件。
- **回滚触发条件**（任一满足即回滚）：
  - 测试覆盖率下降 > 5%
  - 性能基准退化 > 10%
  - 数据不一致（SQLite 与 YAML 数据校验失败）
- **回滚操作**：`git revert` 对应 Phase 的 commit，恢复 feature flag 为 `false`。无需数据库迁移回退，因为 SQLite 和 YAML 在迁移后并行存在。

### 测试迁移策略

当前 1298 个测试全部基于同步 API。async 化需要同步迁移测试基础设施。

**P25 测试基础设施**（前置工作，优先于业务代码改动）：
- `conftest.py` 新增 `@pytest.fixture` async 版本：`async_http_client`、`async_store`、`async_memory`
- `pytest.ini` 或 `pyproject.toml` 配置 `asyncio_mode = "auto"`，支持混合同步/异步测试
- 引入 `pytest-asyncio` 的 `@pytest.mark.asyncio` 标记

**每个 Phase 的测试迁移**：

| Phase | 测试工作量 | 说明 |
|-------|-----------|------|
| P25 | 中 | 采集相关测试改为 async（mock httpx.AsyncClient），约 30-40 个测试 |
| P26 | 高 | Memory 相关测试全部重写（mock aiosqlite），约 50-60 个测试；新增 YAML→SQLite 迁移测试 |
| P27 | 中 | AI Provider 测试改为 async，新增缓存和批处理测试，约 20-30 个测试 |
| P28 | 低 | API Server 测试改为 async client，约 15-20 个测试 |
| P29 | 中 | 新增多 target 并发集成测试，约 10-15 个测试 |

**测试原则**：
- 旧同步测试在对应模块 async 化后删除，不保留两套
- 每个 Phase 完成后测试总数不应减少，新增测试覆盖 async 路径
- Mock 策略：HTTP 用 `httpx.AsyncClient` mock，SQLite 用 `aiosqlite` 内存数据库（`:memory:`），避免文件依赖

### 验证标准

每个 Phase 完成的验收条件：
- 现有测试全部通过（CI 绿色）
- 新增 async 测试覆盖新增代码路径
- `ruff check` + `mypy` 零错误
- 测试覆盖率不低于 Phase 开始前水平
- 性能基准：记录 Phase 前后 `bounded_run` 端到端时间，量化改善
- SQLite 迁移验证（P26）：YAML 数据完整性迁移到 SQLite 后数据一致
