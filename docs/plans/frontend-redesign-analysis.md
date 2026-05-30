# News Sentry 前端重设计落地方案

> 日期: 2026-05-26
> 来源分支: `feature/frontend-redesign-analysis`
> 目标: 将参考站分析升级为可指导后续开发、验收和回归的前端重设计方案

---

## 1. 现状校准

本方案以 `main` 当前实现为基准，而不是照搬 `feature/frontend-redesign-analysis` 的代码改动。

当前已经存在的事实：

- 前端是 FastAPI StaticFiles 托管的 Vanilla JS SPA，符合 ADR-0025。
- 路由结构仍是 `#/section/tab`，新闻区位于 `#/news/*`。
- 已有 `#/news/feed` 雏形，入口组件为 `src/news_sentry/static/pages/feed.js`。
- 已有 `/api/v1/events/feed`，当前返回按日期分组的事件流。
- 当前视觉基调是 `#1a1a1e` 暗背景和 `#ff8000` Reuters 橙。
- 管理能力仍集中在 overview/events/chains/entities/trends/alerts/ops/config/settings 等视图中。

需要避免的旧分支误差：

- 不接受该分支移除 feed 页面模块的结果；新闻流是本轮重设计的第一闭环。
- 不新增独立 `#/feed` 作为唯一入口；继续使用现有 hash router，默认落到 `#/news/feed`。
- 不把事件级 AI 理由描述为既有 `narrative` 字段；链级叙述仍属于 chain narrative，事件级理由第一版来自 `judge_result.rationale`。
- 不沿用旧分析里的蓝色主视觉方案；本轮视觉语言改为克制暗红中国红。

---

## 2. 参考站可借鉴点

`aihot.virxact.com` 值得借鉴的不是具体 UI 皮肤，而是新闻消费范式。

### 2.1 时间流组织

新闻用户打开页面时，第一问题通常是“今天发生了什么”，不是“我要先进入哪个管理 Tab”。因此首页应按日期和发布时间组织新闻，最新在前，日期作为阅读节奏的自然分隔。

落地到 News Sentry：

- `#/news/feed` 成为默认新闻消费入口。
- `#/`、`#/news`、旧默认入口应重定向或自然落到 `#/news/feed`。
- `#/news/overview` 保留为分析概览，不再承担默认首页职责。

### 2.2 AI 理由可见

News Sentry 的价值不只是聚合新闻，而是完成“增强人工研判”的第一步。每条新闻都应该有一句人能立刻读懂的价值判断，让编辑快速决定是否展开、追踪或归档。

第一版不新增 schema：

- 优先从 `judge_result.rationale` 取第一句。
- 如果第一句过长，截取前 60 个中文字符并补省略号。
- 如果 `judge_result.rationale` 缺失，再降级到 `content_translated` 或 `content_original` 的摘要预览。
- 字段在 feed 响应中命名为 `ai_reason`，这是 API 展示字段，不是 `NewsEvent` 顶层契约字段。

### 2.3 扁平标签和高密度

当前 L0/L1、实体、话题标签都很有价值，但直接全量展示会让新闻流变成结构化数据表。新闻流中只展示 2-4 个直觉标签，完整结构留给详情页。

标签来源优先级：

1. `classification.l0`
2. `classification.l1` 中可读性最高的 1 项
3. `topic_tags` 前 1-2 项
4. `nlp_entities` 中高相关实体 1 项

视觉规则：

- 新闻流标签统一为中性 chip，不使用彩虹分类色。
- 高价值状态使用分数和红色强调表达，不靠多色标签表达。
- 一屏目标展示 8-10 条紧凑新闻摘要。

---

## 3. News Sentry 落地原则

### 3.1 产品定位

前端从“管理后台”转为“新闻情报工作台”。

这不是删除管理能力，而是重新安排默认优先级：

- 默认页服务新闻消费和人工研判。
- 管理、运维、配置退到次级导航。
- 事件详情、追踪链、实体、趋势继续保留，用于展开分析。
- 反馈闭环继续保留，符合 Iron Man 套装原则。

### 3.2 信息层级

新闻流条目的默认层级如下：

```text
时间 + 来源 + 分数
标题
2-4 个扁平标签
AI 理由
来源链接 / 原文链接 / 关联数量
```

展开态再显示：

```text
完整评分
情感与实体
关联事件或追踪链入口
反馈操作
原始字段
```

### 3.3 视觉方向

视觉语言采用“暗红新闻室”，不是节庆大红。

深色主题建议：

- 页面底色: `#171314`
- 区块底色: `#211b1c`
- 悬停底色: `#2b2324`
- 主强调色: `#b3262d`
- 主强调 hover: `#c63a3f`

浅色主题建议：

- 页面底色: `#f7f4f2`
- 区块底色: `#fffdfb`
- 悬停底色: `#eee7e3`
- 主强调色: `#8f1d22`
- 主强调 hover: `#a52a2a`

约束：

- 语义色只保留成功、警告、错误。
- 链接、按钮 active、focus ring、当前导航用暗红系。
- 普通 hover 用中性灰，不全站泛红。
- 去除界面 emoji；导航、空态、通知使用文字、现有 SVG 或 CSS 图标。

---

## 4. Public Interfaces

### 4.1 `/api/v1/events/feed`

不新增端点，在现有 `/api/v1/events/feed` 上扩展展示字段。目标响应：

```json
{
  "total": 42,
  "page": 1,
  "page_size": 100,
  "groups": [
    {
      "date": "2026-05-26",
      "events": [
        {
          "event_id": "ne-target-source-20260526-abcd1234",
          "display_title": "DeepSeek API 价格永久下调",
          "score": 86,
          "source_id": "rss-deepseek",
          "source_display_name": "DeepSeek 官方博客",
          "published_at": "2026-05-26T08:15:00+08:00",
          "flat_tags": ["tech", "DeepSeek", "行业动态"],
          "ai_reason": "API 长期降价会改变模型调用成本结构，值得持续观察。",
          "recommendation": "review",
          "related_count": 3,
          "url": "https://example.com/news"
        }
      ]
    }
  ]
}
```

字段规则：

| 字段 | 规则 |
|------|------|
| `display_title` | 优先 `title_translated`，否则 `title_original` |
| `score` | 优先 `news_value_score`，否则 `importance_score`，否则 `null` |
| `source_display_name` | 优先 source 配置 `display_name`，否则 `source_id` |
| `flat_tags` | 由 classification、topic_tags、实体合成，最多 4 个 |
| `ai_reason` | 从 `judge_result.rationale` 提取；缺失时用正文摘要降级 |
| `recommendation` | 来自 `judge_result.recommendation`；缺失时可为空 |
| `related_count` | 可选；无链路数据时返回 0 或省略 |

### 4.2 路由兼容

默认入口：

```text
#/              -> #/news/feed
#/news          -> #/news/feed
#/news/feed     -> 新闻流首页
#/news/overview -> 分析概览
```

必须保留：

```text
#/news/events
#/news/events/:id
#/news/chains
#/news/chains/:id
#/news/entities
#/news/entities/:id
#/news/trends
#/alerts/*
#/ops/*
#/feedback/*
#/config/*
#/settings/*
```

---

## 5. 分阶段实施方案

### Phase A: 文档校准

目标：让本文件成为前端重设计的单一指导文档。

任务：

- 合并参考站三点结论：时间流、AI 理由、扁平高密度标签。
- 校正旧分支中与 main 不一致的内容。
- 明确 `judge_result.rationale` 是事件级 AI 理由第一来源。
- 明确 `#/news/feed` 是默认新闻入口。

验收：

- 文档可以独立指导实现，不依赖口头上下文。
- 文档中没有要求移除 feed 页面模块、新增独立 `#/feed` 唯一路由、或把链级叙述当作事件字段。

### Phase B: 新闻流闭环

目标：完成用户打开系统后的第一屏新闻消费体验。

后端任务：

- 扩展 `/api/v1/events/feed` 返回 `display_title`、`score`、`flat_tags`、`ai_reason`、`recommendation`、`source_display_name`。
- 保持现有 `groups` 结构兼容，旧前端读取 `groups[].events` 不应中断。
- `ai_reason` 提取逻辑优先复用文件 frontmatter 中的 `judge_result.rationale`。

前端任务：

- 将 `feed.js` 默认视图改为高密度时间线。
- 每条新闻展示时间、来源、分数、标题、标签、AI 理由。
- 列表默认一屏展示 8-10 条。
- 卡片视图和紧凑视图可以保留，但不得影响默认时间流体验。
- 来源展示从技术 `source_id` 升级为 `display_name` 优先。

验收：

- 访问 `#/news/feed` 可读到按日期分组的新闻流。
- 每条新闻在有数据时显示 AI 理由。
- 无 AI 理由时不出现空白占位或报错。
- 低数据量、无数据、接口失败都有明确空态。

### Phase C: 全局视觉与导航

目标：将视觉从 Reuters 橙管理后台转为克制暗红新闻情报工作台。

样式任务：

- 重建 `style.css` 根变量、light 变量和 `prefers-color-scheme: light` 变量。
- 将 `--accent-blue` 这类历史命名逐步兼容到新的暗红 accent，不在第一轮大规模改变量名。
- 清理散落硬编码的橙色、蓝色、紫色和 GitHub 风格颜色。
- 标签、按钮、链接、focus ring 统一使用新变量。

导航任务：

- 默认路由落到 `#/news/feed`。
- 新闻流作为新闻区第一个 Tab。
- 管理类视图继续存在，但视觉上降级为次级操作。
- 移除导航、登录页、通知和空态中的 emoji。

验收：

- 深色和浅色主题都符合暗红克制风格。
- 导航和通知没有 emoji。
- 管理页面仍可访问。
- 移动端侧边栏或导航不会遮挡新闻流内容。

### Phase D: 管理能力回收

目标：保留系统的完整管理能力，但降低默认认知负荷。

任务：

- `overview` 定位为分析概览，不再和新闻流争夺首页。
- `events` 保留为检索和批量管理视图。
- `chains`、`entities`、`trends` 保留为展开分析视图。
- `ops`、`config`、`settings` 保留为系统管理视图。
- 事件详情页增加从新闻流进入后的返回路径或上下文感。

验收：

- 从新闻流进入详情，再进入链/实体/反馈时路径清晰。
- 旧管理操作不因新闻流重构丢失。
- 用户可以在 1 次点击内从新闻流进入事件详情。

### Phase E: 验收与回归

目标：建立后续实现的最小验证闭环。

API 验证：

```bash
.venv/bin/python3 -m pytest tests/unit/test_api_server.py -q
```

前端验证：

- 本地启动 `news-sentry serve` 或等价开发服务。
- 浏览器打开 `#/news/feed`。
- 验证桌面和移动宽度下新闻流不重叠、不截断核心信息。
- 手动切换浅色和深色主题。
- 检查无数据、接口失败、加载中状态。

代码搜索验收：

```bash
rg -n "[\\x{1F300}-\\x{1FAFF}]" src/news_sentry/static
rg -n "#ff8000|255, 128, 0|#4f8ff7|#58a6ff" src/news_sentry/static/style.css
```

允许保留：

- 品牌 SVG 或非 emoji 图标。
- 语义成功、警告、错误色。
- 兼容旧变量名但值已映射到新色板的 CSS 变量。

---

## 6. 后续开发检查清单

开发前：

- 先读 `docs/contracts-canonical.md`，确认字段口径。
- 确认不修改 `NewsEvent` schema。
- 确认只扩展 feed API 展示字段，不新增竞争事件对象。

开发中：

- 优先改 `/api/v1/events/feed` 和 `feed.js`，先让新闻流完整可用。
- 再做 `style.css` 全局变量和散落颜色收敛。
- 最后处理导航默认入口、emoji 清理和管理视图降噪。

提交前：

- 跑最窄 API 测试。
- 浏览器检查 `#/news/feed`。
- 搜索 emoji 和旧品牌色残留。
- 确认未删除管理功能和旧路由。

---

## 7. 决策记录

| 决策 | 结论 |
|------|------|
| 主入口 | `#/news/feed` |
| 事件级 AI 理由 | 第一版复用 `judge_result.rationale` |
| Schema 变更 | 不变更 |
| Feed API | 扩展现有 `/api/v1/events/feed` |
| 视觉方向 | 克制暗红中国红 |
| 标签策略 | 2-4 个扁平中性标签 |
| 管理能力 | 保留，但降级为次级视图 |
| emoji | 前端 UI 移除 |

---

## 8. 与参考站的差异

News Sentry 不复制参考站，而是吸收其新闻消费逻辑。

| 维度 | 参考站 | News Sentry 落地 |
|------|--------|------------------|
| 定位 | AI 新闻聚合 | 新闻情报监控与人工研判工作台 |
| 首页 | 时间流 | 时间流，但保留管理入口 |
| AI 内容 | 推荐理由 | AI 理由 + 评分 + 追踪链 + 反馈闭环 |
| 标签 | 扁平标签 | 扁平展示，底层仍保留 L0-L3 分类 |
| 运维能力 | 基本无 | 保留 ops/config/settings |
| 发布边界 | 面向消费 | v1 仍止于通知和人工审批，不自动发布 |

---

## 9. 成功标准

本轮重设计真正落地的标准不是“换了一套颜色”，而是：

- 用户打开系统首先看到当天新闻流。
- 用户不展开详情也能理解每条新闻为什么值得看。
- 一屏能扫描 8-10 条新闻。
- 标签帮助判断，不制造新的阅读负担。
- 管理能力仍在，但不压过新闻消费体验。
- 深色和浅色主题形成同一套克制暗红设计语言。
- 后续工程师能按本文档分阶段实现和验收。
