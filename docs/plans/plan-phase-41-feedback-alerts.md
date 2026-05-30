# Phase 41: Web UI 反馈闭环 + 告警管理 — 设计文档

> 日期: 2026-05-16
> 状态: 设计确认
> 前置: Phase 40 治理积压清理完成 (1592 tests, 91% coverage)

## 1. 背景与目标

Phase 20 实现了 FeedbackCollector + RulesOptimizer（人工反馈→规则自优化），但无 API 暴露、无 Web UI 入口。Phase 38 实现了智能告警但仅嵌入运维详情页，无独立管理页。反馈闭环是 ADR-0010 "Iron Man 套装"理念的核心——"增强人工研判"需要人在界面上方便介入。

**目标：** 实现 Web UI 反馈闭环（事件详情提交反馈→规则优化）+ 独立告警管理页面。

**非目标：** 告警阈值配置 UI、反馈导出、告警通知渠道管理。

## 2. 技术决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 反馈存储 | SQLite feedback 表 | 与 AsyncStore 统一，查询方便 |
| 告警历史 | SQLite alert_history 表 | 持久化告警记录，支持历史查看 |
| 规则优化触发 | API 手动 + dry_run 预览 | 安全，先看调整再确认 |
| 前端页面 | 2 新页面 + 1 修改 | alerts.js + feedback.js + events.js 反馈按钮 |

## 3. 数据层

### 3.1 feedback 表

```sql
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    verdict_type TEXT NOT NULL,
    original_recommendation TEXT,
    comment TEXT,
    keywords_matched TEXT,
    source_id TEXT,
    created_at TEXT DEFAULT (datetime('now'))
)
```

### 3.2 alert_history 表

```sql
CREATE TABLE IF NOT EXISTS alert_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    details TEXT,
    created_at TEXT DEFAULT (datetime('now'))
)
```

### 3.3 AsyncStore 新增方法

- `save_feedback(target_id, event_id, verdict_type, comment, ...)` — 插入反馈
- `get_feedback(target_id, limit=50)` — 获取反馈列表
- `get_feedback_stats(target_id)` — 聚合统计
- `save_alert_history(target_id, alerts)` — 批量写入告警
- `get_alert_history(target_id, limit=50)` — 获取历史告警

## 4. API 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/api/v1/feedback` | 提交人工反馈 |
| GET | `/api/v1/feedback?target_id=X` | 获取反馈列表 |
| GET | `/api/v1/feedback/stats?target_id=X` | 反馈统计 |
| POST | `/api/v1/rules/optimize` | 触发规则优化 |
| GET | `/api/v1/alerts/history?target_id=X` | 告警历史 |

### 4.1 POST /feedback

```json
{"target_id": "italy", "event_id": "ne-123", "verdict_type": "publish_override", "comment": "应推送"}
```

返回：`{"id": 1, "event_id": "ne-123", "verdict_type": "publish_override"}`

### 4.2 GET /feedback?target_id=X

返回：`{"feedback": [...], "total": 42}`

### 4.3 GET /feedback/stats?target_id=X

返回：`{"total": 42, "publish_override": 15, "archive_override": 20, "comment": 7}`

### 4.4 POST /rules/optimize

参数：`target_id`（必须）、`dry_run`（可选，默认 true）

返回：`{"total_verdicts": 10, "adjustments": 3, "adjustments_detail": [...], "written": false}`

### 4.5 GET /alerts/history?target_id=X

返回：`{"alerts": [...], "total": 25}`

## 5. 前端

### 5.1 告警管理页 #/alerts（alerts.js）

- 当前活跃告警：调用 GET /alerts/smart，severity 颜色卡片
- 历史告警表格：调用 GET /alerts/history，时间倒序
- 统计卡片：今日/本周告警数

### 5.2 反馈管理页 #/feedback（feedback.js）

- 统计卡片：总反馈 / 发布覆盖 / 归档覆盖 / 评论
- 反馈列表表格（事件 ID + 判定类型 + 评论 + 时间）
- 「规则优化」按钮 → POST /rules/optimize（dry_run=true 预览 → 确认后 dry_run=false）

### 5.3 事件详情页反馈按钮（events.js 修改）

- 底部反馈操作区：推荐发布 / 归档 两个按钮 + 评论输入
- 调用 POST /feedback，toast 提示成功
- 已反馈事件显示判定标签

## 6. 文件变更清单

| 文件 | 动作 | 职责 |
|------|------|------|
| `src/news_sentry/core/async_store.py` | 修改 | feedback + alert_history 表 + 5 方法 |
| `src/news_sentry/core/alert_pipeline.py` | 修改 | check_smart_alerts 写入 alert_history |
| `src/news_sentry/core/api_server.py` | 修改 | 5 个新端点 + Pydantic 模型 |
| `src/news_sentry/static/pages/alerts.js` | 新建 | 告警管理页 |
| `src/news_sentry/static/pages/feedback.js` | 新建 | 反馈管理页 |
| `src/news_sentry/static/pages/events.js` | 修改 | 事件详情反馈按钮 |
| `src/news_sentry/static/app.js` | 修改 | 新增路由 |
| `src/news_sentry/static/index.html` | 修改 | 侧边栏新增项 |
| `src/news_sentry/static/style.css` | 修改 | 新页面样式 |
| `tests/unit/test_async_store.py` | 修改 | feedback + alert history 测试 |
| `tests/unit/test_api_server.py` | 修改 | 5 端点测试 |

## 7. 测试计划

| 测试文件 | 测试内容 | 预计新增 |
|----------|----------|----------|
| `test_async_store.py` | save/get feedback + stats + alert history | ~3 tests |
| `test_api_server.py` | 5 个新端点 | ~5 tests |

预计新增 ~8 tests。

## 8. 验收标准

1. 1592 后端测试零破坏
2. save_feedback() 正确写入 feedback 表
3. get_feedback_stats() 正确聚合统计
4. alert_history 正确持久化告警记录
5. POST /api/v1/feedback 正常工作
6. GET /api/v1/feedback/stats 正常工作
7. POST /api/v1/rules/optimize 正常工作（dry_run + apply）
8. GET /api/v1/alerts/history 正常工作
9. 告警管理页显示活跃告警 + 历史告警
10. 反馈管理页显示统计 + 反馈列表 + 触发优化
11. 事件详情页可提交反馈
12. ruff=0, mypy=0
