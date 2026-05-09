# News Sentry 通用内核与平台化架构 PRD

> 版本: v0.1-draft | 日期: 2026-05-09
> 状态: 中长期产品与架构规划
> 使用方法: 本文档用于统一 News Sentry 的宏观概念、平台边界、工程路线和成功标准。它不替代具体子 Skill 规格，而是为后续内核、配置、工具、Skill、sandbox、AI Provider 等模块的实现提供产品级 source of truth。
> 前置文档: [架构总览](../architecture-overview.md) | [Integration Protocol](../integration-protocol.md) | [NewsEvent Schema](../newsevent-schema.md) | [Agent Skill Pack 总纲](./AgentSkillPack开发总纲与多Agent生产线路线图.md)

---

## 1. Executive Summary

News Sentry 要建设的是一套面向驻外新闻机构、记者站和研究团队的 **可配置 Agent Skill 平台**，而不是单一国家或单一数据源的新闻爬虫。我们将开发一个框架无关的通用内核，将目标国家配置、工具适配、Skill Registry、sandbox 执行环境、AI Provider、文件事件协议和长期记忆统一到稳定架构中，使 Hermes Agent、Codex、OpenClaw 等心跳型 Agent 框架都能以薄适配方式调用同一套能力。长期目标是让团队可以通过配置快速创建“意大利版”“法国版”“涉华议题版”等新闻监控 Skill Pack，并在可审计、可降级、可扩展的环境中持续运行。

---

## 2. Problem Statement

### Who has this problem?

主要用户是：

1. 大型新闻媒体集团的驻外机构、记者站和国际部编辑。
2. 需要 24 小时跟踪目标国家/地区/议题的研究团队。
3. 需要把 Agent 自动化能力产品化、复用化的工程团队。

### What is the problem?

当前项目已有大量关于意大利 breaking news、NewsEvent、Integration Protocol、RSS/API、OpenCLI、社媒 KOL、Agent Skill 生态的设计，但这些能力仍分散在不同文档中。若直接进入实现，会出现几个系统性问题：

1. **内核边界不清**：哪些属于通用 runtime，哪些属于国家配置，哪些属于具体 Skill，容易混在一起。
2. **配置模型不统一**：TargetConfig、SourceChannel、KOLRegistry、OutputPolicy、ProviderConfig 各自生长，后续难以迁移国家模板。
3. **工具与 Skill 边界不清**：OpenCLI、RSS、浏览器、MCP、外部 CLI、Agent Skill 的接入方式不同，需要统一包装层。
4. **sandbox 与权限策略缺失**：长期运行的 Agent 会调用终端、浏览器、外部 API、文件系统和登录态工具，必须有明确权限模型。
5. **AI Provider 不可替换**：研判、翻译、摘要、草稿生成都依赖模型，如果 Provider 抽象不足，会导致成本、可用性和质量不可控。
6. **中长期路线容易漂移**：如果没有宏观 PRD，短期 demo 会压过平台化建设，导致后续重构成本上升。

### Why is it painful?

对产品和工程的影响：

1. 一个国家样板跑通后，难以复制到第二个国家。
2. 新采集工具或新模型接入时，需要修改多处流程。
3. 登录态社媒、OpenCLI、浏览器自动化等高风险能力缺少统一治理。
4. 多 Agent 之间通过文件交接，但缺少生命周期、锁、审计和失败恢复策略。
5. 系统越运行越依赖隐式约定，后续无法稳定交给其他 Agent 或工程师维护。

### Evidence

现有项目文档已经暴露出这些需要收束的概念：

| 现有文档 | 已有基础 | 仍需补齐 |
|----------|----------|----------|
| `architecture-overview.md` | Pipeline、Skill Registry、Adaptation Layer | 通用内核和平台模块分层 |
| `integration-protocol.md` | SkillManifest、NewsEvent、PipelineContext | Provider、sandbox、runtime adapter 统一契约 |
| `newsevent-schema.md` | 数据交换模型 | 文件状态、任务状态、审计状态与 schema 的边界 |
| `AgentSkillPack开发总纲...md` | 框架无关 Skill Pack 与文件事件协议 | 长期平台化路线和模块职责 |
| 三份采集子规格 | RSS/API、OpenCLI、社媒/KOL | 统一工具接入和权限治理 |

---

## 3. Target Users & Personas

### Primary Persona: 驻外新闻监控负责人

- **角色**：国际部编辑、驻外记者站负责人、区域新闻产品负责人
- **目标**：持续发现目标地区的重大新闻、权威发布和涉华舆情线索
- **痛点**：人工值守成本高，信源分散，突发事件发现滞后，草稿整理耗时
- **成功体验**：通过配置选择目标国家和关注领域后，系统能稳定产出可审阅线索、简报和草稿

### Secondary Persona: Agent 工程负责人

- **角色**：负责把新闻监控流程产品化的工程师或 Agent 平台开发者
- **目标**：让采集、过滤、研判、输出能力可复用、可测试、可降级
- **痛点**：不同 Agent 框架、模型 Provider、工具链和浏览器自动化能力接口不一致
- **成功体验**：新增一个工具、Provider 或国家配置时，只需接入标准接口，不破坏核心 pipeline

### Secondary Persona: 事实核查与内审编辑

- **角色**：审核 Agent 草稿、判断是否可以进入正式报道或推送的人
- **目标**：快速确认来源、证据链、研判理由和风险标签
- **痛点**：自动生成内容如果没有清晰来源和处理记录，无法信任
- **成功体验**：每个事件文件都保留来源链接、处理历史、模型输出、人工/Agent 审核状态和归档原因

### Jobs-to-be-done

1. 当我需要监控一个新国家时，我想用配置创建目标模板，而不是复制修改代码。
2. 当我需要接入新工具时，我想通过 Tool Adapter 注册能力，而不是改动主流程。
3. 当我需要切换模型时，我想更换 AI Provider 配置，而不是重写 prompt 和调用逻辑。
4. 当 Agent 要执行高风险操作时，我想通过 sandbox 和权限策略限制它能做什么。
5. 当系统出错时，我想从文件、日志和 memory 中恢复上下文，而不是丢失状态。

---

## 4. Strategic Context

### Business Goals

1. **从样板项目走向可复用产品**：意大利样板只是第一个 target package，长期要支持多国家、多语言、多议题。
2. **降低持续监控成本**：通过心跳型 Agent 和确定性工具减少人工轮询和重复整理。
3. **提升新闻发现速度与质量**：将低风险结构化源、OpenCLI 深度源、社媒/KOL 早期信号统一进入研判链。
4. **保持人类可审阅和可追责**：自动化停在草稿和 reviewed 状态，正式发布由人工确认。

### Why Now?

项目已经完成了数据模型、集成协议、信息获取链、KOL 管理、采集子规格等初步设计。现在如果不补齐通用内核、配置、工具、sandbox、AI Provider 的宏观规划，后续很容易在第一版实现中把意大利样板逻辑写进核心代码，导致平台化目标落空。

### Competitive/Reference Context

现有参考项目提供了局部能力：

| 参考方向 | 可借鉴能力 | News Sentry 需要补齐 |
|----------|------------|----------------------|
| TrendRadar | RSS、简报、推送、多渠道通知 | 国家模板化、NewsEvent、专业新闻研判 |
| BettaFish | 多 Agent 分析、报告模板、舆情研判 | 轻量化、心跳式、驻外新闻场景 |
| OpenCLI | 确定性网站/社媒适配器 | Tool Adapter、sandbox、健康检查 |
| Agent Skill 生态 | 可复用 Skill、MCP 工具 | Registry、能力评分、适配治理 |

---

## 5. Solution Overview

### 5.1 产品形态

News Sentry 将演进为一个 **Agent Skill Pack Platform**。它由通用内核和可替换扩展层组成：

```text
Host Agent Framework
  Hermes Agent / Codex / OpenClaw / other heartbeat agent
    |
    v
Runtime Adapter Layer
  framework adapter / heartbeat adapter / context adapter
    |
    v
News Sentry Core Kernel
  run lifecycle / pipeline orchestration / state manager / policy engine
    |
    +--> Configuration Layer
    |      TargetConfig / SourceChannel / OutputPolicy / ProviderConfig / SandboxPolicy
    |
    +--> Skill & Tool Layer
    |      Skill Registry / Tool Registry / Tool Adapter / Capability Manifest
    |
    +--> Execution & Sandbox Layer
    |      permissions / cwd / env / network / browser session / command budget
    |
    +--> AI Provider Layer
    |      model routing / cost budget / fallback / prompt contract / eval logs
    |
    +--> Data & Memory Layer
           NewsEvent / PipelineContext / file events / run logs / long-term memory
```

### 5.2 核心模块

#### Core Kernel

通用内核负责一次 bounded run 的生命周期：

1. 加载配置和 memory。
2. 选择本轮应执行的 SourceChannel 或 Agent role。
3. 调用采集、过滤、研判、输出子 Skill。
4. 应用权限、预算、降级和失败策略。
5. 写入 NewsEvent、run log 和 memory。

通用内核不包含任何意大利硬编码、不直接保存平台账号凭据、不直接依赖某个 AI Provider。

#### Configuration Layer

配置层负责描述“系统应该做什么”，不是“代码怎么写”。v1 需要将以下配置对象稳定下来：

| 配置对象 | 说明 |
|----------|------|
| `TargetConfig` | 目标国家/地区/领域、语言、时区、关注主题、阈值 |
| `SourceChannel` | 信源、采集方式、字段映射、频率、降级 |
| `KOLRegistry` | 人物/机构追踪对象、平台账号、观察期、剪枝状态 |
| `FilterRules` | 关键词、实体、来源可信度、突发事件规则 |
| `OutputPolicy` | 文件目录、草稿策略、推送策略、归档策略 |
| `ProviderConfig` | AI 模型、用途、预算、fallback、质量策略 |
| `SandboxPolicy` | 命令、网络、文件、浏览器、凭据权限 |
| `ToolManifest` | 工具能力、输入输出、风险等级、健康检查 |
| `SkillManifest` | 子 Skill 能力、pipeline stage、运行约束 |

#### Skill & Tool Layer

Skill 是可被编排器调用的业务能力，Tool 是 Skill 内部使用或直接被内核调用的外部能力。二者需要明确分层：

| 类型 | 示例 | 责任 |
|------|------|------|
| Skill | `rss-api-collector`, `news-value-judge`, `draft-writer` | 消费/产出 NewsEvent，完成业务阶段 |
| Tool | `opencli`, `feedparser`, `browser`, `ffmpeg`, `MCP tool` | 提供具体执行能力 |
| Adapter | `opencli-wrapper`, `rss-parser-adapter`, `provider-router` | 把外部工具适配为统一契约 |

#### Execution & Sandbox Layer

sandbox 层负责限制 Agent 能做什么：

1. 命令白名单或风险分级。
2. 工作目录和输出目录边界。
3. 网络访问策略。
4. 浏览器 profile 和登录态使用策略。
5. API key 和凭据注入方式。
6. 每次心跳的执行时间、命令数、请求数、模型调用预算。

#### AI Provider Layer

AI Provider 层负责将不同模型供应商抽象为用途驱动接口：

| 用途 | 质量要求 | 成本策略 |
|------|----------|----------|
| 翻译 | 稳定、保真、多语言 | 可批量、低成本 |
| 过滤分类 | 快速、一致 | 优先小模型或规则 |
| 新闻价值研判 | 高质量、可解释 | 中高模型，限制条数 |
| 事实核查辅助 | 谨慎、引用来源 | 高质量模型，多源输入 |
| 草稿生成 | 风格可控、结构清楚 | 中高模型，保留审阅 |
| KOL/舆情分析 | 观点/事实分离 | 高风险内容加 guardrail |

Provider 不能只按供应商命名，而要按任务路由，例如 `judge.primary`、`translate.fast`、`draft.editorial`、`fallback.local`。

#### Data & Memory Layer

数据层沿用现有 `NewsEvent` 和 `PipelineContext`，并补充文件事件、长期 memory 和运行日志：

```text
raw/         collected events
evaluated/   filtered and judged events
drafts/      editorial drafts
reviewed/    review candidates
published/   approved archive or publish-ready files
archive/     rejected, duplicate, low-value, failed samples
memory/      known ids, source health, provider stats, KOL states
logs/        bounded run logs and error reports
```

---

## 6. Success Metrics

### Primary Metric

**国家模板复用效率**：新增一个目标国家配置并跑通 RSS/API 基线监控的工程时间。

- 当前：需要重新分析和手动拼接文档方案
- v1 目标：1-2 天内完成新国家最小配置
- v2 目标：半天内完成新国家基础配置并进入试运行

### Secondary Metrics

| 指标 | 目标 |
|------|------|
| SourceChannel 可用率 | P0 源 7 日成功率 >= 95% |
| NewsEvent schema 合规率 | 新写入事件 >= 99% 满足最低字段 |
| Tool Adapter 失败可解释率 | 失败都有 error type、source、suggested action |
| Provider 可替换性 | 同一 judge 任务可在至少 2 个 Provider 间切换 |
| 草稿可审阅率 | 高价值事件草稿 100% 保留来源链接和研判理由 |
| 自动发布事故 | v1 必须为 0，因为不允许自动发布 |

### Guardrail Metrics

1. LLM 成本不能随采集量线性失控，必须受 `llm_budget_remaining` 和优先级队列限制。
2. 登录态工具不能在未授权 profile 上运行。
3. 低价值重复事件不能持续进入草稿目录。
4. 文件事件协议不能绕过 `NewsEvent.pipeline_stage` 和处理历史。

---

## 7. User Stories & Requirements

### Epic Hypothesis

我们相信，建设框架无关的 News Sentry 通用内核和平台化配置体系，可以让团队从单一意大利样板扩展到多国家、多领域新闻监控，因为核心能力、工具接入、AI Provider 和 sandbox 策略都被稳定抽象。成功将通过新增国家配置时间、采集稳定性、模型可替换性和审计完整性衡量。

### Story 1: 作为驻外新闻监控负责人，我可以创建目标国家配置

**Acceptance Criteria:**

- [ ] `TargetConfig` 可以声明国家、语言、时区、关注领域和优先级阈值。
- [ ] `SourceChannel[]` 可以声明 RSS/API、OpenCLI、社媒/KOL 等不同采集方式。
- [ ] 配置中不包含核心代码逻辑。
- [ ] 意大利样板可以作为第一个 reference package。

### Story 2: 作为 Agent 工程师，我可以通过统一内核运行一次心跳

**Acceptance Criteria:**

- [ ] 每次 run 都有 `run_id`、输入配置、输出摘要和错误记录。
- [ ] bounded run 完成后退出，不在 Skill Pack 内部无限循环。
- [ ] 宿主框架只需要调用 adapter，不需要理解采集细节。
- [ ] run 失败时保留 memory 和日志，下一次心跳可以恢复。

### Story 3: 作为工具开发者，我可以接入新工具而不改主流程

**Acceptance Criteria:**

- [ ] 工具通过 `ToolManifest` 声明能力、输入输出、风险等级和健康检查。
- [ ] Tool Adapter 把外部输出映射为 `NewsEvent` 或结构化中间结果。
- [ ] 工具失败时有标准错误类型和降级策略。
- [ ] OpenCLI、RSS parser、浏览器/MCP 工具可以共享同一接入思想。

### Story 4: 作为平台维护者，我可以控制 sandbox 权限

**Acceptance Criteria:**

- [ ] 每个工具或 Skill 有权限等级。
- [ ] 高风险能力必须声明文件、网络、浏览器、凭据访问需求。
- [ ] 社媒登录态和浏览器 profile 使用必须可审计。
- [ ] 遇到验证码、封禁、权限异常时自动停止重试。

### Story 5: 作为编辑，我可以信任 AI Provider 输出的可审计性

**Acceptance Criteria:**

- [ ] 每次模型调用记录用途、Provider、模型、输入摘要、输出文件和成本估算。
- [ ] 研判结果保留 reasoning、confidence、source links。
- [ ] Provider 可按任务切换，不影响 NewsEvent schema。
- [ ] 高风险判断必须有 fallback 或人工确认路径。

### Story 6: 作为内审编辑，我可以追溯事件从采集到草稿的全过程

**Acceptance Criteria:**

- [ ] 每个事件保留 `processing_history`。
- [ ] 文件目录状态和 `pipeline_stage` 的关系有明确说明。
- [ ] 被归档或打回的事件不删除，只补充原因。
- [ ] 草稿文件必须包含来源链接、摘要、研判理由和风险提示。

---

## 8. Out of Scope

v1 不包含：

1. **自动对外发布**：只产出草稿、reviewed 文件和 publish-ready 归档。
2. **完整多租户 SaaS 平台**：先做本地/仓库驱动的 Skill Pack，不做用户、计费、权限后台。
3. **全量国家配置市场**：只提供意大利 reference package 和国家模板能力。
4. **全量社媒生产化**：社媒登录态/KOL 是高价值实验通道，不作为 v1 稳定性基线。
5. **强数据库依赖**：文件事件和 memory 优先，数据库作为后续检索和任务队列增强。
6. **模型微调平台**：Provider 层先做路由和替换，不做训练基础设施。
7. **绕平台限制的数据采集**：不绕过登录墙、验证码、付费墙、私人内容权限。

---

## 9. Dependencies & Risks

### Technical Dependencies

| 依赖 | 说明 |
|------|------|
| NewsEvent Schema | 所有 Skill 和 Tool 输出必须能映射到 NewsEvent |
| Integration Protocol | SkillManifest、PipelineContext、降级策略的基础 |
| Agent Skill Pack 总纲 | 框架无关 bounded run 和文件事件协议 |
| RSS/API 子规格 | 低风险采集基线 |
| OpenCLI 子规格 | 工具适配和确定性网页/命令采集 |
| 社媒/KOL 子规格 | 高风险登录态和 KOL registry 管理 |

### Risks & Mitigations

| 风险 | 影响 | 缓解 |
|------|------|------|
| 抽象过度 | 迟迟不能落地 | 以意大利 reference package 驱动内核接口 |
| 抽象不足 | 第二国家迁移返工 | 配置对象不允许写死国家逻辑 |
| Provider 绑定 | 成本和可用性风险 | 用用途驱动 ProviderConfig 和 fallback |
| sandbox 缺失 | 高风险工具失控 | 先定义权限策略，再开放登录态工具 |
| 文件协议混乱 | 多 Agent 交接不可靠 | 目录状态和 `pipeline_stage` 分离说明 |
| 工具失败不可诊断 | 长期运行不稳定 | ToolManifest + health record + run log |
| 自动化越界 | 发布或合规事故 | v1 明确停在草稿和 reviewed |

---

## 10. Open Questions

1. `ToolManifest` 是否单独成文，还是并入 `SkillManifest` 作为一种 capability 类型？
2. sandbox v1 是配置约束还是需要实际执行隔离，例如容器、工作目录沙箱、profile 沙箱？
3. AI Provider 是否需要统一 prompt registry，以便 Provider 切换时保持输出结构一致？
4. 文件事件协议在并发 Agent 下是否需要 lock 文件或 lease 机制？
5. 长期 memory 是继续使用 Markdown/YAML 文件，还是在 v2 引入 SQLite？
6. Skill Pack 的最小 CLI 入口如何命名，是否需要统一为 `news-sentry run --target italy --stage collect`？
7. Provider 成本和质量如何评估，是否需要离线 eval 集？

---

## 11. Roadmap

### Phase 0: Contract Stabilization

目标：把核心概念定稿，避免实现阶段边界漂移。

交付：

1. 本 PRD。
2. `NewsEvent`、`PipelineContext`、`TargetConfig`、`SourceChannel` 的 canonical 字段和量纲定稿。
3. `ToolManifest`、`ProviderConfig`、`SandboxPolicy` 草案。
4. 文件事件协议与 `pipeline_stage` 的分离规则。
5. SourceChannel 不直接保存可执行 shell 命令的约束。

成功标准：实现者不需要再决定 ID、字段别名、分数量纲、provenance、country 语义或最小 sandbox 边界。

### Phase 1: Kernel MVP

目标：跑通文件事件和 bounded run。

交付：

1. 通用 run lifecycle。
2. 配置加载器。
3. 文件事件 writer。
4. run log 和 memory writer。
5. RSS/API collector 接入。
6. 最小 sandbox enforcer：命令/工具 allowlist、文件边界、网络 host 记录、预算限制、审计日志。

成功标准：意大利 reference package 能稳定产生 `raw/` 和 `evaluated/` 事件。

### Phase 2: Tool & Skill Registry

目标：工具和子 Skill 可注册、可选择、可降级。

交付：

1. SkillManifest registry。
2. ToolManifest registry。
3. OpenCLI Tool Adapter，采用 `tool_ref + binding_id + validated_args`。
4. source health 和 adapter health。
5. 手动检查队列。

成功标准：OpenCLI 和 RSS/API 可作为同一 SourceChannel 体系下的不同 acquisition method 运行。

### Phase 3: AI Provider Layer

目标：研判、翻译、摘要和草稿生成不绑定单一 Provider。

交付：

1. ProviderConfig。
2. task-based routing。
3. cost budget。
4. fallback provider。
5. prompt/output contract。

成功标准：同一 judge 任务可在至少两个 Provider 间切换，输出仍满足 NewsEvent/JudgeResult 结构。

### Phase 4: Sandbox & Risk Governance

目标：在 Phase 1 的最小 enforcer 基础上强化高风险工具治理。

交付：

1. 完整 SandboxPolicy。
2. command/network/browser/profile 权限模型强化。
3. 登录态使用审计。
4. stop-on-risk 机制。
5. 社媒/KOL 实验通道。

成功标准：社媒/KOL 小规模试运行时，所有登录态使用都有 session profile、授权标记和失败停止策略。

### Phase 5: Multi-target Expansion

目标：证明平台可复制。

交付：

1. 第二国家 reference package。
2. 跨国家配置差异文档。
3. 多语言 Provider 策略。
4. 复用率和迁移成本评估。

成功标准：新国家不修改核心内核即可跑通 RSS/API 基线监控。

---

## 12. Decision Log

| 决策 | 结论 | 原因 |
|------|------|------|
| 产品形态 | Agent Skill Pack Platform | 比单一 demo 更能支撑多国家复用 |
| 核心架构 | 框架无关内核 + 薄 runtime adapter | 兼容 Hermes/Codex/OpenClaw |
| 状态存储 | Obsidian + Git 文件优先 | 人类可审阅、协作和审计友好 |
| 数据模型 | NewsEvent + PipelineContext | 已有协议基础，降低分裂风险 |
| 工具接入 | Tool Adapter + ToolManifest | 统一 OpenCLI/RSS/MCP/浏览器等能力 |
| 模型接入 | task-based AI Provider routing | 控制成本、质量和 fallback |
| 安全边界 | sandbox policy 前置 | 长期运行 Agent 必须可控 |
| 自动化边界 | 到草稿和 reviewed 为止 | 避免自动发布风险 |

---

## 13. Next Documents

建议接下来补三份架构规格，作为本 PRD 的工程承接：

1. [ToolManifest与工具适配层规格](./ToolManifest与工具适配层规格.md)
2. [AIProvider与模型路由规格](./AIProvider与模型路由规格.md)
3. [SandboxPolicy与执行权限规格](./SandboxPolicy与执行权限规格.md)

这三份文档完成后，再进入内核实现计划。
