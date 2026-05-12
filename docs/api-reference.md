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
