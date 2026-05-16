# Phase 39: Dashboard 增强 — 设计文档

> 日期: 2026-05-16
> 状态: 设计确认
> 前置: Phase 38 智能告警 2.0 完成 (1580 tests, 91% coverage)

## 1. 背景与目标

Dashboard 当前仅展示全时间聚合统计（总事件数、平均分、分类分布等），缺乏时间维度。用户无法快速了解"今天发生了什么""趋势如何"。

**目标：** 为 Dashboard 增加今日/昨日对比统计、近期高价值事件 Top5、趋势概览。

**非目标：** 跨 target 对比、自定义时间范围、实时自动刷新。

## 2. 技术决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 对比维度 | 今日 vs 昨日 | 最直观，与 pipeline 每日运行对齐 |
| Top5 展示 | 最近 7 天 | 一周窗口，数据充分 |
| 趋势概览 | 复用 /trends/topics API | 避免重复实现，前端直接调用 |

## 3. AsyncStore 新增方法

### 3.1 get_today_stats(target_id)

```sql
-- 今日
SELECT COUNT(*), AVG(news_value_score), MAX(news_value_score)
FROM event_index WHERE target_id = ? AND stage = 'judged'
  AND date(published_at) = date('now')

-- 昨日
SELECT COUNT(*), AVG(news_value_score)
FROM event_index WHERE target_id = ? AND stage = 'judged'
  AND date(published_at) = date('now', '-1 day')
```

返回：
```python
{
    "today_count": 12,
    "today_avg_score": 78.5,
    "today_max_score": 95,
    "yesterday_count": 9,
    "yesterday_avg_score": 73.2,
}
```

### 3.2 get_top_events(target_id, days=7, limit=5)

```sql
SELECT event_id, title_original, news_value_score, source_id, published_at
FROM event_index
WHERE target_id = ? AND stage = 'judged'
  AND published_at >= date('now', ? || ' days')
ORDER BY news_value_score DESC
LIMIT ?
```

## 4. API 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/v1/stats/today` | 今日 vs 昨日对比 |
| GET | `/api/v1/events/top` | 近期高价值事件 |

### 4.1 GET /stats/today

参数：`target_id`（必须）

```json
{
  "target_id": "italy",
  "today_count": 12,
  "today_avg_score": 78.5,
  "today_max_score": 95,
  "yesterday_count": 9,
  "yesterday_avg_score": 73.2
}
```

### 4.2 GET /events/top

参数：`target_id`（必须）、`days`（可选，默认 7）、`limit`（可选，默认 5）

```json
{
  "target_id": "italy",
  "events": [
    {"event_id": "ne-1", "title": "...", "news_value_score": 95, "source_id": "ansa", "published_at": "..."}
  ]
}
```

## 5. 前端 — Dashboard 增强

### 5.1 顶部对比卡片行

在现有 stats-grid 之前新增一行：

| 今日事件 | 今日均分 | 今日高分 | 趋势主题 |
|----------|----------|----------|----------|
| 12 (↑3) | 78 (↑5) | 95 | 3 rising |

涨跌用颜色区分（绿色↑、红色↓），无昨日数据时显示"-"。

### 5.2 近期高价值事件卡片

stats-grid 之后新增"近期高价值事件"section-card：

| 标题 | 分数 | 来源 | 时间 |
|------|------|------|------|
| 意大利总理签署移民法案 | 95 | ANSA | 2小时前 |

点击行跳转 `#/events/{event_id}`。

### 5.3 趋势概览

在对比卡片最后一格显示 rising 的 top-3 主题 badge（调用已有 `/api/v1/trends/topics`）。

## 6. 文件变更清单

| 文件 | 动作 | 职责 |
|------|------|------|
| `src/news_sentry/core/async_store.py` | 修改 | 2 个新方法 |
| `src/news_sentry/core/api_server.py` | 修改 | 2 个端点 + Pydantic 模型 |
| `src/news_sentry/static/pages/dashboard.js` | 修改 | 对比卡片 + Top5 + 趋势概览 |
| `tests/unit/test_async_store.py` | 修改 | 2 个方法测试 |
| `tests/unit/test_api_server.py` | 修改 | 2 个端点测试 |

## 7. 测试计划

| 测试文件 | 测试内容 | 预计新增 |
|----------|----------|----------|
| `test_async_store.py` | get_today_stats + get_top_events | ~2 tests |
| `test_api_server.py` | 2 个端点 | ~2 tests |

预计新增 ~4 tests。

## 8. 验收标准

1. 1580 后端测试零破坏
2. get_today_stats() 正确返回今日/昨日对比
3. get_top_events() 正确返回按分数降序
4. GET /api/v1/stats/today 正常工作
5. GET /api/v1/events/top 正常工作
6. Dashboard 显示今日对比卡片（含涨跌指示）
7. Dashboard 显示近期高价值事件 Top5
8. Dashboard 显示趋势概览（rising 主题 badge）
9. ruff=0, mypy=0
