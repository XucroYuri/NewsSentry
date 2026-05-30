# Public Analysis Portal Design

## Context

Plan 1 已经把默认访问体验拆成公开新闻门户和独立管理后台。公开端现在包括：

- `#/news/feed`：公开 target 卡片首页。
- `#/news/target/:targetId`：公开频道新闻流。
- `#/news/target/:targetId/events/:eventId`：公开文章详情。

下一步不是把现有后台 `overview`、`entities`、`chains`、`trends` 直接搬到公开端。那些页面依赖受保护接口，并包含运维、反馈、诊断、写操作或过细的内部分析入口。公开分析门户应该提供读者有用的摘要，而不是暴露后台工作台。

## Goals

1. 为每个 target 增加一个公开分析页：`#/news/target/:targetId/analysis`。
2. 公开展示目标的宏观态势：事件总量、平均新闻价值、平均中国相关度、分类分布、来源分布、热门实体、主题趋势、情感趋势、活跃追踪链摘要。
3. 匿名用户可以访问分析摘要，但不能触发后台写操作、诊断、配置、反馈、链叙述生成或原始管理列表。
4. 公开新闻流与公开分析页之间可以互相跳转，仍保持顶部导航和当前暗色专业工具视觉。
5. 后台分析页面继续保留在 `#/admin/news/overview`、`#/admin/news/entities`、`#/admin/news/chains`、`#/admin/news/trends`。

## Non-Goals

1. 不公开现有 `/api/v1/stats`、`/api/v1/entities`、`/api/v1/chains`、`/api/v1/trends/*` 后台端点。
2. 不新增公开实体详情页、公开追踪链详情页或公开趋势后台页。
3. 不支持匿名导出、邮件发送、人工反馈、重新生成叙述、手动采集或诊断。
4. 不修改 `NewsEvent` schema，不新增竞争事件对象。
5. 不改变 Plan 1 中管理后台登录和受保护路由边界。

## Recommended Approach

第一版采用“聚合快照端点 + 公开分析页”的方式。

新增只读端点：

```text
GET /api/v1/public/targets/{target_id}/analysis?days=14
```

该端点返回面向公开展示的聚合快照，而不是复用多个后台端点。好处是权限边界清晰，前端只请求一个匿名端点，后续可以独立缓存或裁剪字段。后台现有端点继续保持认证，避免出现“为了公开页顺手放开后台 API”的风险。

备选方案及取舍：

- 直接放开 stats/entities/chains/trends：实现快，但权限边界粗，会让后台 API 语义漂移。
- 公开页只使用 events/feed 前端计算：接口最少，但趋势、实体、链摘要质量弱，且浏览器端重复计算会越来越重。
- 聚合快照端点：实现量适中，边界清楚，最适合第一版。

## Route Design

公开端新增：

```text
#/news/target/:targetId/analysis
```

公开导航规则：

- `#/news/feed` 显示 target 卡片。
- `#/news/target/:targetId` 显示频道新闻流。
- `#/news/target/:targetId/:channelId` 显示指定频道新闻流。
- `#/news/target/:targetId/analysis` 显示公开分析门户。
- `#/news/target/:targetId/events/:eventId` 显示公开文章详情。

路由解析需要优先识别 `analysis`，避免把它误当作频道 ID。

## API Contract

`GET /api/v1/public/targets/{target_id}/analysis?days=14`

查询参数：

| 参数 | 规则 |
|------|------|
| `days` | 整数，允许 7、14、30，默认 14 |

响应示例：

```json
{
  "target_id": "italy",
  "target_name": "意大利新闻监控",
  "days": 14,
  "generated_at": "2026-05-26T10:00:00+00:00",
  "summary": {
    "total_events": 128,
    "high_value_events": 24,
    "avg_news_value_score": 68.2,
    "avg_china_relevance": 31.4
  },
  "classification_distribution": [
    { "name": "politics", "count": 42 }
  ],
  "source_distribution": [
    { "source_id": "ansa", "display_name": "ansa", "count": 18 }
  ],
  "top_entities": [
    { "name": "Meloni", "entity_type": "person", "mention_count": 12 }
  ],
  "topic_trends": [
    {
      "topic": "regulation",
      "trend_direction": "rising",
      "hotness": 74,
      "current_count": 9,
      "prev_count": 4,
      "daily_counts": [{ "day": "2026-05-26", "count": 3 }]
    }
  ],
  "sentiment_trend": [
    { "day": "2026-05-26", "positive": 2, "negative": 1, "neutral": 8 }
  ],
  "active_chains": [
    {
      "root_event_id": "ne-italy-ansa-20260526-a1b2c3d4",
      "event_count": 3,
      "latest_title": "Example title",
      "latest_time": "2026-05-26T08:00:00+00:00",
      "narrative_summary": "该链条呈现政策议题持续发酵。"
    }
  ]
}
```

字段裁剪规则：

- `top_entities` 只返回公开摘要字段：名称、类型、提及次数。
- `active_chains` 只返回摘要字段，不返回完整事件链和内部 signals。
- `topic_trends` 复用已有趋势计算输出，但最多返回 10 个主题。
- `sentiment_trend` 返回每日计数，不返回原始事件。
- 空数据返回空数组和 0/null 指标，不返回 401 或 500。

## Data Flow

1. 公开页面加载 `targets`，用于 target 名称和导航。
2. 用户进入 `#/news/target/:targetId/analysis`。
3. 前端请求公开聚合端点。
4. 后端优先使用 target store 聚合数据；若 store 不可用，使用文件系统事件扫描降级生成 summary、分类分布和来源分布。
5. 前端渲染摘要卡、分布条、趋势列表、情感条和链摘要。
6. 读者点击“返回新闻流”回到 `#/news/target/:targetId`。

## Page Structure

公开分析门户使用 full-width public shell，不显示后台侧边栏、tab、SSE 状态或设置入口。

页面区域：

1. Target header
   - target 名称
   - 时间范围切换：7 / 14 / 30 天
   - 返回新闻流按钮

2. Summary strip
   - 事件总数
   - 高价值事件数
   - 平均新闻价值
   - 平均中国相关度

3. Situation grid
   - 左侧：主题趋势和情感趋势
   - 右侧：热门实体、分类分布、来源分布

4. Chain digest
   - 活跃追踪链摘要列表
   - 每条只展示最新标题、事件数、更新时间和 narrative summary

## Error And Empty States

1. target 不存在：显示“未找到该监控目标”，提供返回公开首页。
2. 无分析数据：显示“暂无分析数据”，保留返回新闻流入口。
3. 接口失败：显示可读错误和重试按钮。
4. 部分区块为空：只显示该区块空态，不影响其他区块。
5. 字段缺失：局部降级，不显示空标题、空数值标签或空叙述。

## Security Boundary

继续公开：

- `/api/v1/health`
- `/api/v1/targets`
- `/api/v1/events/feed`
- `/api/v1/events/{event_id}` 公开详情
- 新增 `/api/v1/public/targets/{target_id}/analysis`

继续保护：

- `/api/v1/stats`
- `/api/v1/stats/today`
- `/api/v1/events`
- `/api/v1/events/top`
- `/api/v1/events/{event_id}/links`
- `/api/v1/events/{event_id}/chain`
- `/api/v1/entities`
- `/api/v1/entities/{entity_id}`
- `/api/v1/chains`
- `/api/v1/chains/{root_id}/narrative`
- `/api/v1/trends/topics`
- `/api/v1/trends/sentiment`
- 所有 config、ops、feedback、alerts、maintenance、admin、写操作

公开分析页不得请求任何受保护端点。

## Testing

API 测试：

- 匿名请求公开分析端点返回 200。
- `days=7/14/30` 返回对应天数。
- 非法 `days` 返回 422。
- 无数据 target 返回 200 和空数组。
- 匿名访问现有后台分析端点仍返回 401。
- 登录 token 下现有后台分析端点仍保持既有行为。

JS 路由测试：

- `#/news/target/italy/analysis` 解析为 `publicTargetAnalysis`。
- `#/news/target/italy/policy` 仍解析为频道新闻流。
- 公开分析链接生成函数正确编码 target。

浏览器验证：

- 匿名访问公开分析页不跳登录。
- Network 中不出现受保护 API 请求。
- 桌面和 390px 移动端无横向溢出。
- 切换 7 / 14 / 30 天不会卡在加载态。
- 返回新闻流按钮回到对应 target 门户。

## Implementation Boundaries

建议拆成四个实现任务：

1. 后端公开分析聚合端点与 API 测试。
2. 路由和 public portal helper 测试。
3. 公开分析页面模块和公开导航入口。
4. 浏览器 smoke、鉴权边界回归和最终提交。

实现时不得纳入当前并行本地改动：

- `src/news_sentry/static/pages/dashboard.js`
- `src/news_sentry/static/style.css`
- `.omx/`
- `docs/plans/frontend-redesign-analysis.md`
- `docs/plans/plan-phase-74-feed-redesign.md`
- `docs/plans/plan-phase-75-public-news-workbench.md`

如果必须新增样式，优先放入 `src/news_sentry/static/public.css`，避免与当前 `style.css` 并行改动冲突。
