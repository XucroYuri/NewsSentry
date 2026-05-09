# News Sentry Agent Skill Pack 开发总纲与多 Agent 生产线路线图

> 版本: v0.1-draft | 日期: 2026-05-09
> 状态: 开发前规格与决策路线图
> 前置文档: [架构总览](../architecture-overview.md) | [NewsEvent Schema](../newsevent-schema.md) | [Integration Protocol](../integration-protocol.md) | [信息获取链条与自动化机制](./information-acquisition-chains.md) | [KOL追踪与信源动态管理](./kol-tracking-and-source-management.md)

---

## 0. 核心定位

News Sentry 的目标不是做一个只服务意大利样板的 breaking news demo，而是开发一套可被心跳型 Agent 框架调用的 **Agent Skill Pack**。它应能运行在 Hermes Agent、Codex、OpenClaw 等具备定时触发、上下文记忆、终端执行和自主决策能力的框架中，用于新闻媒体集团驻外机构或记者站的 24 小时信息值守。

这个 Skill Pack 的 v1 目标是：

1. 对目标国家、地区或领域进行持续新闻监控。
2. 自动抓取、过滤、去重和研判高价值新闻线索。
3. 对重大新闻、国际组织权威发布、涉华议题和舆情动态进行优先追踪。
4. 将结果写入 Obsidian + Git 可审阅文件系统。
5. 自动生成简报或新闻稿草稿，但不自动对外发布。

意大利是第一套样板配置，不是架构边界。所有核心能力必须通过配置支持迁移到其他国家、地区或专题领域。

---

## 1. 设计原则

### 1.1 框架无关核心

Skill Pack 不绑定 Hermes、Codex 或 OpenClaw 的内部接口。宿主框架只负责触发心跳、提供运行环境、注入上下文和读取产物。核心逻辑使用统一的输入输出契约：

```yaml
SkillPackRunInput:
  target_config: TargetConfig
  pipeline_context: PipelineContext
  source_channels: SourceChannel[]
  historical_events: NewsEvent[]
  runtime_options:
    max_duration_seconds: int
    max_events_per_run: int
    dry_run: bool

SkillPackRunOutput:
  run_id: string
  events_written: NewsEvent[]
  files_written: string[]
  stage_summary: dict
  errors: RunError[]
  next_actions: string[]
```

每次心跳执行一个 bounded run：启动、读取输入、处理有限数量的任务、写入文件、更新 memory，然后退出。下一次心跳由宿主框架再次触发，避免 Skill Pack 自己无限循环导致失控。

### 1.2 配置驱动

国家、领域、信源、关键词、评分权重、输出路径和推送策略都由配置注入。v1 至少需要支持以下配置对象：

| 配置对象 | 作用 |
|----------|------|
| `TargetConfig` | 定义目标国家/地区、语言范围、关注领域、优先级阈值 |
| `SourceChannel[]` | 定义每条采集链的来源、方法、频率、字段映射、降级策略 |
| `FilterRules` | 定义关键词、实体、来源、时间和可信度规则 |
| `OutputPolicy` | 定义各类事件写入哪些目录、是否推送、是否生成草稿 |
| `AgentRoles` | 定义采集、评估、草稿、内审等 Agent 的职责边界 |

### 1.3 文件优先，数据库后置

v1 使用 Obsidian + Git 文件作为主存储。文件同时承担数据交换、人工审阅、远程协作和审计记录功能。数据库可以在后续用于任务队列、检索和统计，但不作为 v1 的必需依赖。

### 1.4 自动化到草稿为止

Agent 可以自动完成采集、过滤、研判、摘要、草稿生成和归档建议。正式对外发布必须由人工确认，或者在后续版本中引入更严格的审批策略后再开放。

---

## 2. 总体架构

```text
Heartbeat Host (Hermes / Codex / OpenClaw)
  -> Skill Pack Adapter
    -> Pipeline Orchestrator
      -> collect sub-skills
         - RSS/API collector
         - OpenCLI collector
         - Social/KOL collector
      -> filter sub-skills
         - rule filter
         - deduplicator
         - relevance classifier
      -> judge sub-skills
         - news value judge
         - china relevance judge
         - event tracker
      -> output sub-skills
         - markdown writer
         - draft writer
         - archive writer
         - notification handoff
```

核心编排器不直接理解每个平台的细节。每个采集子 skill 只负责把原始来源映射成 `NewsEvent(stage=collected)`。过滤、研判和输出阶段沿用现有 Integration Protocol 的原则：只能丰富 `NewsEvent`，不能删除字段；淘汰事件也必须保留处理记录。

---

## 3. 多 Agent 生产线

### 3.1 Agent 角色

| 角色 | 输入 | 输出 | 自主边界 |
|------|------|------|----------|
| 采集 Agent | `SourceChannel[]`、上次运行 memory | `raw/` 中的 collected NewsEvent | 可自动轮询和落盘 |
| 评估 Agent | `raw/`、规则和历史事件 | `evaluated/` 或 `archive/` | 可自动过滤、去重、评分 |
| 草稿 Agent | `evaluated/` 中高价值事件 | `drafts/` 中简报或新闻稿草稿 | 可自动写草稿，不可发布 |
| 内审 Agent | `drafts/`、来源链接、研判理由 | `reviewed/` 或 `archive/` | 可给出审阅意见，不代表人工签发 |
| 发布/归档 Agent | `reviewed/` | `published/` 或外部推送队列 | v1 默认只写文件，不自动发布 |

### 3.2 文件事件协议

v1 使用目录状态表达生产阶段：

```text
workspace/
  raw/
  evaluated/
  drafts/
  reviewed/
  published/
  archive/
  memory/
  logs/
```

目录含义如下：

| 目录 | 含义 |
|------|------|
| `raw/` | 采集阶段产物，字段满足 NewsEvent collected 必填项 |
| `evaluated/` | 过滤和研判后产物，包含 `filter_result` 和必要的 `judge_result` |
| `drafts/` | 面向编辑或记者的简报、线索说明或新闻稿草稿 |
| `reviewed/` | 人工或内审 Agent 审阅后的候选发布稿 |
| `published/` | 已确认可发布或已作为正式档案保留的产物 |
| `archive/` | 低价值、重复、误报、失败样本和被打回内容 |
| `memory/` | 跨心跳记忆，如 known event ids、source health、KOL 状态 |
| `logs/` | 每次 bounded run 的执行摘要和错误记录 |

文件移动必须保持可追溯。一个事件被归档时不删除正文，而是在 frontmatter 中写入 `archive_reason`、`archived_by`、`archived_at`。目录状态是多 Agent 交接状态，不替代 `NewsEvent.pipeline_stage`；这些额外字段属于输出层 metadata/frontmatter 扩展，不改变 NewsEvent 核心 schema。

### 3.3 Markdown Frontmatter 基线

```yaml
---
id: ne-20260509-it-ansa-001
source_id: ansa-rss
source_url: https://example.org/news/001
source_name: ANSA
collected_at: 2026-05-09T08:00:00Z
published_at: 2026-05-09T07:40:00Z
target_id: italy
source_country: IT
involved_countries: [IT, CN]
language: it
content_type: article
pipeline_stage: judged
agent_id: news-sentry-judge
run_id: run-20260509-0800-it
news_value_score: 82
china_relevance: 76
breaking_news_level: significant
review_status: draft_required
---
```

正文至少包含：原始标题、中文摘要、来源摘录、研判理由、建议动作、来源链接。对社媒内容必须保留原帖链接或可定位标识。

---

## 4. 国家模板化模型

### 4.1 TargetConfig

```yaml
target_id: italy
target_country: IT
display_name: "Italy News Sentry"
language_scope: ["it", "en", "zh"]
timezone: "Europe/Rome"
focus_areas:
  - breaking_news
  - government_policy
  - international_orgs
  - china_related_opinion
  - diaspora_community
priority_thresholds:
  draft: 70
  urgent: 85
  archive_below: 35
output_policy:
  vault_root: "NewsSentry/Italy"
  auto_publish: false
```

### 4.2 意大利样板覆盖范围

第一套意大利配置用于验收：

| 类别 | P0 样板源 |
|------|-----------|
| 主流媒体 | ANSA, Corriere della Sera, La Repubblica |
| 政府监管 | Presidenza del Consiglio, Ministero degli Esteri |
| 国际组织 | FAO, WFP, IFAD |
| 涉华源 | 中国驻意使馆、涉华关键词搜索、在意华文媒体 |
| 社媒/KOL | 意大利政要、外交安全人物、主流记者、智库研究员 |

国家模板化不要求 v1 一次性覆盖所有源。v1 的成功标准是：同一套 Skill Pack 协议可以通过配置替换目标国家，而不改动核心采集、过滤、研判和输出流程。

---

## 5. 三类采集子规格的关系

三类采集能力全部纳入架构，但独立规格、独立验收：

| 子规格 | v1 定位 | 依赖风险 | 主要产物 |
|--------|---------|----------|----------|
| RSS/API 采集 | 低风险生产基线 | 低 | 稳定的新闻、政府、国际组织事件 |
| OpenCLI 采集 | 网站和终端轮询增强 | 中 | 无 RSS 网站、全文页面、搜索结果 |
| 社媒登录态/KOL 追踪 | 高价值实验通道 | 高 | KOL 发言、社媒舆情、候选信源 |

它们共享 `SourceChannel`、`NewsEvent`、`PipelineContext` 和文件事件协议。差异只体现在 `acquisition_method`、认证方式、失败模式和风险治理。

---

## 6. 自主决策边界

Agent 可以自主执行：

1. 按心跳读取配置并轮询信源。
2. 对新事件生成确定性 ID 并去重。
3. 根据规则和 LLM 研判分配优先级。
4. 将事件写入 `raw/`、`evaluated/`、`drafts/` 或 `archive/`。
5. 为高价值事件生成简报或新闻稿草稿。
6. 提出下一步追踪建议，如二次搜索、关联事件、观察 KOL。

Agent 不可以自主执行：

1. 对外发布新闻稿、社交媒体帖文或正式通稿。
2. 绕过人工确认使用私人或敏感账号。
3. 采集非公开、绕权限或违反平台条款的数据。
4. 删除原始事件和审计记录。
5. 在来源不足时将推测写成事实。

---

## 7. 路线图

### 阶段 1: Skill Pack 骨架与文件事件闭环

目标是验证多 Agent 生产线，不追求源覆盖最大化。

交付内容：

1. `TargetConfig`、`SourceChannel`、`OutputPolicy` 配置结构。
2. `raw/ -> evaluated/ -> drafts/ -> archive/` 文件事件协议。
3. RSS/API 低风险采集基线。
4. 基础过滤、去重和新闻价值评分。
5. 草稿生成模板。

验收场景：一条意大利新闻、一条国际组织发布、一条涉华线索能够进入不同输出状态，并保留来源、评分和处理历史。

### 阶段 2: OpenCLI 与全文/网页增强

目标是把无 RSS 或需要登录态以外网页操作的来源纳入。

交付内容：

1. OpenCLI wrapper 契约。
2. 适配器健康检查。
3. 命令输出到 `NewsEvent` 的映射规范。
4. 失败降级到网页抓取或人工检查队列。

验收场景：一个意大利媒体页面、一个国际组织项目页面、一个关键词搜索结果可以通过 OpenCLI 转为 `NewsEvent`。

### 阶段 3: 社媒登录态与 KOL 追踪

目标是建立高价值实验通道，而不是立即全量生产化。

交付内容：

1. KOL registry 配置。
2. Session pool 和账号预算规则。
3. 登录态采集审计记录。
4. KOL 候选发现、观察期和剪枝机制。
5. 合规边界和风险降级策略。

验收场景：少量公开 KOL 的涉华发言进入 `raw/` 或 `evaluated/`，并可触发草稿 Agent 生成舆情线索说明。

---

## 8. 风险与治理

| 风险 | 影响 | v1 策略 |
|------|------|---------|
| 误报 | 编辑成本升高 | 保留 `confidence`、`reasoning`、`archive_reason` |
| 漏报 | 错过重大新闻 | P0 RSS/API 作为基线，OpenCLI 和社媒补盲 |
| Git 冲突 | 多 Agent 同时写文件 | 文件名包含 `id` 和 `run_id`，同事件只追加处理历史 |
| LLM 成本 | 长期运行成本不可控 | `max_events_per_run`、优先级队列、低分事件不进 LLM |
| 来源失效 | 数据中断 | source health 写入 memory，失败后降级或告警 |
| 登录态风险 | 封号或合规问题 | 社媒作为实验通道，账号预算和人工授权必需 |
| 自动发布风险 | 事实或合规事故 | v1 不自动发布，只产草稿和 reviewed 文件 |

---

## 9. 验收标准

总纲验收必须满足：

1. 一个宿主 Agent 框架可以用同一入口触发 bounded run。
2. Skill Pack 不依赖某个框架内部 memory 或任务队列才能理解状态。
3. 任意子 skill 的产物都能映射为 `NewsEvent`。
4. 文件事件目录能支持多 Agent 交接和人工审阅。
5. 意大利样板可以覆盖重大新闻、在意国际组织发布、涉华议题三类场景。
6. 自动化边界明确停在草稿和 reviewed 文件，不进入自动对外发布。

---

## 10. 后续文档

本总纲下挂三份子规格：

1. [RSS/API采集子Skill规格](./RSS-API采集子Skill规格.md)
2. [OpenCLI采集子Skill规格](./OpenCLI采集子Skill规格.md)
3. [社媒登录态KOL追踪子Skill规格](./社媒登录态KOL追踪子Skill规格.md)
