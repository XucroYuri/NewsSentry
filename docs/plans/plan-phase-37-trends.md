# Phase 37: 量化趋势分析 — 设计文档

> 日期: 2026-05-16
> 状态: 设计确认
> 前置: Phase 36 事件时间线叙事完成 (1559 tests, 92% coverage)

## 1. 背景与目标

Phase 35-36 建立了事件追踪链和 AI 叙事能力。但系统仍缺乏量化趋势分析——无法回答"哪些主题在升温？""情感趋势如何变化？"等问题。

**目标：** 基于已有 event_index 数据，实现按天聚合的主题热度趋势和情感分布趋势，在 Web UI 中以折线图/面积图展示。

**非目标：** 实体活跃度趋势、预测分析、跨 target 趋势对比。

## 2. 技术决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 趋势核心 | 主题热度趋势 | 数据基础最充分（topic_tags 已索引），与现有 TrendReport 模型对齐 |
| 时间粒度 | 按天聚合 | 与 pipeline 每日运行周期对齐，数据点稳定 |
| 图表库 | Chart.js (CDN) | ~10KB gzip，支持折线图/面积图，无需构建工具 |
| 计算方式 | 实时 SQL 聚合 | 数据量可控（单 target 日均百级事件），无需预计算 |
| 趋势判定 | 近 7 天 vs 前 7 天对比 | 简单直观，rising/stable/falling 三级 |

## 3. 数据层

### 3.1 AsyncStore 新增 3 个聚合查询方法

**`get_topic_daily_counts(target_id, days=14)`**

按天分桶统计每个 topic_tags 的出现次数。topic_tags 字段为逗号分隔，需拆分统计：

```sql
WITH split_topics AS (
    SELECT TRIM(value) AS topic, date(published_at) AS day
    FROM event_index, json_each('["' || REPLACE(topic_tags, ',', '","') || '"]')
    WHERE target_id = ? AND stage = 'judged'
      AND published_at >= date('now', ? || ' days')
      AND topic_tags IS NOT NULL AND topic_tags != ''
)
SELECT topic, day, COUNT(*) AS cnt
FROM split_topics
WHERE topic != ''
GROUP BY topic, day
ORDER BY day
```

返回 `list[dict]`，每条 `{topic: str, day: str, count: int}`。

> 注：SQLite 的 json_each 需要 JSON 格式输入。对于逗号分隔的 topic_tags，改用 Python 层拆分 + 按 day 聚合更可靠。

实际实现用两层查询：
1. 先查 `SELECT published_at, topic_tags FROM event_index WHERE ...` 获取原始行
2. Python 层拆分 topic_tags、按 (topic, day) 聚合计数

**`get_sentiment_daily_counts(target_id, days=14)`**

```sql
SELECT date(published_at) AS day, sentiment, COUNT(*) AS cnt
FROM event_index
WHERE target_id = ? AND stage = 'judged'
  AND published_at >= date('now', ? || ' days')
  AND sentiment IS NOT NULL
GROUP BY day, sentiment
ORDER BY day
```

**`get_top_topics(target_id, days=7, limit=10)`**

```sql
SELECT topic_tags, COUNT(*) AS total
FROM event_index
WHERE target_id = ? AND stage = 'judged'
  AND published_at >= date('now', ? || ' days')
  AND topic_tags IS NOT NULL AND topic_tags != ''
GROUP BY topic_tags
ORDER BY total DESC
LIMIT ?
```

> 注：此查询按原始 topic_tags 字符串分组。实际使用时需 Python 层拆分后按单个 topic 聚合。

### 3.2 趋势方向计算

在 `trend_analyzer.py` 中新增 `compute_topic_trends()` 函数：

- 取最近 7 天（current_period）vs 前 7 天（prev_period）的 topic 出现次数
- `trend_direction`：
  - current > prev × 1.2 → "rising"
  - current < prev × 0.8 → "falling"
  - 否则 → "stable"
- `hotness`：min(current_count / max_all_current_count × 100, 100)
- prev_count 为 0 时：current > 0 → "rising"，否则 "stable"

### 3.3 模型扩展

扩展现有 `TopicTrend` 和 `TrendReport`：

```python
class DailyCount(BaseModel):
    day: str
    count: int

class TopicTrend(BaseModel):  # 扩展
    topic: str
    hotness: int
    trend_direction: str
    event_count: int
    current_count: int = 0
    prev_count: int = 0
    daily_counts: list[DailyCount] = []

class TrendReport(BaseModel):  # 扩展
    target_id: str
    period_start: str
    period_end: str
    topics: list[TopicTrend] = []
    overall_sentiment: dict[str, int] = {}
    generated_at: str = ""
```

## 4. API 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/v1/trends/topics` | 主题热度趋势（时间序列） |
| GET | `/api/v1/trends/sentiment` | 情感分布趋势（时间序列） |

### 4.1 GET /trends/topics

参数：`target_id`（必须）、`days`（可选，默认 14，可选 7/14/30）

响应：
```json
{
  "target_id": "italy",
  "days": 14,
  "topics": [
    {
      "topic": "immigration",
      "trend_direction": "rising",
      "hotness": 85,
      "current_count": 12,
      "prev_count": 5,
      "event_count": 17,
      "daily_counts": [
        {"day": "2026-05-03", "count": 1},
        {"day": "2026-05-04", "count": 2}
      ]
    }
  ],
  "generated_at": "2026-05-16T15:00:00+00:00"
}
```

### 4.2 GET /trends/sentiment

参数：`target_id`（必须）、`days`（可选，默认 14）

响应：
```json
{
  "target_id": "italy",
  "days": 14,
  "daily_sentiment": [
    {"day": "2026-05-03", "positive": 3, "negative": 5, "neutral": 8}
  ],
  "generated_at": "2026-05-16T15:00:00+00:00"
}
```

## 5. 前端

### 5.1 Chart.js 引入

在 `index.html` 加 CDN script 标签（在 app.js 之前）：
```html
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
```

### 5.2 趋势页 (`#/trends`)

布局：
- **统计卡片行：** 追踪主题数 / 上升主题数 / 下降主题数 / 监控天数
- **天数切换：** 7天 / 14天 / 30天 三个按钮
- **主题热度折线图：** Chart.js 折线图，X 轴日期、Y 轴出现次数，每个 top-10 topic 一条线
- **主题排行表：** topic、trend_direction badge（↑上升/→稳定/↓下降）、hotness 进度条、当前数量
- **情感分布面积图：** Chart.js 堆叠面积图，三条线（positive/negative/neutral）

### 5.3 侧边栏

在"追踪链"和"运维中心"之间新增"趋势分析"入口，`data-page="trends"`。

## 6. 文件变更清单

| 文件 | 动作 | 职责 |
|------|------|------|
| `src/news_sentry/core/async_store.py` | 修改 | 3 个聚合查询方法 |
| `src/news_sentry/skills/analysis/trend_analyzer.py` | 修改 | compute_topic_trends() + 模型扩展 |
| `src/news_sentry/core/api_server.py` | 修改 | 2 个趋势端点 + Pydantic 模型 |
| `src/news_sentry/static/pages/trends.js` | 新建 | 趋势页（Chart.js 折线图 + 排行表） |
| `src/news_sentry/static/app.js` | 修改 | trends 路由 + import |
| `src/news_sentry/static/index.html` | 修改 | Chart.js CDN + 侧边栏入口 |
| `src/news_sentry/static/style.css` | 修改 | 趋势页样式 |
| `tests/unit/test_async_store.py` | 修改 | 聚合查询测试 |
| `tests/unit/test_trend_analyzer.py` | 修改 | compute_topic_trends 测试 |
| `tests/unit/test_api_server.py` | 修改 | 趋势端点测试 |

## 7. 测试计划

| 测试文件 | 测试内容 | 预计新增 |
|----------|----------|----------|
| `test_async_store.py` | 3 个聚合查询方法 | ~4 tests |
| `test_trend_analyzer.py` | compute_topic_trends + 趋势方向判定 | ~3 tests |
| `test_api_server.py` | 2 个趋势端点 | ~2 tests |

预计新增 ~9 tests，总测试数 ~1568。

## 8. 验收标准

1. 1559 后端测试零破坏
2. AsyncStore 3 个聚合查询方法正确返回按天分桶数据
3. `compute_topic_trends()` 正确计算 rising/stable/falling 方向
4. GET `/api/v1/trends/topics` 返回主题热度时间序列
5. GET `/api/v1/trends/sentiment` 返回情感分布时间序列
6. 趋势页 Chart.js 折线图正确渲染
7. 主题排行表显示趋势方向 badge + hotness 进度条
8. 天数切换（7/14/30）正常工作
9. 侧边栏"趋势分析"入口可见
10. ruff=0, mypy=0
