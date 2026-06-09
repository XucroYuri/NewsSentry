# 公共新闻产品体验设计

> 日期：2026-06-09  
> 状态：下一阶段产品规格  
> 关联：ADR-0027、`docs/roadmap/public-news-productization-20260609.md`

## 1. 定位

News Sentry 公共门户下一阶段不再是“公开的采集监控台”，而是一个面向读者的新闻情报产品。

一句话目标：

> 让读者打开站点后，立刻看到值得读的新闻、可靠来源、摘要、推荐理由和后续追踪入口。

公共门户的核心任务是消费新闻，不是解释系统如何采集新闻。

## 2. 当前问题

### 2.1 信息组织偏后台

首屏大量使用事件总数、信源总数、目标状态、增强队列、采集健康等宏观指标。这些信息对管理员有价值，但对普通读者不是第一行动。

### 2.2 布局不是真正响应式

当前桌面页面虽然居中，但有效阅读区域偏窄。1440px 宽屏没有形成全宽内容台，仍像移动单列放大版。

### 2.3 新闻闭环不足

读者看到标题和评分后，仍缺少完整判断链：

- 新闻来自哪里。
- 原文能不能打开。
- 摘要是否足够说明发生了什么。
- 为什么值得关注。
- 与哪些事件、来源或讨论有关。
- 下一步应该读详情、看原文，还是追踪话题。

### 2.4 工程参数外露

`stage`、`target_id`、裸 `score`、增强状态等工程字段在公共侧过于显眼。公共门户应把这些字段翻译成读者语言，例如“精选”“值得关注”“来源可靠”“样本不足”。

### 2.5 自主前端代码维护压力过高

Vanilla JS + 手写 CSS 已经覆盖路由、组件、状态、响应式、样式 token、浏览器 QA。继续叠加会提高维护成本，且难以形成统一组件体系。

## 3. AIHOT 可学习点

参考站点：`https://aihot.virxact.com/`

学习的是信息组织，不复制视觉皮肤：

- 首页直接是内容流。
- 左侧是稳定导航，主区域是时间线新闻。
- 顶部有精选、全部、日报、Agent 接入等明确频道。
- 每条内容包含来源、时间、标题原文链接、摘要、标签和推荐理由。
- “精选分数”存在，但不是唯一主角。
- 关联讨论作为内容可信度和热度补充。
- 移动端保持同一内容流，不把读者先带到仪表盘。

News Sentry 应迁移为类似的“新闻消费流”，但保留自己的目标监控、跨语种、来源矩阵和中国相关度特色。

## 4. 信息架构

### 4.1 顶层导航

公共门户顶层导航调整为：

- `精选`：默认入口，高价值新闻流。
- `全部`：按时间展示所有公开新闻。
- `目标`：按国家/专题 target 浏览。
- `来源`：按媒体、RSS、官方站点、社媒来源浏览。
- `态势`：趋势、实体、来源分布和追踪链。
- `日报`：按天生成的编辑摘要。

管理后台入口保留，但不参与公共信息架构。

### 4.2 页面层级

| 页面 | 目标 | 首屏内容 |
|---|---|---|
| 首页 / 精选 | 直接消费高价值新闻 | 精选新闻流 + 频道筛选 |
| 全部 | 完整时间线 | 日期分组新闻流 |
| Target | 查看某个监控目标 | 目标新闻流，不先展示仪表盘 |
| 来源 | 判断来源质量与最近报道 | 来源列表 + 最近文章 |
| 文章详情 | 完整阅读闭环 | 标题、摘要、原文、来源、理由、相关事件 |
| 态势 | 阅读后的分析层 | 趋势、实体、来源分布、故事线 |
| 日报 | 每日摘要 | 当天重点、主题、风险、链接 |

## 5. 新闻卡片规格

公共新闻卡片必须以读者语言展示：

- 时间：`HH:mm` 或日期分组下的发布时间。
- 来源：来源显示名、来源类型、可信度提示。
- 标题：中文展示标题，点击进入详情。
- 原文标题：可折叠或在详情页展示。
- 摘要：1-3 行，优先使用翻译/增强后的短摘要。
- 推荐理由：解释为什么进入精选或为什么值得关注。
- 标签：主题、分类、实体、国家/组织。
- 关联：相关事件数、来源交叉数、讨论数。
- 操作：查看原文、查看详情、复制摘要、追踪主题。

不直接把 `pipeline_stage`、`target_id`、裸 `score` 放在主视觉层级。

## 6. 公共视图模型

下一阶段前端不直接消费原始 `NewsEvent`，而消费 presentation model：

```ts
type PublicNewsItem = {
  id: string
  targetId: string
  targetLabel: string
  source: {
    id: string
    name: string
    type: "rss" | "api" | "web" | "social" | "official" | "unknown"
    credibilityLabel?: string
  }
  publishedAt: string
  title: string
  originalTitle?: string
  summary?: string
  recommendationReason?: string
  originalUrl?: string
  detailUrl: string
  tags: string[]
  entities: Array<{ name: string; type?: string }>
  relatedCount: number
  discussionCount?: number
  valueLabel: "精选" | "关注" | "普通" | "待评估"
  valueScore?: number
  chinaRelevanceLabel?: "高" | "中" | "低" | "未知"
}
```

该模型是前端与 API 的展示边界，不替代 `NewsEvent` 契约。

新闻流响应建议使用 envelope，而不是裸数组，方便前端做低负担增量更新：

```ts
type PublicNewsFeedResponse = {
  items: PublicNewsItem[]
  latestCursor?: string
  nextCursor?: string
  pollAfterMs: number
  hasNewer?: boolean
}
```

`latestCursor` 代表当前列表顶部最新位置，`nextCursor` 代表继续加载更早新闻的位置。服务端可以通过 `pollAfterMs` 建议前端下一次检查新内容的时间。

## 7. API 增强方向

第一阶段可继续复用：

- `GET /api/v1/events/feed`
- `GET /api/v1/events/{event_id}`
- `GET /api/v1/events/{event_id}/links`
- `GET /api/v1/targets`
- `GET /api/v1/public/targets/{target_id}/analysis`

后续建议新增或扩展 presentation API：

- `GET /api/v1/public/news`：全站公开新闻流，支持 `featured`、`target_id`、`source_id`、`category`、`date`、`q`。
- `GET /api/v1/public/news/{event_id}`：读者侧详情，不暴露后台字段。
- `GET /api/v1/public/sources`：来源目录和最近内容。
- `GET /api/v1/public/daily`：按天生成日报。

所有公开 API 默认只返回读者字段。

### 7.1 轻量实时更新

公共门户必须支持用户停留页面时自动看到新新闻，但第一阶段不引入高负担实时基础设施。

推荐策略：

- `GET /api/v1/public/news?since_cursor=...` 只返回比当前顶部更新的公开新闻。
- 无新内容时返回空 `items`，并给出较长 `pollAfterMs`；支持 `ETag` / `If-None-Match` 或 `Last-Modified` 时可返回 `304`。
- 默认轮询间隔不低于 30 秒，由服务端按 target 活跃度建议 30-180 秒。
- 页面隐藏、浏览器离线、用户处于低电量模式或连续失败时暂停或指数退避。
- 前端不强行打断阅读位置；新内容先以“有 N 条新动态”提示，用户点击后再插入顶部。
- 列表只做增量合并和去重，不整页刷新。

暂不把 WebSocket/SSE 作为默认方案。只有当后续出现高频协同阅读、低延迟告警或大量在线用户场景时，再单独做 ADR 评估。

## 8. 布局原则

### 桌面

- 使用全宽内容台，而不是窄中栏。
- 1440px 下主内容有效宽度不低于 1100px。
- 推荐结构：左侧频道导航、中央新闻流、右侧趋势/热门来源/实体摘要。
- 宏观指标只作为右栏辅助，不占据主首屏。

### 移动

- 单列新闻流。
- 底部导航保持固定且不遮挡内容。
- 首屏必须出现第一条新闻标题和摘要。
- 新新闻出现时使用顶部轻提示或列表内提示，不把正在阅读的内容突然顶走。
- 筛选使用横向 tabs 或 bottom sheet，不堆叠成大面积表单。

## 9. 组件体系

公共门户采用 shadcn/ui 作为基础组件：

- `Tabs`：频道与分类。
- `Card`：新闻卡片、来源卡片、日报块。
- `Badge`：标签、精选状态、来源类型。
- `Button`：查看原文、复制摘要、刷新。
- `Input` / `Command`：搜索。
- `Sheet`：移动筛选。
- `Skeleton`：加载态。
- `Toast`：复制、刷新、错误反馈。

News Sentry 只维护设计 tokens、布局模式和业务组件，不继续手写每个基础控件。

## 10. 验收标准

- 390x844 首屏可看到第一条新闻标题和摘要。
- 1440x900 有三栏或全宽布局，不是窄屏居中。
- 每条新闻都能进入详情或原文。
- 用户停留在首页或 target 新闻流时，新新闻能自动提示并可增量插入，无需手动刷新整页。
- 来源、摘要、推荐理由、标签、关联事件在列表层级可见。
- 公共页面中不出现裸工程字段作为主信息。
- 空状态解释“暂无新闻/暂无来源/样本不足”的读者原因，而非采集内部状态。
- 管理后台不因公共门户重构发生路由或权限回归。

## 11. 非目标

- 不复制 AIHOT 的暗色视觉皮肤。
- 不在第一阶段重写后台管理页。
- 不改变采集、过滤、研判、输出的核心 pipeline。
- 不把 React app 变成业务领域模型的事实来源。
