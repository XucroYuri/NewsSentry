# Phase 35: 事件追踪链 + 时间线关联 — 设计文档

> 日期: 2026-05-16
> 状态: 设计确认
> 前置: Phase 34 运维仪表盘完成 (1535 tests, 92% coverage)

## 1. 背景与目标

Phase 30-34 建立了 NLP 分析、Entity Tracking、Web UI 可视化、运维仪表盘能力。但系统只能分析单个事件，无法串联事件发展脉络。

**目标：** 基于现有实体/主题/时间信号，自动发现事件间关联关系，构建事件追踪链，在 Web UI 中以时间线方式展示事件演变。

**非目标：** AI 驱动关联（留未来增强）、跨 target 关联、知识图谱。

## 2. 技术决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 关联算法 | 纯规则本地计算 | 零外部依赖，复用 NLP 信号，YAGNI |
| 存储位置 | SQLite event_links 表 | 与 AsyncStore 一致，查询高效 |
| 关联触发 | pipeline judge 后 | 事件已有 NLP 标注，信号充分 |
| link_type 枚举 | followup/related/same_event/correction | 覆盖主要关联场景 |
| 前端展示 | 垂直时间线 | 直观展示事件演变 |

## 3. 数据模型

### 3.1 event_links 表

```sql
CREATE TABLE IF NOT EXISTS event_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_event_id TEXT NOT NULL,
    target_event_id TEXT NOT NULL,
    link_type TEXT NOT NULL,
    strength REAL NOT NULL DEFAULT 0.5,
    signals TEXT NOT NULL DEFAULT '{}',
    target_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_event_id, target_event_id, link_type)
);
```

### 3.2 link_type 语义

- `followup` — 后续进展（同一事件的时间线延续）
- `related` — 相关事件（实体/主题交叉但非同一事件）
- `same_event` — 不同信源报道同一事件
- `correction` — 纠正/反转

### 3.3 关联算法

**候选池：** 同一 target 下最近 7 天的所有事件。

**3 个匹配信号（加权）：**

| 信号 | 权重 | 计算方式 |
|------|------|----------|
| 实体重叠 | 0.4 | 共同实体数 / max(事件A实体数, 事件B实体数) |
| 主题匹配 | 0.3 | topic_tags 集合 Jaccard 相似度 |
| 时间接近 | 0.3 | 1.0 - min(时间差/7天, 1.0) |

**关联决策：**
- `strength >= 0.7` + 实体重叠 >= 2 → 自动创建 link
- `0.4 <= strength < 0.7` → 创建 link 但标记为低置信度
- `strength < 0.4` → 不关联

## 4. Pipeline 集成

### 4.1 集成点

```
collect → filter → judge → [link_events] → output
```

### 4.2 执行逻辑

1. 从 AsyncStore 查询本次新入库的事件列表（judge 通过的事件）
2. 对每个新事件调用 `find_candidates()` 获取候选池
3. 计算 strength，满足阈值的写入 `event_links`
4. `try/except` 包裹 — 关联失败不阻塞 pipeline

### 4.3 新增 AsyncStore 方法

- `find_candidates(target_id, event_id, days=7)` — 查找候选关联事件
- `create_link(source_id, target_id, link_type, strength, signals, target_id)` — 写入关联
- `get_event_chain(event_id, depth=5)` — 向前向后遍历关联链
- `get_event_links(event_id)` — 获取某事件的所有直接关联

## 5. API 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/v1/events/{event_id}/links` | 获取某事件的关联事件列表 |
| GET | `/api/v1/events/{event_id}/chain` | 获取某事件的完整追踪链 |
| GET | `/api/v1/chains` | 列出当前 target 的活跃追踪链 |

### 5.1 /links 响应结构

```json
{
  "event_id": "abc123",
  "links": [
    {
      "linked_event_id": "def456",
      "link_type": "followup",
      "strength": 0.82,
      "direction": "backward",
      "signals": {"entity_overlap": 0.75, "topic_match": 0.6, "time_proximity": 0.9},
      "linked_event_title": "...",
      "linked_event_time": "2026-05-16T10:00:00Z"
    }
  ]
}
```

### 5.2 /chain 响应结构

```json
{
  "chain_id": "abc123",
  "events": [
    {"event_id": "aaa", "time": "...", "title": "...", "link_type": null},
    {"event_id": "abc123", "time": "...", "title": "...", "link_type": "followup"},
    {"event_id": "xyz", "time": "...", "title": "...", "link_type": "followup"}
  ],
  "total": 3
}
```

### 5.3 /chains 响应结构

```json
{
  "chains": [
    {"root_event_id": "aaa", "event_count": 5, "latest_time": "...", "latest_title": "..."},
    {"root_event_id": "bbb", "event_count": 3, "latest_time": "...", "latest_title": "..."}
  ]
}
```

## 6. 前端页面

### 6.1 追踪链列表页 (`#/chains`)

- 统计卡片：活跃链数 / 最大链长度 / 今日新增链数
- 追踪链列表：链根事件标题、事件数、最新事件时间、最新事件标题
- 点击进入链详情

### 6.2 链详情页 (`#/chains/{root_event_id}`)

- 垂直时间线：事件按时间排列
- 每个节点：标题、时间、关联类型 badge、关联强度条
- 关联类型颜色：followup(蓝)、related(灰)、same_event(绿)、correction(红)
- 点击事件节点跳转事件详情页

### 6.3 事件详情页增强

- NLP 分析区域下方新增"关联事件"卡片
- 显示前序事件和后续事件，带 link_type badge 和 strength 指示

### 6.4 侧边栏

"事件列表"和"实体追踪"之间新增"追踪链"入口，`data-page="chains"`。

## 7. 文件变更清单

| 文件 | 动作 | 职责 |
|------|------|------|
| `src/news_sentry/core/async_store.py` | 修改 | event_links 表 + 4 个新方法 |
| `src/news_sentry/core/async_run.py` | 修改 | link_events() 协程集成 |
| `src/news_sentry/core/api_server.py` | 修改 | 3 个新端点 |
| `src/news_sentry/static/pages/chains.js` | 新建 | 追踪链列表 + 链详情页 |
| `src/news_sentry/static/pages/events.js` | 修改 | 事件详情新增关联事件卡片 |
| `src/news_sentry/static/app.js` | 修改 | #/chains 路由 + import |
| `src/news_sentry/static/index.html` | 修改 | 侧边栏"追踪链"入口 |
| `src/news_sentry/static/style.css` | 修改 | 时间线样式 |
| `tests/unit/test_async_store.py` | 修改 | 表创建 + 4 个方法测试 |
| `tests/unit/test_api_server.py` | 修改 | 3 个端点测试 |
| `tests/unit/test_async_run.py` | 修改 | link_events 集成测试 |

## 8. 测试计划

| 测试文件 | 测试内容 | 预计新增 |
|----------|----------|----------|
| `test_async_store.py` | 表创建 + 4 个新方法 | ~8 tests |
| `test_api_server.py` | 3 个新端点 | ~5 tests |
| `test_async_run.py` | link_events 协程集成 | ~3 tests |

预计新增 ~16 tests，总测试数 ~1551。

## 9. 验收标准

1. 1535 后端测试零破坏
2. `event_links` 表正确创建（UNIQUE 约束生效）
3. 关联算法能基于实体+主题+时间信号产生关联
4. pipeline 集成后自动对新事件执行关联扫描
5. 关联失败不阻塞 pipeline
6. `GET /api/v1/events/{id}/links` 返回关联事件
7. `GET /api/v1/events/{id}/chain` 返回完整追踪链
8. `GET /api/v1/chains` 返回活跃链列表
9. `#/chains` 追踪链列表页正常展示
10. `#/chains/{id}` 时间线视图正常展示
11. 事件详情页显示关联事件卡片
12. ruff=0, mypy=0
