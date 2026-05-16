# Phase 31: NLP 数据 API 暴露 + SQLite 索引增强 — 设计文档

> 日期: 2026-05-16
> 状态: 设计确认
> 前置: Phase 30 多语言 NLP 深度分析完成 (1504 tests, 92% coverage)

## 1. 背景与目标

Phase 30 完成了 NLP 分析能力（NLPRulesAnalyzer + NLPAIAnalyzer + NLPAnalyzer 编排器），但产出的 NLPAnalysis 数据（sentiment/entities/topic_tags/event_relations）被困在内存和 Markdown frontmatter 中（仅 sentiment_score 被写入）。

API Server 和 SQLite event_index 都无法查询 NLP 维度：
- event_index 表无 sentiment/entities/topic_tags 列
- API `/api/v1/events` 无按情感/实体/主题过滤参数
- `/api/v1/stats` 无情感分布统计

**目标:** 打通 frontmatter → SQLite → API 三层，让 NLP 数据完全可查询可消费。

**非目标:** 知识图谱、实体关系追踪、趋势时间序列 API。

## 2. 技术决策

| 决策 | 选择 | 理由 |
|------|------|------|
| SQLite 存储策略 | 窄列（sentiment/entity_names/topic_tags） | SQL 直接过滤，无需 JSON 解析，索引友好 |
| Frontmatter NLP 写入 | 去掉 sentiment_confidence | 置信度是内部指标，frontmatter 面向阅读者 |
| Schema Migration | ALTER TABLE ADD COLUMN | 沿用 yaml_migration 模式，检测列存在再添加 |
| entity/topic_tag 查询 | LIKE '%keyword%' 参数化 | 逗号分隔字符串，参数化查询防注入 |

## 3. Frontmatter 写入扩展

在 `markdown_writer.py` 的 `_build_frontmatter_dict` 中，`sentiment_score` 之后写入：

```yaml
sentiment: positive              # Sentiment enum value
nlp_entities:                    # list[NLPEntity]
  - name: Meloni
    entity_type: person
    relevance: 80
  - name: Roma
    entity_type: location
    relevance: 50
topic_tags:                      # list[str]
  - politics
event_relations:                 # list[str]（通常 AI 填充）
  - "与上周预算案关联"
```

条件写入：只在 `nlp_analysis is not None` 时写入，保持无 NLP 数据的事件 frontmatter 不变。

不写入 `sentiment_confidence`（内部指标，面向升级判断而非阅读者）。

## 4. SQLite event_index 扩展

### 4.1 新增列

```sql
sentiment TEXT,           -- "positive"/"negative"/"neutral" 或 NULL
entity_names TEXT,        -- 逗号分隔，如 "Meloni,Roma" 或 NULL
topic_tags TEXT           -- 逗号分隔，如 "politics,economy" 或 NULL
```

### 4.2 Migration

在 `AsyncStore.initialize()` 中执行 `ALTER TABLE ADD COLUMN`，检测列是否存在再添加（与 Phase 26 模式一致）。

新增索引：
- `idx_event_sentiment ON event_index(sentiment)` — sentiment 选择性低但查询频率高
- `idx_event_topic_tags ON event_index(topic_tags)` — topic_tags 选择性高

### 4.3 写入逻辑

`upsert_event()` 中从 `event.judge_result.nlp_analysis` 提取：
- `sentiment` → `nlp.sentiment.value`（StrEnum 转 str）
- `entity_names` → `",".join(e.name for e in nlp.entities)`
- `topic_tags` → `",".join(nlp.topic_tags)`

nlp_analysis 为 None 时写入 NULL。

### 4.4 查询扩展

`query_events_paginated()` 增加过滤参数：
- `sentiment: str | None` → `WHERE sentiment = ?`
- `entity_name: str | None` → `WHERE ',' || entity_names || ',' LIKE '%,' || ? || ',%'`（精确匹配逗号分隔项）
- `topic_tag: str | None` → 同上模式

## 5. API Server 过滤参数

### 5.1 list_events 新增参数

```
GET /api/v1/events?target_id=italy&sentiment=negative&entity=Meloni&topic_tag=politics
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `sentiment` | str \| None | "positive"/"negative"/"neutral" |
| `entity` | str \| None | 实体名精确匹配 |
| `topic_tag` | str \| None | 主题标签精确匹配 |

传入 `query_events_paginated()` 对应的 WHERE 条件。

### 5.2 stats 情感分布

`/api/v1/stats` 响应增加 `sentiment_breakdown` 字段：

```json
{
  "total_events": 150,
  "sentiment_breakdown": {
    "positive": 12,
    "negative": 45,
    "neutral": 30,
    "none": 63
  }
}
```

### 5.3 get_event

不变。已通过 `_load_event_by_path` 返回完整 frontmatter，NLP 字段会自动包含。

## 6. 文件变更清单

| 文件 | 动作 | 职责 |
|------|------|------|
| `src/news_sentry/skills/output/markdown_writer.py` | 修改 | 写入 sentiment/nlp_entities/topic_tags/event_relations |
| `src/news_sentry/core/async_store.py` | 修改 | event_index 加 3 列 + migration + upsert 扩展 + 查询扩展 |
| `src/news_sentry/core/api_server.py` | 修改 | list_events 加 3 个过滤参数 + stats 加 sentiment 分布 |
| `tests/unit/test_markdown_writer.py` | 修改 | 验证 NLP 字段写入 |
| `tests/unit/test_async_store.py` | 修改 | 验证新列写入和过滤查询 |
| `tests/unit/test_api_server.py` | 修改 | 验证新过滤参数和统计 |

## 7. 测试策略

| 层级 | 测试内容 | 数量 |
|------|---------|------|
| Frontmatter | NLP 字段写入、无 NLP 时不写入、部分字段缺失 | 3 |
| AsyncStore | 迁移执行、新列写入、sentiment/entity/topic_tag 过滤 | 7 |
| API Server | 3 个新过滤参数、stats sentiment_breakdown | 5 |

约 15 个新测试，总量 1504 + 15 = 1519。

## 8. 验收标准

1. 1504 现有测试零破坏
2. frontmatter 包含 sentiment/nlp_entities/topic_tags/event_relations（条件写入）
3. SQLite event_index 包含 sentiment/entity_names/topic_tags 列，可过滤查询
4. API `/api/v1/events` 支持 sentiment/entity/topic_tag 查询参数
5. API `/api/v1/stats` 返回 sentiment_breakdown
6. ruff=0, mypy=0
7. 1519 tests，coverage >= 92%
