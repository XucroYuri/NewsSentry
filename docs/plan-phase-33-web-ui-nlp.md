# Phase 33: Web UI NLP + Entity 可视化集成 — 设计文档

> 日期: 2026-05-16
> 状态: 设计确认
> 前置: Phase 32 Entity Tracking 完成 (1527 tests, 92% coverage)

## 1. 背景与目标

Phase 30-32 建立了 NLP 深度分析、API 过滤和 Entity Tracking 能力，但 Web UI 完全未利用这些数据：
- `sentiment_breakdown` 和 `top_entities` — API 已返回，Dashboard 未展示
- `sentiment`/`entity`/`topic_tag` 筛选 — API 已支持，事件筛选栏未接入
- `GET /entities` + `GET /entities/{id}` — 完全没有 UI 页面
- 事件 frontmatter 中的 NLP 字段 — 事件卡片和详情页未展示

**目标：** 将 Phase 30-32 的 NLP/Entity 数据接入 Web UI，让用户可通过浏览器直接消费。

**非目标：** Run History API、Source Health API、引入前端框架/图表库、前端自动化测试。

## 2. 技术决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 前端架构 | ES Modules 拆分 | 浏览器原生支持，无构建工具，每个页面独立文件 |
| 图表方案 | 纯 CSS 条形图（沿用现有） | 不引入新依赖，与现有 Dashboard 风格一致 |
| Entity 展示 | chips 而非表格 | 紧凑、与列表页一致，relevance 用 tooltip |
| 文件组织 | pages/ 子目录 | 页面文件与入口分离，新增页面只需加文件+注册路由 |

## 3. ES Modules 拆分

### 3.1 文件结构

```
static/
  index.html              — script 改为 type="module"
  app.js                  — 入口：路由 + 状态 + 页面注册 (~150 行)
  api.js                  — 导出: api(), escapeHtml(), state, scoreBar() 等工具
  pages/
    dashboard.js          — renderDashboard() 导出
    events.js             — renderEventList() + renderEventDetail() 导出
    entities.js           — renderEntityList() + renderEntityDetail() 导出 (P33.03)
    config.js             — 5 个配置页渲染函数
  style.css               — 不动（P33.02 增加新样式）
```

### 3.2 拆分规则

- `state` 对象、`dom` 引用放在 `api.js`，所有页面共享
- `api()`、`escapeHtml()`、`scoreBar()`、`scoreColor()`、`scoreGradient()`、`showError()` 放在 `api.js` 导出
- 每个页面文件导出 `render*` 函数，由 `app.js` 路由调用
- `index.html` 中 `<script src="app.js">` 改为 `<script type="module" src="app.js">`

### 3.3 验证

拆分前后对比所有 8 个页面的 DOM 快照，确认完全一致。

## 4. Dashboard 增强

### 4.1 sentiment_breakdown 条形图

在 Classification 和 Source 分布图下方新增 sentiment 分布图。复用现有纯 CSS 条形图模式：
- positive（绿色 #22c55e）/ negative（红色 #ef4444）/ neutral（灰色 #6b7280）/ none（暗灰色 #374151）
- 数据来自 `stats.sentiment_breakdown`

### 4.2 top_entities 列表

Dashboard 底部新增"高频实体"卡片：
- 显示 entity name + type tag + mention_count
- 点击跳转 `#/entities/{id}`
- 数据来自 `stats.top_entities`

## 5. 事件列表/详情 NLP 增强

### 5.1 筛选栏新增 3 个控件

- Sentiment 下拉：全部 / positive / negative / neutral
- Entity 搜索框：文本输入
- Topic tag 搜索框：文本输入

### 5.2 事件卡片增强

- Sentiment 色标点（绿/红/灰色圆点，标题左侧）
- Entity chips（实体名小标签，最多 3 个，卡片底部）

### 5.3 事件详情增强

Score cards 下方新增 NLP Analysis 区域：
- Sentiment 标签（带色标）
- Entity chips（name + type，点击跳转 `#/entities/{id}`，relevance 用 tooltip）
- Topic tag chips
- Event relations 文本列表（如有）

## 6. Entity 浏览页

### 6.1 侧边栏

Events 和 Config 之间新增"实体"入口。

### 6.2 Entity 列表（`#/entities`）

**筛选控件：**
- Entity type 下拉：全部 / person / organization / location / event
- 最少提及次数数字输入框
- Target 下拉（复用现有）

**卡片列表：**
- canonical_name（大字）、entity_type tag、mention_count
- first_seen / last_seen 时间、target_ids chips
- 按 mention_count DESC 排序，分页

**API：** `GET /api/v1/entities?entity_type=...&min_mentions=...&limit=20`

### 6.3 Entity 详情（`#/entities/{id}`）

- 头部：canonical_name、entity_type、mention_count、时间范围
- 关联事件列表：最近 10 条（卡片精简版）

**API：** `GET /api/v1/entities/{id}`

## 7. 文件变更清单

| 文件 | 动作 | 职责 |
|------|------|------|
| `src/news_sentry/static/index.html` | 修改 | script 改为 type="module" |
| `src/news_sentry/static/app.js` | 重写 | 入口+路由 |
| `src/news_sentry/static/api.js` | 新建 | api helper + 工具函数 |
| `src/news_sentry/static/pages/dashboard.js` | 新建 | Dashboard（含增强） |
| `src/news_sentry/static/pages/events.js` | 新建 | 事件列表+详情（含 NLP） |
| `src/news_sentry/static/pages/entities.js` | 新建 | Entity 浏览页 |
| `src/news_sentry/static/pages/config.js` | 新建 | 5 个配置页 |
| `src/news_sentry/static/style.css` | 修改 | NLP/entity 新样式 |

## 8. 验收标准

1. 1527 后端测试零破坏
2. 拆分前后所有 8 个现有页面 DOM 完全一致
3. Dashboard 展示 sentiment_breakdown 条形图 + top_entities 列表
4. 事件列表支持 sentiment/entity/topic_tag 筛选
5. 事件卡片显示 sentiment 色标 + entity chips
6. 事件详情显示完整 NLP 区域（sentiment + entity chips + topic chips + relations）
7. `#/entities` 列表页正常（筛选 + 分页）
8. `#/entities/{id}` 详情页正常（关联事件）
9. ruff=0, mypy=0
