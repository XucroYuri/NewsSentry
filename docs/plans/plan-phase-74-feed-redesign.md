# Phase 74: 新闻流首页重设计落地

> 日期: 2026-05-26
> 状态: Phase B 首屏闭环已落地

## 目标

将 `#/news/feed` 从雏形升级为默认新闻消费入口。用户打开系统后优先看到按日期分组的新闻流，并能在不展开详情的情况下看到标题、来源、分数、扁平标签和事件级 AI 理由。

## 范围

- 不修改 `NewsEvent` schema。
- 不新增独立事件对象。
- 在现有 `/api/v1/events/feed` 上补充展示字段。
- 保留 `overview/events/chains/entities/trends/ops/config/settings` 等管理视图。
- 将默认入口从 `#/news/overview` 调整为 `#/news/feed`。

## 已落地

- Feed API 展示字段：
  - `event_id`
  - `display_title`
  - `score`
  - `source_display_name`
  - `flat_tags`
  - `ai_reason`
  - `recommendation`
  - `related_count`
- `ai_reason` 优先来自 `judge_result.rationale` 第一句，缺失时降级到正文摘要。
- `flat_tags` 从 `metadata.classification`、`topic_tags` 和实体信息合成，最多 4 个。
- 新闻流前端读取新字段，列表/卡片显示 AI 理由，紧凑视图保持高密度。
- 登录后默认进入 `#/news/feed`，侧边栏新闻入口也指向 `#/news/feed`。
- 触及的导航、登录页和 SSE toast 文案移除 emoji。
- 全局主色从橙色切换为克制暗红，旧变量名保留以兼容现有页面。

## 验证

```bash
.venv/bin/python3 -m pytest tests/unit/test_api_server.py -q
.venv/bin/ruff check src/news_sentry/core/api_server.py tests/unit/test_api_server.py
node --check src/news_sentry/static/pages/feed.js
node --check src/news_sentry/static/app.js
rg -n "[\\x{1F300}-\\x{1FAFF}]" src/news_sentry/static/app.js src/news_sentry/static/index.html src/news_sentry/static/pages/feed.js
rg -n "#ff8000|255, 128, 0|#cc6600|204, 102, 0|#ff9933" src/news_sentry/static/style.css src/news_sentry/static/pages/feed.js
```

本地服务验证：

```bash
.venv/bin/uvicorn "news_sentry.core.api_server:create_app" --factory --host 127.0.0.1 --port 8765
curl --noproxy "*" http://127.0.0.1:8765/api/v1/health
```

## 后续

- Phase C 继续清理未触及页面中的历史蓝色、GitHub 风格颜色和剩余 emoji。
- 给 `source_display_name` 增加后端 source 配置映射缓存，减少前端逐源配置请求。
- 增加浏览器截图回归，覆盖桌面和移动宽度下的新闻流布局。
