# Phase 38: 智能告警 2.0 + 性能修复 — 设计文档

> 日期: 2026-05-16
> 状态: 设计确认
> 前置: Phase 37 量化趋势分析完成 (1571 tests, 91% coverage)

## 1. 背景与目标

Phase 30-37 建立了 NLP 分析、实体追踪、事件链、AI 叙事、量化趋势分析能力。但这些数据对用户是"被动可见"——需要主动查看 Web UI。

当前 `AlertPipeline`（Phase 17/24）仅基于单个事件的 `news_value_score`、`china_relevance` 触发告警。链更新、趋势变化、实体突增等丰富信号完全未接入。

**目标：** 扩展告警系统，接入链更新/趋势变化/实体突增三类智能告警；同时修复 chains 页 N+1 性能问题和补齐缺失索引。

**非目标：** 预测分析、告警规则 UI 配置、跨 target 聚合告警。

## 2. 技术决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 告警触发 | Pipeline 自动（在 _generate_narratives 之后） | 复用 pipeline 流程，数据完备时触发 |
| 告警存储 | 内存列表 + API 实时查询 | 告警量有限，无需持久化表 |
| chains N+1 修复 | get_active_chains 嵌入 narrative_summary | 单次查询，前端零额外请求 |
| 索引策略 | 6 个新索引 | 覆盖常用查询路径，写入开销可忽略 |

## 3. 三类智能告警

### 3.1 链更新告警

**触发条件：** 最近 24 小时新增 `followup` link 且 `strength >= 0.7`

**数据查询：** `get_recent_links(target_id, hours=24)`

**告警格式：**
```
[链更新] "移民政策"追踪链新增后续事件: "意大利政府宣布新移民法案" (强度: 0.85)
```

### 3.2 趋势变化告警

**触发条件：** `compute_topic_trends()` 返回 `trend_direction == "rising"` 且 `hotness >= 60`

**数据查询：** 复用 `get_topic_daily_counts` + `get_top_topics` + `compute_topic_trends`

**告警格式：**
```
[趋势上升] "Elections" 主题热度快速上升 (热度: 85, 近7天: 12次, 前7天: 5次)
```

### 3.3 实体突增告警

**触发条件：** 实体今日提及量 > 7 天日均的 2 倍

**数据查询：** `get_entity_daily_mentions(entity_name, target_id, days=7)`

**告警格式：**
```
[实体突增] "Meloni" 实体提及量突增 (今日: 8次, 7天日均: 2.3次)
```

### 3.4 Pipeline 集成

```
collect → filter → judge → [link_events] → [generate_narratives] → [check_smart_alerts] → output
```

在 `_run_judge_async` 中 `_generate_narratives` 之后新增 `_check_smart_alerts()` 调用。`try/except` 包裹。

## 4. AsyncStore 变更

### 4.1 新增方法

**`get_recent_links(target_id, hours=24)`**
```sql
SELECT el.source_event_id, el.target_event_id, el.link_type, el.strength,
       ei.title_original
FROM event_links el
LEFT JOIN event_index ei ON ei.event_id = el.target_event_id
WHERE el.target_id = ? AND el.created_at >= datetime('now', ? || ' hours')
ORDER BY el.created_at DESC
```

**`get_entity_daily_mentions(entity_name, target_id, days=7)`**
```sql
SELECT date(published_at) AS day, COUNT(*) AS cnt
FROM event_index
WHERE target_id = ? AND stage = 'judged'
  AND published_at >= date('now', ? || ' days')
  AND ',' || entity_names || ',' LIKE '%,' || ? || ',%'
GROUP BY day ORDER BY day
```

### 4.2 get_active_chains 扩展

在 `get_active_chains()` 返回值中嵌入 `narrative_summary`（叙述前 50 字）和 `has_narrative` 布尔值。一次 JOIN 查询：

```sql
SELECT el.source_event_id AS root_id, COUNT(*) AS event_count,
       MAX(ei.published_at) AS latest_time,
       (SELECT ei2.title_original FROM event_index ei2 WHERE ei2.event_id = el.source_event_id) AS latest_title,
       cn.narrative AS narrative_summary,
       CASE WHEN cn.narrative IS NOT NULL THEN 1 ELSE 0 END AS has_narrative
FROM event_links el
JOIN event_index ei ON ...
LEFT JOIN chain_narratives cn ON cn.chain_root_id = el.source_event_id
...
```

### 4.3 新增 6 个索引

```sql
CREATE INDEX IF NOT EXISTS idx_event_classification ON event_index(classification_l0);
CREATE INDEX IF NOT EXISTS idx_event_source ON event_index(source_id);
CREATE INDEX IF NOT EXISTS idx_event_score ON event_index(news_value_score);
CREATE INDEX IF NOT EXISTS idx_narrative_target ON chain_narratives(target_id);
CREATE INDEX IF NOT EXISTS idx_event_links_type ON event_links(link_type, strength);
CREATE INDEX IF NOT EXISTS idx_event_created ON event_index(created_at);
```

## 5. API 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/v1/alerts/smart` | 获取最近智能告警列表 |

参数：`target_id`（必须）

响应：
```json
{
  "target_id": "italy",
  "alerts": [
    {
      "type": "chain_update",
      "severity": "high",
      "message": "\"移民政策\"追踪链新增后续事件",
      "details": {"chain_root_id": "evt-1", "strength": 0.85, "link_type": "followup"},
      "triggered_at": "2026-05-16T15:00:00+00:00"
    }
  ],
  "total": 1
}
```

## 6. 前端变更

### 6.1 chains.js 优化

移除 N+1 调用（当前对每个 chain 单独请求 narrative）。改用 `get_active_chains()` 返回的 `narrative_summary` 字段：

```javascript
// 替换 N+1 Promise.all 为直接使用嵌入字段
const narrativeMap = {};
data.chains.forEach(c => {
  if (c.narrative_summary) {
    narrativeMap[c.root_event_id] = c.narrative_summary.substring(0, 50) + "...";
  }
});
```

### 6.2 ops.js 增强

在运行详情页新增"智能告警"卡片，调用 `/api/v1/alerts/smart` 显示本次触发的告警。

## 7. 文件变更清单

| 文件 | 动作 | 职责 |
|------|------|------|
| `src/news_sentry/core/async_store.py` | 修改 | 2 个新方法 + 6 个索引 + get_active_chains 扩展 |
| `src/news_sentry/core/alert_pipeline.py` | 修改 | check_smart_alerts() |
| `src/news_sentry/core/async_run.py` | 修改 | 集成 _check_smart_alerts |
| `src/news_sentry/core/api_server.py` | 修改 | 1 个告警端点 + Pydantic 模型 |
| `src/news_sentry/static/pages/chains.js` | 修改 | 移除 N+1 调用 |
| `src/news_sentry/static/pages/ops.js` | 修改 | 智能告警卡片 |
| `tests/unit/test_async_store.py` | 修改 | 2 个新方法测试 + 索引验证 |
| `tests/unit/test_alert_pipeline.py` | 修改 | 智能告警测试 |
| `tests/unit/test_api_server.py` | 修改 | 告警端点测试 |

## 8. 测试计划

| 测试文件 | 测试内容 | 预计新增 |
|----------|----------|----------|
| `test_async_store.py` | 2 个新方法 + 索引验证 | ~3 tests |
| `test_alert_pipeline.py` | 3 类智能告警触发逻辑 | ~4 tests |
| `test_api_server.py` | 告警端点 | ~2 tests |

预计新增 ~9 tests，总测试数 ~1580。

## 9. 验收标准

1. 1571 后端测试零破坏
2. 6 个新索引正确创建
3. `get_recent_links()` 正确返回近期新增 links
4. `get_entity_daily_mentions()` 正确返回实体每日提及量
5. 链更新告警（followup + strength >= 0.7）正确触发
6. 趋势变化告警（rising + hotness >= 60）正确触发
7. 实体突增告警（日提及 > 2x 7 天日均）正确触发
8. GET `/api/v1/alerts/smart` 返回告警列表
9. `/api/v1/chains` 响应嵌入 narrative_summary，前端无 N+1
10. 智能告警失败不阻塞 pipeline
11. ruff=0, mypy=0
