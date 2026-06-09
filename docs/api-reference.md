# News Sentry API 文档

> 版本: v1.0.0 | 基础路径: `http://localhost:8000`

## 安装与启动

```bash
pip install ".[api]"
NEWSSENTRY_API_KEY=your-key uvicorn news_sentry.core.api_server:create_app --factory --host 0.0.0.0 --port 8000
```

## 认证

所有受保护端点需要 API Key，通过以下方式之一传递：

- HTTP Header: `X-API-Key: your-key`
- 查询参数: `?api_key=your-key`

未配置 `NEWSSENTRY_API_KEY` 环境变量时为开发模式（允许所有请求）。

速率限制: 60 requests/min per API key。

---

## 端点

### GET /api/v1/health

健康检查端点。

**响应:**
```json
{"status": "ok"}
```

### GET /public-app/

新公共门户 canonical 入口。该入口由 FastAPI 托管 Vite React 静态构建产物，是公共新闻阅读体验的主入口。

Phase 86 起，旧 `/` 仍返回 legacy shell；浏览器端会把旧公开 hash 路由软跳转到 `/public-app/` 等价路由。后台 hash 路由不跳转。

旧公开路由兼容映射：

| 旧路由 | 新路由 |
|------|------|
| `/` 或 `/#/news/feed` | `/public-app/#/feed?channel=featured` |
| `/#/news/target/:targetId` | `/public-app/#/feed?channel=targets&target_id=:targetId` |
| `/#/news/target/:targetId/:channelId` | `/public-app/#/feed?channel=targets&target_id=:targetId&category=:channelId` |
| `/#/news/target/:targetId/analysis` | `/public-app/#/analysis?target_id=:targetId` |
| `/#/news/target/:targetId/analysis/entities` | `/public-app/#/analysis?target_id=:targetId&section=entities` |
| `/#/news/target/:targetId/events/:eventId` | `/public-app/#/events/:eventId?target_id=:targetId` |
| `/#/news/events/:eventId` | `/public-app/#/events/:eventId` |

`/#/admin*`、配置、运行状态和认证后台路由继续由 legacy shell 承载。

**缓存策略:**

| 路径 | Cache-Control | 说明 |
|------|---------------|------|
| `/public-app/` | `no-cache` | SPA HTML 入口，允许浏览器复查新版本。 |
| `/public-app/assets/*` | `public, max-age=31536000, immutable` | Vite 指纹资源，允许长期缓存。 |

### GET /api/v1/events

查询事件列表。

**参数:**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| target_id | string | 是 | — | 目标标识（如 italy, japan） |
| page | int | 否 | 1 | 页码（≥1） |
| page_size | int | 否 | 20 | 每页条数（1-100） |

**响应:**
```json
{
  "total": 42,
  "events": [
    {
      "id": "ne-italy-ansa-20260512-abc12345",
      "source_id": "ansa-en",
      "url": "https://...",
      "title_original": "...",
      "news_value_score": 75,
      "china_relevance": 80,
      "pipeline_stage": "outputted",
      "judge_result": {
        "recommendation": "publish",
        "rationale": "..."
      }
    }
  ],
  "page": 1,
  "page_size": 20
}
```

### GET /api/v1/events/{event_id}

查询单个事件详情。

**参数:**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| event_id | path | 是 | 事件 ID |
| target_id | query | 是 | 目标标识 |

**响应:** 事件详情 JSON 或 404。

### GET /api/v1/public/news

公共门户读者侧新闻流。匿名只读，返回 presentation shape，不暴露后台字段。

**参数:**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| featured | bool | 否 | false | 仅返回精选/关注新闻 |
| target_id | string | 否 | — | 按 target 筛选 |
| source_id | string | 否 | — | 按来源筛选 |
| category | string | 否 | — | 按 `classification.l0` 筛选 |
| date | string | 否 | — | 日期筛选，格式 `YYYY-MM-DD` |
| q | string | 否 | — | 关键词搜索 |
| before_cursor | string | 否 | — | 加载更早新闻 |
| since_cursor | string | 否 | — | 检查比当前顶部更新的新闻 |
| page_size | int | 否 | 30 | 每次返回条数，1-100 |

**响应头:**

| Header | 说明 |
|--------|------|
| ETag | 当前响应指纹。客户端可用 `If-None-Match` 复查。 |
| X-Poll-After-Ms | 服务端建议的下一次低频检查间隔。 |
| Cache-Control | `private, max-age=0, must-revalidate` |

无变化且 `If-None-Match` 匹配时返回 `304 Not Modified`。

**响应:**

```json
{
  "items": [
    {
      "id": "ne-italy-ansa-20260609-abcd1234",
      "targetId": "italy",
      "targetLabel": "意大利新闻监控",
      "source": {
        "id": "ansa",
        "name": "ANSA",
        "type": "rss",
        "credibilityLabel": "高"
      },
      "publishedAt": "2026-06-09T09:30:00+00:00",
      "title": "意大利新闻标题",
      "originalTitle": "Titolo originale",
      "summary": "新闻摘要。",
      "recommendationReason": "推荐理由。",
      "originalUrl": "https://example.com/news",
      "detailUrl": "/public-app/#/events/ne-italy-ansa-20260609-abcd1234?target_id=italy",
      "tags": ["international-relations"],
      "entities": [],
      "relatedCount": 0,
      "discussionCount": null,
      "valueLabel": "精选",
      "valueScore": 82,
      "chinaRelevanceLabel": "高"
    }
  ],
  "latestCursor": "...",
  "nextCursor": "...",
  "pollAfterMs": 60000,
  "hasNewer": false,
  "total": 1
}
```

### GET /api/v1/public/news/{event_id}

公共门户读者侧新闻详情。匿名只读。

**参数:**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| event_id | path | 是 | 事件 ID |
| target_id | query | 否 | 可选 target 提示；提供后查找更快 |

**响应:** 单条 `PublicNewsItem` 或 404。

### POST /api/v1/webhook

接收外部事件（Webhook 入站），写入 `data/{target_id}/raw/`。

**参数:**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| target_id | query | 是 | 目标标识 |

**请求体:**

```json
{
  "source_id": "external-source",
  "url": "https://example.com/article",
  "title_original": "Breaking News Title",
  "content_original": "Article content...",
  "language": "en",
  "published_at": "2026-05-12T10:00:00Z",
  "metadata": {}
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| source_id | string | 是 | 来源标识 |
| url | string | 是 | 原始 URL |
| title_original | string | 是 | 原始标题 |
| content_original | string | 否 | 原始内容 |
| language | string | 否 | 语言代码（默认 mixed） |
| published_at | string | 否 | 发布时间 ISO 8601 |
| metadata | object | 否 | 附加元数据 |

**响应:**
```json
{
  "status": "accepted",
  "event_id": "ne-webhook-external-source-20260512-a1b2c3d4",
  "message": "Event ne-webhook-... saved to italy/raw/"
}
```

### GET /docs

Swagger UI 交互式文档。

### GET /openapi.json

OpenAPI 3.1 JSON Schema。

---

## 错误响应

| 状态码 | 说明 |
|--------|------|
| 401 | API Key 无效或缺失 |
| 404 | 事件未找到 |
| 422 | 请求参数验证失败 |
| 429 | 速率限制超限 |
