# RSS/API 采集子 Skill 规格

> 版本: v0.1-draft | 日期: 2026-05-09
> 状态: 开发前子规格
> **实现阶段: Phase 3 Kernel MVP（v1 主线）** — 本规格是 Kernel MVP 的核心采集基线，优先实现
> 上级文档: [Agent Skill Pack 开发总纲与多 Agent 生产线路线图](./AgentSkillPack开发总纲与多Agent生产线路线图.md)
> 字段口径基准: [contracts-canonical.md](../contracts-canonical.md)

---

## 0. 定位

RSS/API 采集子 Skill 是 News Sentry Skill Pack 的低风险生产基线。它负责从公开、结构化、可稳定轮询的来源采集新闻、政府公告、国际组织发布和权威机构更新，并映射为 `NewsEvent(stage=collected)`。

这条采集线优先服务三类场景：

1. 重大新闻和 breaking news 的低延迟发现。
2. 政府、监管机构和国际组织的权威发布监控。
3. 在 OpenCLI 和社媒登录态尚未稳定前，为系统提供可持续运行的数据底座。

---

## 1. 子 Skill 边界

### 1.1 负责事项

RSS/API collector 负责：

1. 读取 `SourceChannel(acquisition_method=rss|api)`。
2. 执行 HTTP 请求、RSS/Atom 解析或 API 调用。
3. 将条目映射为 `NewsEvent` 核心字段。
4. 基于 `source_url`、`published_at`、标题 hash 和历史 memory 去重。
5. 记录 source health、错误、空结果和增量游标。
6. 将产物写入 `raw/` 或返回给上游 orchestrator。

### 1.2 不负责事项

RSS/API collector 不负责：

1. LLM 深度研判。
2. 新闻稿草稿生成。
3. 社媒登录态管理。
4. 绕过付费墙或登录墙。
5. 对外推送或发布。

---

## 2. 输入契约

```yaml
RSSAPICollectorInput:
  target_config: TargetConfig
  pipeline_context: PipelineContext
  source_channels:
    - id: string
      dimension: news_media | international_orgs | government | academic | china_related
      source_name: string
      priority: P0 | P1 | P2 | P3
      acquisition_method: rss | api
      acquisition_config:
        url: string
        method: GET | POST
        headers: dict
        params: dict
        poll_interval: string
        timeout_seconds: int
        auth_required: bool
        cursor_strategy: none | if_modified_since | etag | since_time | page_token
      field_mapping: dict
      skill_id: rss-api-collector
      fallback_skill: builtin-rss | manual-check
  historical_events: NewsEvent[]
  runtime_options:
    max_sources_per_run: int
    max_items_per_source: int
    dry_run: bool
```

字段映射必须显式声明，避免不同 RSS 或 API 格式隐式进入后续管线。

---

## 3. 输出契约

每条成功采集的条目输出 `NewsEvent(stage=collected)`。最低字段集与现有 `NewsEvent` 设计一致：

```yaml
NewsEvent:
  id: string
  source_id: string
  source_url: string
  collected_at: datetime
  title_original: string
  content_original: string
  language: string
  content_type: article | press_release | official_doc
  source_name: string
  published_at: datetime?
  target_id: string
  source_country: string?
  involved_countries: string[]
  pipeline_stage: collected
  processing_history:
    - stage: collected
      skill_id: rss-api-collector
      timestamp: datetime
      result_summary: string
  metadata:
    acquisition:
      method: rss | api
      source_channel_id: string
      cursor_used: string?
      http_status: int?
      etag: string?
      if_modified_since: string?
```

采集失败不生成虚假的 `NewsEvent`。失败写入 run log 和 source health memory：

```yaml
SourceHealthRecord:
  source_id: string
  last_success_at: datetime?
  last_attempt_at: datetime
  consecutive_failures: int
  last_error_type: timeout | parse_error | http_error | auth_error | empty_result
  last_error_message: string
  suggested_action: retry | check_feed | downgrade | manual_check
```

---

## 4. 去重与 ID 策略

### 4.1 确定性 ID

RSS/API 事件优先使用确定性 ID，便于跨心跳和跨 Agent 去重：

```text
ne-{target_id}-{source_id}-{published_date}-{content_hash8}
```

`content_hash8` 由 `source_url + normalized_title + published_at` 生成。若 `published_at` 缺失，则使用 `source_url + normalized_title`。

### 4.2 去重顺序

1. 精确匹配 `source_url`。
2. 匹配确定性 `id`。
3. 同一 source 内标题归一化相似度高且发布时间接近。
4. 跨源相似事件不在 collect 阶段合并，只在 filter/judge 阶段关联。

collect 阶段只避免重复写入同一来源同一条目，不做事实层面的事件合并。

---

## 5. 意大利样板 SourceChannel

```yaml
source_channels:
  - id: ansa-rss
    dimension: news_media
    source_name: ANSA
    priority: P0
    acquisition_method: rss
    acquisition_config:
      url: "https://www.ansa.it/sito/notizie/topnews/topnews_rss.xml"
      poll_interval: "1h"
      timeout_seconds: 20
      cursor_strategy: if_modified_since
      auth_required: false
    field_mapping:
      title_original: "rss.title"
      source_url: "rss.link"
      content_original: "rss.description"
      published_at: "rss.pubDate"
      language: "it"
      target_id: "italy"
      source_country: "IT"
      involved_countries: ["IT"]
      content_type: "article"

  - id: fao-news-rss
    dimension: international_orgs
    source_name: FAO
    priority: P0
    acquisition_method: rss
    acquisition_config:
      url: "https://www.fao.org/newsroom/rss/en"
      poll_interval: "1h"
      timeout_seconds: 20
      cursor_strategy: etag
      auth_required: false
    field_mapping:
      title_original: "rss.title"
      source_url: "rss.link"
      content_original: "rss.description"
      published_at: "rss.pubDate"
      language: "en"
      target_id: "italy"
      source_country: null
      involved_countries: ["IT"]
      content_type: "press_release"

  - id: italian-government-api
    dimension: government
    source_name: Presidenza del Consiglio
    priority: P0
    acquisition_method: api
    acquisition_config:
      url: "https://www.governo.it/it/api/news"
      method: GET
      poll_interval: "1h"
      timeout_seconds: 20
      cursor_strategy: since_time
      auth_required: false
    field_mapping:
      title_original: "$.items[].title"
      source_url: "$.items[].url"
      content_original: "$.items[].summary"
      published_at: "$.items[].published_at"
      language: "it"
      target_id: "italy"
      source_country: "IT"
      involved_countries: ["IT"]
      content_type: "official_doc"
```

实际实现时需要验证每个 URL 的真实可用性。若源没有官方 RSS/API，应移入 OpenCLI 或 web scraping 子规格。

---

## 6. 心跳执行流程

```text
heartbeat run starts
  -> load TargetConfig and SourceChannel list
  -> select due sources by poll_interval and last_success_at
  -> request each source with timeout and retry policy
  -> parse RSS/API response
  -> map entries to NewsEvent(collected)
  -> deduplicate against memory.known_item_ids
  -> write new events to raw/
  -> update memory/source_health
  -> write run log
heartbeat run exits
```

每次 bounded run 必须有最大执行时间和最大条目数。超出限制的来源进入下一次心跳，不在单次运行内无限追赶历史数据。

---

## 7. 失败模式与降级策略

| 失败模式 | 判断方式 | 处理策略 |
|----------|----------|----------|
| HTTP timeout | 超过 `timeout_seconds` | 记录失败，指数退避，保留上次 cursor |
| HTTP 4xx | 状态码 | 401/403 标记认证或权限问题，404 标记源变更 |
| HTTP 5xx | 状态码 | 重试一次，仍失败则等待下次心跳 |
| RSS parse error | 解析器异常 | 尝试 lenient parser，失败后标记 `parse_error` |
| 空结果 | 结果为空但请求成功 | 连续空结果超过阈值后触发 source health 告警 |
| 字段缺失 | 必填字段为空 | 丢弃该条目并记录 `field_mapping_error` |
| 重复条目 | 命中 known id 或 source_url | 不写入文件，更新统计 |

降级优先级：

1. 同源备用 RSS/API。
2. OpenCLI 子 Skill。
3. 通用 web scraping。
4. 写入 `logs/manual-check.md` 等待人工检查。

---

## 8. 过滤前预标记

采集阶段不做深度判断，但可以写入轻量 metadata，帮助 filter 阶段排序：

```yaml
metadata:
  prefilter_hints:
    source_priority: P0
    contains_breaking_keyword: true
    contains_china_keyword: false
    age_minutes_at_collection: 18
    source_authority_hint: 95
```

这些字段不能代替 `filter_result` 或 `judge_result`。它们只是下游排序和预算控制的输入。

---

## 9. 验收标准

RSS/API 子 Skill v1 通过以下场景验收：

1. 能轮询至少 3 个意大利主流媒体或政府/国际组织公开源。
2. 能把每条新内容写成满足 collected 最低字段集的 `NewsEvent`。
3. 能跨两次心跳避免重复写入同一条源内容。
4. 能在源失败时写入 source health 和 run log，而不是静默失败。
5. 能把高优先级源和低优先级源按 `poll_interval` 分开调度。
6. 能为后续 filter/judge 阶段保留 `source_url`、`published_at`、`source_name` 和采集历史。

---

## 10. 与其他子 Skill 的接口

RSS/API 采集完成后：

1. 新事件进入 `raw/`，等待评估 Agent。
2. 需要全文增强的事件可由 judge 或 filter 阶段触发 OpenCLI 子 Skill。
3. 与社媒相关的重大新闻可触发社媒/KOL 子 Skill 做二次搜索。
4. 低价值或重复事件由 filter 阶段移入 `archive/`，collect 阶段只记录采集事实。
