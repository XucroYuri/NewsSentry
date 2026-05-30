# Phase 32: Entity Tracking & Cross-Reference — 设计文档

> 日期: 2026-05-16
> 状态: 设计确认
> 前置: Phase 31 NLP 数据 API 暴露完成 (1511 tests, 92% coverage)

## 1. 背景与目标

Phase 30/31 建立了 NLP 实体提取能力（NLPRulesAnalyzer + NLPAIAnalyzer）并将实体数据暴露到 SQLite event_index 和 API。但实体数据仍是"一次性"的——每次 run 独立提取后丢弃，无法跨 run 追踪。

**目标:** 新增 `entities` 表持久化实体，支持跨 run 累计统计和 API 查询。

**非目标:** 实体关系图谱、跨语言别名合并、实体趋势报告生成。

## 2. 技术决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 主键策略 | INTEGER AUTOINCREMENT + UNIQUE(canonical_name, entity_type) | 避免小写名碰撞风险，整数主键 JOIN 更快 |
| 去重逻辑 | ON CONFLICT DO UPDATE 累加 mention_count | 单条 SQL 原子操作，无读-改-写竞态 |
| 关联事件查询 | 复用 event_index.entity_names LIKE 匹配 | 不做 junction 表，YAGNI |
| 实体规范化 | 首次提取的原始名作为 canonical_name | 不做小写转换，保留原始大小写 |

## 3. SQLite entities 表

### 3.1 Schema

```sql
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    mention_count INTEGER DEFAULT 1,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    target_ids TEXT DEFAULT '',
    UNIQUE(canonical_name, entity_type)
);
```

### 3.2 Indexes

```sql
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_mentions ON entities(mention_count DESC);
CREATE INDEX IF NOT EXISTS idx_entities_last_seen ON entities(last_seen DESC);
```

### 3.3 Migration

在 `AsyncStore.initialize()` 中执行 `CREATE TABLE IF NOT EXISTS`（幂等，与现有模式一致）。

## 4. 实体持久化逻辑

### 4.1 集成点

`async_run.py` 的 NLP 增强之后，遍历 `nlp_analysis.entities` 逐个调用 `store.upsert_entity()`。异常不阻塞 pipeline。

### 4.2 upsert_entity 方法

```python
async def upsert_entity(self, name: str, entity_type: str,
                        target_id: str, seen_at: str) -> None:
    # INSERT ... ON CONFLICT(canonical_name, entity_type) DO UPDATE SET
    #   mention_count = mention_count + 1,
    #   last_seen = excluded.last_seen,
    #   target_ids = CASE
    #     WHEN ',' || target_ids || ',' LIKE '%,' || excluded.target_id || ',%' THEN target_ids
    #     ELSE target_ids || ',' || excluded.target_id
    #   END
```

## 5. AsyncStore 查询方法

### 5.1 query_entities

```python
async def query_entities(
    self,
    entity_type: str | None = None,
    target_id: str | None = None,
    min_mentions: int = 1,
    limit: int = 20,
    sort: str = "mention_count",
) -> list[dict]: ...
```

WHERE 条件：`entity_type = ?` / `target_ids LIKE '%target_id%'` / `mention_count >= ?`。
ORDER BY：`mention_count DESC` 或 `last_seen DESC`。

### 5.2 query_entity_detail

```python
async def query_entity_detail(self, entity_id: int) -> dict | None:
    # 1. SELECT FROM entities WHERE id = ?
    # 2. SELECT FROM event_index WHERE entity_names LIKE '%name%'
    #    ORDER BY published_at DESC LIMIT 10
```

### 5.3 get_stats_aggregated 扩展

在现有 stats 查询中追加 `top_entities`：
```sql
SELECT canonical_name, entity_type, mention_count
FROM entities ORDER BY mention_count DESC LIMIT 10
```

## 6. API Server 端点

### 6.1 GET /api/v1/entities

| 参数 | 类型 | 说明 |
|------|------|------|
| `entity_type` | str \| None | person/organization/location/event |
| `target_id` | str \| None | 过滤目标 |
| `min_mentions` | int \| None | 最少提及次数（默认 1） |
| `limit` | int | 返回数量（默认 20，最大 100） |
| `sort` | str | mention_count（默认）或 last_seen |

认证：需要 X-API-Key。

### 6.2 GET /api/v1/entities/{entity_id}

返回实体详情 + recent_events（最多 10 条关联事件，复用 event_index LIKE 查询）。

### 6.3 GET /api/v1/stats 扩展

StatsResponse 增加 `top_entities` 字段（mention_count TOP 10）。

## 7. 文件变更清单

| 文件 | 动作 | 职责 |
|------|------|------|
| `src/news_sentry/core/async_store.py` | 修改 | entities 表 DDL + upsert_entity + query_entities + query_entity_detail + stats 扩展 |
| `src/news_sentry/core/api_server.py` | 修改 | 2 个新端点 + StatsResponse 扩展 |
| `src/news_sentry/core/async_run.py` | 修改 | NLP 增强后实体持久化 |
| `tests/unit/test_async_store.py` | 修改 | 6 个新测试 |
| `tests/unit/test_api_server.py` | 修改 | 5 个新测试 |
| `tests/unit/test_run.py` | 修改 | 1 个集成测试 |

## 8. 测试策略

| 层级 | 测试内容 | 数量 |
|------|---------|------|
| AsyncStore | 表创建、upsert 新实体、upsert 累加、target_ids 追加、query_entities 过滤排序、query_entity_detail 关联事件 | 6 |
| API Server | /entities 默认列表、entity_type 过滤、min_mentions 过滤、/entities/{id} 详情、stats top_entities | 5 |
| 集成 | async_run 实体持久化（mock store） | 1 |

约 12 个新测试，总量 1511 + 12 = 1523。

## 9. 验收标准

1. 1511 现有测试零破坏
2. entities 表正确创建，UNIQUE(canonical_name, entity_type) 约束生效
3. 相同实体 upsert 时 mention_count 累加而非重复插入
4. API `/api/v1/entities` 支持 entity_type/target_id/min_mentions/sort 过滤
5. API `/api/v1/entities/{id}` 返回实体详情 + 关联事件
6. API `/api/v1/stats` 返回 top_entities
7. ruff=0, mypy=0, coverage >= 92%
