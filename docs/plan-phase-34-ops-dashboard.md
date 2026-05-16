# Phase 34: 运维仪表盘 + Pipeline 控制 — 设计文档

> 日期: 2026-05-16
> 状态: 设计确认
> 前置: Phase 33 Web UI NLP 完成 (1527 tests, 92% coverage)

## 1. 背景与目标

Phase 25-33 建立了异步 pipeline、SQLite 存储、NLP 分析、Entity Tracking 和 Web UI 可视化能力。但运维数据完全沉睡在文件系统：

- **RunLog** — 每次 run 产出结构化 JSON 审计日志，但无 API 暴露
- **AICostTracker** — 纯内存，run 结束数据即丢失
- **MetricsWriter** — 代码存在但未被 pipeline 调用
- **SourceHealthChecker** — 检查结果未批量持久化/暴露
- **Pipeline 触发** — 只能 CLI，Web UI 纯只读

**目标：** 将运维数据通过 API 暴露并在 Web UI 中可视化，支持从 UI 手动触发采集。

**非目标：** Prometheus 集成、告警历史查询、MetricsWriter 接入（留 Phase 35）、人工审核闭环。

## 2. 技术决策

| 决策 | 选择 | 理由 |
|------|------|------|
| RunLog 读取 | 直接读 JSON 文件 | 已有结构化数据，无需迁入 SQLite |
| AI 成本持久化 | 写入 RunLog JSON 的 summary 字段 | 最小改动，RunLog 已包含成本数据 |
| 信源健康批量查询 | AsyncStore 新增方法 | source_health 表已有，只需加批量查询 |
| Pipeline 触发 | asyncio.create_task | 不阻塞 API 请求，后台执行 |
| 前端页面 | 新增 pages/ops.js | 沿用 ES Modules 架构 |

## 3. 后端 API

### 3.1 新增端点

| 方法 | 路径 | 认证 | 用途 |
|------|------|:----:|------|
| GET | `/api/v1/runs` | 无 | 运行历史列表（需 `?target_id=`） |
| GET | `/api/v1/runs/{run_id}` | 无 | 单次运行详情 |
| GET | `/api/v1/runs/active` | 无 | 当前活跃运行心跳状态 |
| GET | `/api/v1/sources/health` | 无 | 信源健康批量状态（需 `?target_id=`） |
| POST | `/api/v1/runs/trigger` | 需认证 | 手动触发采集 |

### 3.2 数据层新增

- `AsyncStore.get_all_source_health()` → `list[dict]` — 批量返回所有信源健康记录

### 3.3 RunLog JSON 结构（已存在，参考）

```json
{
  "run_id": "italy_20260516T120000Z_a1b2c3d4",
  "started_at": "2026-05-16T12:00:00+00:00",
  "ended_at": "2026-05-16T12:01:30+00:00",
  "target_id": "italy",
  "phases": [
    { "stage": "collect", "duration_ms": 5000, "items_count": 42, "errors_count": 0 }
  ],
  "errors_count": 0,
  "summary": { "total_events_collected": 42 }
}
```

### 3.4 心跳文件结构（已存在）

```json
{
  "run_id": "...",
  "last_stage": "collect",
  "last_at": "2026-05-16T12:00:30+00:00",
  "status": "running"
}
```

## 4. 前端运维页面

### 4.1 运维总览页 (`#/ops`)

- **运行历史列表**（最近 20 次）：run_id（截断显示）、target、开始时间、耗时、事件数、错误数
- **当前活跃运行**：心跳数据显示 running 状态 + 当前 stage
- **信源健康看板**：healthy/degraded/unreachable 三色统计
- **快速操作**：触发采集按钮（选 target + stage 下拉）、配置重载按钮

### 4.2 运行详情页 (`#/ops/{run_id}`)

- 运行基本信息（target、时间、耗时）
- 各阶段执行详情（collect/filter/judge/output：耗时、事件数、错误）
- 错误列表（如有）

### 4.3 侧边栏

在"实体追踪"和分割线之间新增"运维中心"入口。

## 5. 文件变更清单

| 文件 | 动作 | 职责 |
|------|------|------|
| `src/news_sentry/core/async_store.py` | 修改 | 新增 get_all_source_health() |
| `src/news_sentry/core/api_server.py` | 修改 | 5 个新端点 |
| `src/news_sentry/static/pages/ops.js` | 新建 | 运维页面渲染 |
| `src/news_sentry/static/app.js` | 修改 | 路由 + import |
| `src/news_sentry/static/index.html` | 修改 | 侧边栏入口 |
| `src/news_sentry/static/style.css` | 修改 | 运维页样式 |
| `tests/unit/test_async_store.py` | 修改 | 批量健康查询测试 |
| `tests/unit/test_api_server.py` | 修改 | 运维 API 测试 |

## 6. 验收标准

1. 1527 后端测试零破坏
2. `GET /api/v1/runs` 返回运行历史列表
3. `GET /api/v1/runs/{run_id}` 返回单次运行详情
4. `GET /api/v1/runs/active` 返回心跳状态
5. `GET /api/v1/sources/health` 返回信源健康批量数据
6. `POST /api/v1/runs/trigger` 能异步触发 pipeline
7. `#/ops` 运维总览页正常展示运行历史 + 信源健康 + 操作按钮
8. `#/ops/{run_id}` 运行详情页正常展示阶段详情
9. ruff=0, mypy=0
