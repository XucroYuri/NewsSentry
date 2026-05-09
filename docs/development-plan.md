# News Sentry — 开发计划

> 版本: v1.0 | 日期: 2026-05-09
> 状态: **路线图主权文档** — 本文档是七阶段开发计划与 TODO 矩阵的唯一权威来源
> 字段口径基准: [`docs/contracts-canonical.md`](./contracts-canonical.md)
> 架构决策: [`docs/adr/README.md`](./adr/README.md)
> 历史背景: [`docs/brainstorming/AgentSkillPack开发总纲与多Agent生产线路线图.md`](./brainstorming/AgentSkillPack开发总纲与多Agent生产线路线图.md)（历史脉络文档）

---

## §0. 反思与判断基础（四张清单）

> 本节记录本轮规划的取舍判断，实现者应先理解这四张清单，再参考后续 TODO 矩阵。

### 保留（不改变，继续沿用）

- `AGENTS.md` 的七阶段次序（Phase 1–7）
- Bounded run 设计：宿主触发，Skill Pack 不实现无界 daemon
- `NewsEvent` + `PipelineContext` + `SkillManifest` 三层契约
- 文件事件目录协议（`raw/evaluated/drafts/reviewed/published/archive/memory/logs/`）
- Hermes/OpenClaw 优先级（Hermes 主编排，OpenClaw Skill 生态，Codex/Claude Cowork 仅备用）
- 五类敏感数据禁入条款（cookies、tokens、passwords、browser profiles、API keys）
- 从草稿到 reviewed 为止，v1 不实现自动外发

### 改写（已在本轮修正）

- `pipeline_stage` 命名漂移 → 统一过去分词（`collected/filtered/judged/outputted`）
- `NewsEvent.id` 三种写法 → 统一为 `ne-{target_id}-{source_id}-{yyyymmdd}-{hash8}`
- `output_channels` 字段 → 对齐为 `output_result.destinations[].target`
- SandboxPolicy YAML `write_roots` → 补充 `reviewed/` 和 `published/`
- `ToolRunResult.error.type` → 补充 `args_invalid` 等缺失枚举
- 产品名大小写 → `News Sentry`（文章）/ `news-sentry`（包名/命令）

### 推迟（明确写入 Phase 6+，不在 v1 主线）

- `kol-tracking` 全量 KOL 矩阵、多账号 session 池、邮件/微信反向信源
- `information-acquisition-chains` L3 多源交叉、动态 Skill registry、复杂 provider 调度
- 社媒生产化通道（只做 Phase 6 小规模实验）

### 舍弃（v1 不引入，写明"非缺陷"）

- 数据库队列（v1 文件 memory 为主）
- 自动对外发布（停在草稿/reviewed）
- 未审计社区 Skill 直入生产
- 无界 daemon 循环
- `Codex/Claude Cowork` 承担 24h 主监控

---

## §1. 七阶段总览

| Phase | 名称 | 核心目标 | 估算规模 |
|-------|------|---------|---------|
| Phase 1 | Contract Stabilization | 定稿所有核心契约和文档，消除口径漂移 | S（已基本完成） |
| Phase 2 | Runtime Carrier Alignment | Hermes/OpenClaw adapter、bounded run 协议定稿 | M |
| Phase 3 | Kernel MVP | RSS/API 基线、bounded run、文件事件、source health、最小 sandbox | L |
| Phase 4 | Tool/Skill Registry + OpenCLI | SkillManifest/ToolManifest registry、OpenCLI 接入 | L |
| Phase 5 | AI Provider Routing | task-based 路由、多 Provider、prompt/output schema、成本预算 | L |
| Phase 6 | Sandbox Hardening + Social/KOL Experiment | 权限模型强化、社媒/KOL 小规模实验通道 | M |
| Phase 7 | Multi-target Expansion | 第二国家 reference package，验证核心无意大利硬编码 | M |

---

## §2. Phase 1 — Contract Stabilization

> → 详细 SPEC: [docs/spec/phase-1-contract-stabilization.md](spec/phase-1-contract-stabilization.md)

**目标：** 定稿所有核心契约、消除跨文档口径漂移、关闭已答 Open Questions。

**入口标准：** 项目存在设计文档但多处口径不一致，需在实现前统一。

**出口标准：** 实现者不需要再决定 ID 格式、字段别名、分数量纲、provenance、pipeline_stage 形式或最小 sandbox 边界。

**范围内（IN SCOPE）：**
- 创建 `docs/contracts-canonical.md`（口径基准）
- 创建 `docs/adr/` 目录（ADR-0001 至 ADR-0007）
- 精修 `AGENTS.md`、`architecture-overview.md`、`integration-protocol.md`、`newsevent-schema.md`
- 精修 `SandboxPolicy与执行权限规格.md`、`通用内核与平台化架构PRD.md`
- 为采集子 Skill 规格加阶段标签
- 为超 v1 范围文档加 banner
- 创建 `docs/it-zh-bilingual-sop.md` 和 `docs/it-zh-glossary.md`
- 创建本文档（`docs/development-plan.md`）

**范围外（OUT OF SCOPE）：**
- 任何代码实现
- ToolManifest / AIProvider 规格新内容（只更新引用）
- 新的数据采集或测试

**验收清单：**

- [ ] `contracts-canonical.md` 覆盖全部 6 类口径漂移，并有 §7 修正记录表
- [ ] `docs/adr/` 含 ADR-0001 至 ADR-0007，README 有完整索引
- [ ] `AGENTS.md` 引用 `contracts-canonical.md` 和双语 SOP
- [ ] `newsevent-schema.md §待讨论` 第 4、5 条标注 RESOLVED
- [ ] `SandboxPolicy YAML` `write_roots` 含 `reviewed/` 和 `published/`
- [ ] 三类采集子 Skill 规格头部均有阶段标签
- [ ] `kol-tracking.md`、`information-acquisition-chains.md` 含超 v1 范围 banner
- [ ] `it-zh-bilingual-sop.md` 覆盖翻译时机、三层粒度、术语策略、草稿模板、合规免责
- [ ] `it-zh-glossary.md` 含七张种子表

**风险与回退：**
- 风险：后续文档被直接修改而不走 ADR，导致口径再次漂移
- 回退：任何争议查 `contracts-canonical.md §7`，修改必须新建 ADR

---

## §3. Phase 2 — Runtime Carrier Alignment

> → 详细 SPEC: [docs/spec/phase-2-runtime-carrier-alignment.md](spec/phase-2-runtime-carrier-alignment.md)

**目标：** 定稿生产运行载体优先级和部署 profile，避免实现阶段把开发工具和生产运行框架混为一谈。

**入口标准：** Phase 1 完成，核心契约已定稿。

**出口标准：** 实现者清楚知道 Hermes 承接长期生产调度、OpenClaw 承接 Skill 生态和兼容运行、Codex/Claude Cowork 不作为 24h 主监控。

**范围内：**
- `RuntimeHostAdapter` 最小约定文档（可能更新 `Hermes与OpenClaw运行载体规格.md`）
- `cloud-vps` 和 `local-workstation` 两套部署 profile 定义
- bounded run 入口协议（触发方式、环境注入、产物读取）
- Codex Automations / Claude Cowork fallback 边界确认

**范围外：**
- Hermes 内部 API 实现
- OpenClaw 内部 Skill registry 实现
- 任何采集或研判 Skill 的代码

**验收清单：**

- [ ] `RuntimeHostAdapter` 接口定义（输入：run 触发参数 + 配置路径；输出：bounded run 结果摘要 + 错误码）
- [ ] `cloud-vps` profile 定义（cwd、写入目录路径、网络限制、cron 触发方式）
- [ ] `local-workstation` profile 定义（同上，适配本地开发和 Claude Cowork fallback）
- [ ] `Hermes与OpenClaw运行载体规格.md` 更新：引用 `contracts-canonical.md`，补充 fallback automation 边界说明

**风险与回退：**
- 风险：Hermes 或 OpenClaw 内部 API 变动导致 adapter 需频繁修改
- 回退：薄 adapter 原则，只依赖稳定的触发接口，不依赖框架内部 memory

---

## §4. Phase 3 — Kernel MVP

> → 详细 SPEC: [docs/spec/phase-3-kernel-mvp.md](spec/phase-3-kernel-mvp.md)

**目标：** 跑通文件事件闭环和 bounded run，产出意大利样板的 `raw/` 和 `evaluated/` 事件。

**入口标准：** Phase 2 完成，运行载体对齐，契约定稿。

**出口标准：** 意大利 reference package 能稳定产出 `raw/` 和 `evaluated/` 事件，有 run log、memory、source health 记录，最小 sandbox enforcer 运行。

**范围内（仅 v1 主线）：**
- 框架无关 run lifecycle（加载配置 → 运行各阶段 → 写入文件 → 退出）
- 配置加载器（`TargetConfig`、`SourceChannel`、`FilterRules`、`SandboxPolicy` 最小子集）
- 文件事件 writer（`raw/`、`evaluated/`、`archive/`、`memory/`、`logs/`）
- RSS/API collector 接入（基于 `RSS-API采集子Skill规格.md`）
- 规则过滤（关键词、实体、来源可信度、去重）
- run log writer 和 source health 记录
- 最小 sandbox enforcer（命令白名单、文件边界校验、网络 host 记录、预算限制、审计日志）

**范围外（不进 Kernel MVP）：**
- OpenCLI（Phase 4）
- 社媒登录态（Phase 6）
- 动态 registry（Phase 4）
- 复杂 provider 路由（Phase 5）
- 多 Provider 并发（Phase 5）

**关键依赖（实现前须读）：**
- `docs/brainstorming/RSS-API采集子Skill规格.md`
- `docs/brainstorming/通用内核与平台化架构PRD.md §5.2 Core Kernel`
- `docs/contracts-canonical.md`（字段规范）

**验收清单：**

- [ ] 一次 bounded run 触发后能产出至少一个 `raw/ne-italy-*.md` 文件
- [ ] 文件 frontmatter 字段符合 `contracts-canonical.md §3`（id 格式正确）
- [ ] `pipeline_stage` 字段值符合 `contracts-canonical.md §2`（`collected`）
- [ ] 过滤后事件进入 `evaluated/`，被拒事件进入 `archive/`
- [ ] `logs/` 产出 run log，含 `run_id`、`started_at`、`events_collected`、`events_filtered`
- [ ] `memory/` 更新 `known_item_ids`（用于去重）
- [ ] source health 记录在 `memory/source_health.yaml`
- [ ] sandbox enforcer 拒绝未注册工具执行，违规写入安全日志
- [ ] 运行时不实现无界 daemon 循环（run 完成后退出）

**风险与回退：**
- 风险：RSS 信源格式不一致，解析失败
- 回退：adapter 内置多种 RSS 格式解析，失败时写入 `archive/` 带 `acquisition.method=builtin_fallback`
- 风险：文件名冲突（多次 run 处理相同 URL）
- 回退：`id` 的确定性哈希保证同 URL 同天生成相同 id，enforcer 检查 `known_item_ids` 跳过已知

---

## §5. Phase 4 — Tool/Skill Registry + OpenCLI

> → 详细 SPEC: [docs/spec/phase-4-tool-skill-registry-opencli.md](spec/phase-4-tool-skill-registry-opencli.md)

**目标：** 工具和子 Skill 可注册、可选择、可降级；OpenCLI 通过统一接入接入 pipeline。

**入口标准：** Phase 3 完成，RSS/API baseline 稳定运行。

**出口标准：** OpenCLI 和 RSS/API 可作为同一 `SourceChannel` 体系下的不同 acquisition method 运行。

**范围内：**
- `SkillManifest` registry（注册、查询、降级选择）
- `ToolManifest` registry（注册、健康检查、能力声明）
- OpenCLI Tool Adapter（`tool_ref + binding_id + validated_args`）
- source health 和 adapter health 追踪
- 手动检查队列（sandbox violation 进入）

**范围外（不进 Phase 4）：**
- 社媒登录态（Phase 6）
- AI Provider 路由（Phase 5）
- 第二国家配置（Phase 7）

**关键依赖（实现前须读）：**
- `docs/brainstorming/OpenCLI采集子Skill规格.md`
- `docs/brainstorming/ToolManifest与工具适配层规格.md`
- `docs/contracts-canonical.md §2`（`SkillManifest.pipeline_stage` 用动词原形）

**验收清单：**

- [ ] 一个 OpenCLI 采集工具可通过 `tool_ref + binding_id + validated_args` 调用，产出 `NewsEvent`
- [ ] `SourceChannel` 配置中不包含任意 shell 命令
- [ ] `ToolManifest` 注册失败（tool_not_found）写入标准 error.type
- [ ] source health 追踪工具失败率和最近健康状态
- [ ] adapter health check 可在 bounded run 前验证工具可用性
- [ ] 依据 ADR-0011 落地 OpenCLI baseline ToolManifest 12 条（`config/toolmanifest/opencli-baseline.yaml`）
- [ ] 所有 OpenCLI 工具退出码按 ADR-0011 §退出码映射对齐 `ToolRunResult.error.type`
- [ ] 无任何 `SourceChannel` 配置包含 fork/vendor/submodule 引用（符合 ADR-0008）

**风险与回退：**
- 风险：OpenCLI adapter 与意大利网站结构频繁变化
- 回退：adapter 健康检查每次 run 前执行，失败降级到 RSS/API 同等信源

---

## §6. Phase 5 — AI Provider Routing

> → 详细 SPEC: [docs/spec/phase-5-ai-provider-routing.md](spec/phase-5-ai-provider-routing.md)

**目标：** 研判、翻译、摘要和草稿生成不绑定单一 Provider，按任务路由，有成本预算和 fallback。

**入口标准：** Phase 4 完成，Skill registry 稳定。

**出口标准：** 同一 judge 任务可在至少两个 Provider 间切换，输出仍满足 `NewsEvent/JudgeResult` 结构。

**范围内：**
- `ProviderConfig`（`route_id`、primary/fallback model、cost budget、output_schema_id）
- task-based routing（`translate.fast`、`translate.high`、`judge.primary`、`draft.editorial`、`fallback.local`）
- cost budget 追踪和软硬限制
- prompt/output schema 注册（与 `route_id` 绑定）
- Provider 切换测试（同 judge 任务在两个 Provider 间切换，输出结构验证）
- 双语翻译 canonical 路由（实现 ADR-0004 的 `translate.high` 路由）

**范围外：**
- 离线 eval 集（治理 backlog EVAL-001）
- 模型微调
- 社媒/KOL 相关的特殊 Provider 场景

**验收清单：**

- [ ] `judge.primary` route 可切换至少两个 Provider，输出 `JudgeResult` 结构一致
- [ ] `translate.fast` 路由在 collect 阶段成功写入 `metadata.translation.title_pre`
- [ ] `translate.high` 路由在 judge 阶段成功写入 `title_translated`（canonical）
- [ ] cost budget 超限时，超限事件降级到 `recommendation=monitor`，写入 run log
- [ ] Provider 失败 fallback 可切换到备用 Provider 或规则引擎降级

**风险与回退：**
- 风险：模型 API 变更导致 output schema 不一致
- 回退：`output_schema_id` 版本化，Provider 切换时 enforcer 验证 schema 兼容性

---

## §7. Phase 6 — Sandbox Hardening + Social/KOL Experiment

> → 详细 SPEC: [docs/spec/phase-6-sandbox-hardening-social-kol.md](spec/phase-6-sandbox-hardening-social-kol.md)

**目标：** 在 Phase 3 最小 enforcer 基础上强化高风险工具治理，小规模接入社媒/KOL 实验通道。

**入口标准：** Phase 5 完成，AI Provider 路由稳定；或 Phase 3 完成后可优先做 sandbox 强化。

**出口标准：** 社媒/KOL 小规模试运行时，所有登录态使用都有 session profile、授权标记和失败停止策略。

**范围内：**
- 完整 `SandboxPolicy` 强化（`command/network/browser/profile` 权限模型）
- 登录态使用审计（session profile 引用、auth_owner 标记）
- stop-on-risk 机制（captcha/blocked/auth_error 自动停止）
- 社媒/KOL 实验通道（小规模、授权、可审计的公开账号）
- sandbox violation 进入人工检查队列

**范围外：**
- 全量 KOL 生产化（Phase 6 只做实验通道）
- 自动登录、自动刷新 session（永远不做）
- 私密群组采集（永远不做）

**验收清单：**

- [ ] 社媒/KOL 实验运行时，所有 session profile 引用有 `auth_owner=human-approved`
- [ ] captcha/blocked/auth_error 信号触发立即停止并写入安全日志
- [ ] sandbox violation 进入人工检查队列，下次 run 时可查阅
- [ ] `memory/` 中 KOL state 记录可读，不含 cookie 或 token 值

**风险与回退：**
- 风险：社媒平台封禁实验账号
- 回退：降级到公开 RSS/API，标记受封禁源为 `source_health=blocked`，停止重试

---

## §8. Phase 7 — Multi-target Expansion

> → 详细 SPEC: [docs/spec/phase-7-multi-target-expansion.md](spec/phase-7-multi-target-expansion.md)

**目标：** 增加第二国家 reference package，证明核心内核不含意大利硬编码。

**入口标准：** Phase 3 以上完成，意大利 reference package 稳定运行。

**出口标准：** 新国家不修改核心内核即可跑通 RSS/API 基线监控。

**范围内：**
- 第二国家 reference package（配置文件、SourceChannel 列表、FilterRules、TargetConfig）
- 跨国家配置差异文档
- 核心内核无意大利硬编码验证
- 多语言 Provider 策略（第二国家的翻译/研判路由）

**范围外：**
- 第三国家（进入 v2+ 路线）
- 自动化国家模板市场
- 多租户 SaaS

**验收清单：**

- [ ] 第二国家 `TargetConfig` 配置创建后，bounded run 成功产出 `raw/` 事件，不需要修改任何核心代码
- [ ] 意大利特有的关键词/实体/人名配置全部在 `TargetConfig` 或 `SourceChannel` 中，不在核心代码里
- [ ] 第二国家 `it-{lang}-bilingual-sop.md` 或双语 SOP 扩展文档可选创建
- [ ] 用 `docs/news-classification-framework.md` 中的 L0–L3 taxonomy 评估第二国家可复用度：是否需要新增 L1 子主题？是否需要新增 `country_axes` 子轴文件？
- [ ] `metadata.classification.country_axes[]` 中意大利特定轴（`region`/`coalition`）不被第二国家配置引用（验证子轴隔离）

---

## §9. Workstream 矩阵（横切七个 Phase）

| Workstream | W1 契约与口径治理 | W2 运行载体 | W3 内核 MVP | W4 工具/Skill Registry | W5 AI Provider 路由 | W6 沙箱硬化 | W7 多 target | W8 双语 SOP | W9 文档治理 | W10 外部集成 | W11 分类框架 |
|-----------|----------|-----------|-----------|---------------------|---------------------|-----------|------------|-----------|-----------|-----------|-----------|
| **Phase 1** | ★ 核心 | — | — | — | — | — | — | ★ 核心 | ★ 核心 | ◎ 策略文档 | ◎ 框架文档 |
| **Phase 2** | ◎ 引用 | ★ 核心 | — | — | — | — | — | — | ◎ 更新 | — | — |
| **Phase 3** | ◎ 引用 | ◎ 适配 | ★ 核心 | — | — | ◎ 最小 | — | ◎ 基础 | ◎ 更新 | ◎ 数据集接入 | ◎ 规则引擎 |
| **Phase 4** | ◎ 引用 | ◎ 适配 | ◎ 扩展 | ★ 核心 | — | ◎ 扩展 | — | — | ◎ 更新 | ★ 核心 | ◎ 分类测试 |
| **Phase 5** | ◎ 引用 | — | ◎ 适配 | ◎ 适配 | ★ 核心 | ◎ 审计 | — | ★ 翻译路由 | ◎ 更新 | ◎ MCP形态 | ★ LLM分类器 |
| **Phase 6** | ◎ 引用 | — | — | ◎ 扩展 | ◎ 适配 | ★ 核心 | — | ◎ 社媒合规 | ◎ 更新 | ◎ 社媒适配 | ◎ 扩展 |
| **Phase 7** | ◎ 引用 | ◎ 适配 | ◎ 验证 | ◎ 验证 | ◎ 适配 | ◎ 适配 | ★ 核心 | ◎ 扩展 | ◎ 更新 | ◎ 新目标适配 | ★ 新子轴设计 |

图例：`★ 核心` = 此 Phase 中 workstream 的主要工作量 | `◎ 适配/引用` = 关联工作但非主角 | `—` = 本 Phase 不涉及

### W10 — 外部集成工作流（跨 Phase 1–4）

| Phase | 主要产出物 |
|---|---|
| Phase 1 | `docs/external-integration-strategy.md`（策略定稿）、`docs/reference-projects-insights.md`（参考项目提取）、ADR-0008、ADR-0011 |
| Phase 3 | `docs/datasets-catalog-italy.md` 中 Phase 3 标注数据集（ISTAT/Eurostat/GDELT）离线接入 |
| Phase 4 | `config/toolmanifest/opencli-baseline.yaml`（12 条 ADR-0011 骨架实现）；OpenCLI Tool Adapter 集成测试 |
| Phase 5+ | TrendRadar MCP server 形态（可选）；worldmonitor 数据源接入（Phase 7 候选） |

### W11 — 分类框架工作流（跨 Phase 3–7）

| Phase | 主要产出物 |
|---|---|
| Phase 1 | `docs/news-classification-framework.md`（框架定稿）、ADR-0009；`contracts-canonical.md §9` 新增 |
| Phase 3 | 规则引擎分类器（`config/classification-rules.yaml`）；`metadata.classification` 写入 collect/filter Skill |
| Phase 5 | LLM 分类器（route_id: `classify.primary`）；fallback 降级到规则引擎 |
| Phase 6 | 社媒内容分类适配（社媒文本的 L0/L1 识别率验证） |
| Phase 7 | 第二国家 `country_axes` 子轴文件设计；L1 子主题可复用度评估 |

---

## §10. TODO 颗粒度矩阵（Phase 3 Kernel MVP 示例展开）

> 每条 TODO 格式：`{phase}.{ws}.{seq} | 输出物 | 依赖 | 规模 | 验收点`

### Phase 3 · W3 内核 MVP

| ID | 内容 | 输出物 | 依赖 | 规模 | 验收点 |
|----|------|--------|------|------|--------|
| P3.W3.01 | 实现 bounded run 入口（加载配置 → 分阶段 → 退出） | `core/run.py` 或等效 | Phase 2 adapter 接口 | M | 调用后有 run_id，运行后正常退出，无 daemon |
| P3.W3.02 | 实现 `TargetConfig` 配置加载器 | `core/config.py` | `contracts-canonical.md §2` | S | 加载意大利 reference package 配置，字段符合规范 |
| P3.W3.03 | 实现 RSS/API collector adapter | `skills/rss_collector.py` | `RSS-API采集子Skill规格.md` | M | 成功从 ANSA RSS 产出 `NewsEvent(pipeline_stage=collected)` |
| P3.W3.04 | 实现文件事件 writer（`raw/`、`evaluated/`） | `core/file_writer.py` | `contracts-canonical.md §3`（id 格式） | S | 产出文件 id 格式正确，frontmatter 含必填字段 |
| P3.W3.05 | 实现规则过滤（关键词/去重） | `skills/filter.py` | `FilterRules` schema | M | 中文关键词、意语关键词匹配，known_item_ids 去重 |
| P3.W3.06 | 实现 run log writer | `core/run_log.py` | `logs/` 目录 | S | 每次 run 产出 `logs/run-{run_id}.yaml`，含统计摘要 |
| P3.W3.07 | 实现 source health 记录 | `memory/source_health.yaml` | `run log` | S | 记录每个信源的最近成功率和最近失败原因 |
| P3.W3.08 | 实现最小 sandbox enforcer | `core/sandbox.py` | `SandboxPolicy与执行权限规格.md §2` | M | 未注册工具执行被拒，违规写安全日志 |

### Phase 3 · W8 双语 SOP

| ID | 内容 | 输出物 | 依赖 | 规模 | 验收点 |
|----|------|--------|------|------|--------|
| P3.W8.01 | 在 RSS collector 中实现语种检测和标题机译 | `NewsEvent.language` 和 `metadata.translation.title_pre` | `translate.fast` route（Phase 5 前可用 mock） | S | 意大利语事件含 `language=it`，`title_pre` 非空 |
| P3.W8.02 | 实现草稿生成 Skill（基础版） | `drafts/{id}.md` | `it-zh-bilingual-sop.md §5` | M | 草稿含标准 frontmatter、30 秒摘要节，`compliance_note` 非空 |

---

## §11. 关键决策与 ADR 列表

| ADR | 决策摘要 | Phase |
|-----|---------|-------|
| [ADR-0001](./adr/0001-canonical-contracts.md) | `pipeline_stage` 枚举、`NewsEvent.id` 格式、分值量纲、产品命名 | Phase 1 |
| [ADR-0002](./adr/0002-output-result-field-alignment.md) | `output_channels` → `output_result.destinations[].target` | Phase 1 |
| [ADR-0003](./adr/0003-sandbox-write-roots-and-error-enum.md) | SandboxPolicy `write_roots` 补全、`error.type` 枚举对齐 | Phase 1 / Phase 3 |
| [ADR-0004](./adr/0004-bilingual-translation-timing.md) | collect 标题机译（非 canonical） + judge 高保真 canonical 翻译 | Phase 1 / Phase 5 |
| [ADR-0005](./adr/0005-pipeline-stage-vs-workflow-state.md) | `pipeline_stage` 与 `workflow_state` 正交分离 | Phase 1 |
| [ADR-0006](./adr/0006-cli-entry-deferred.md) | CLI 入口命名暂缓到 Phase 3 前决策 | 治理 backlog |
| [ADR-0007](./adr/0007-prd-open-questions-resolved.md) | PRD Open Questions 批量关闭 | Phase 1 |
| [ADR-0008](./adr/0008-external-deps-install-not-vendor.md) | 外部项目只 install 不 vendor；三原则：install-not-vendor、wrap-not-rewrite、document-the-version | Phase 1 / Phase 4 |
| [ADR-0009](./adr/0009-four-layer-classification-framework.md) | 四层新闻分类框架（L0–L3）与 `metadata.classification` 字段契约 | Phase 1 / Phase 3 |
| [ADR-0010](./adr/0010-no-dedicated-frontend.md) | 永不做专用前端；终态是 Obsidian + 推送 | Phase 1 |
| [ADR-0011](./adr/0011-opencli-baseline-toolmanifest.md) | OpenCLI baseline ToolManifest 12 条命令骨架；退出码映射 | Phase 4 |

---

## §12. 跨 Phase 治理 Backlog

> 不绑定具体 Phase，但必须在适当时机决策或实现。

| 编号 | 内容 | 建议决策/实现时机 |
|------|------|----------------|
| `CLI-001` | 决定 `news-sentry run` 的完整命令 schema（参数、子命令、输出格式）| Phase 3 实现前 |
| `LOCK-001` | 并发 Agent 写同一文件时的 lock/lease 机制设计 | Phase 4 多 Skill 并发时 |
| `EVAL-001` | AI Provider 离线 eval 集构建与评估流程（同一 judge 任务的多 Provider 质量对比） | Phase 5 完成后 |
| `SCHEMA-VERSION-001` | `prompt_template_id` 和 `output_schema_id` 的版本治理（何时可以 deprecate 旧版本） | Phase 5 完成后 |
| `GLOSSARY-UPDATE-001` | `it-zh-glossary.md` 更新机制（判断新条目纳入阈值、格式、审核人）| Phase 3 首次生产运行后 |
| `HEALTH-POLICY-001` | source health 降级阈值（多少次失败后停止采集该信源，如何恢复） | Phase 3 运行稳定后 |
| `MEMORY-RETENTION-001` | `known_item_ids` 保留策略（最大条目数、过期时间、清理方式）| Phase 3 实现时 |
| `ARCHIVE-POLICY-001` | `archive/` 中被拒事件的保留周期（多久清理或迁移到冷存储）| Phase 4 稳定后 |

---

## §13. 风险总览

| 风险 | 影响 | 所在 Phase | 缓解策略 |
|------|------|-----------|---------|
| 抽象过度，迟迟不能落地 | 内核无法运行 | Phase 3 | 以意大利 reference package 驱动内核接口，每阶段有最小验收场景 |
| 抽象不足，第二国家迁移返工 | Phase 7 需大量重构 | Phase 3-4 | `TargetConfig` 不允许写死国家逻辑，Phase 3 完成后做"无意大利硬编码"审查 |
| Provider 绑定，成本/可用性风险 | Phase 5 被某 Provider 锁死 | Phase 5 | `route_id` 驱动，不用 Provider 名直接命名，Phase 5 前用 mock 路由 |
| sandbox 缺失，高风险工具失控 | Phase 6 社媒工具越界 | Phase 6 | Phase 3 就实现最小 enforcer，Phase 6 强化，不提前开放 |
| 文件协议混乱，多 Agent 交接不可靠 | 数据丢失或重复 | Phase 3-4 | `id` 确定性哈希去重，`processing_history` 追加不覆盖，LOCK-001 治理 backlog |
| LLM 成本线性失控 | 运营成本不可控 | Phase 5 | `max_provider_cost`、优先级队列、低分事件不进 LLM |
| 自动化越界，发布事故 | 合规/事实风险 | 全 Phase | v1 只产草稿，`publish/` 只做归档，验收清单含"自动发布事故=0"要求 |
| 术语翻译不一致 | 草稿质量低，人审成本高 | Phase 3+ | `it-zh-glossary.md` 种子表，`glossary_hit_rate < 50` 时降为 monitor |
