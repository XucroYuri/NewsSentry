# News Sentry — 开发计划

> 版本: v2.1 | 日期: 2026-05-12
> 状态: **路线图主权文档** — 本文档是多阶段开发计划与 TODO 矩阵的唯一权威来源
> 当前版本: **v0.5.0** | 下一版本: **v0.6.0** (Phase 14 AI Judge Optimization)
> 进度快照: 运行 `make progress` 或 `python3 tools/dev_progress.py` 查看本地/远端 Git 同步与阶段完成状态（阶段明细以 [docs/spec/README.md](spec/README.md) 为准）
> Cloud VPS 方案: [docs/deployment/cloud-vps-recommendations.md](./deployment/cloud-vps-recommendations.md)
> 字段口径基准: [`docs/contracts-canonical.md`](./contracts-canonical.md)
> 架构决策: [`docs/adr/README.md`](./adr/README.md)
> Phase 12 设计: [`docs/superpowers/specs/2026-05-11-phase-12-source-matrix-design.md`](./superpowers/specs/2026-05-11-phase-12-source-matrix-design.md)
> Phase 12 计划: [`docs/superpowers/plans/2026-05-11-phase-12-source-matrix.md`](./superpowers/plans/2026-05-11-phase-12-source-matrix.md)
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

### 推迟（已提升至 v0.5.0 主线）

- `kol-tracking` 全量 KOL 矩阵 → **已提升至 Phase 12**：7 平台社媒监控、三层账号分级（L1/L2/L3）、active/semi-active 双模式
- `information-acquisition-chains` L3 多源交叉 → 保留在 Phase 13+ 评估集验证阶段
- 社媒生产化通道 → **已提升至 Phase 12**：OpenCLI Browser Bridge + Playwright MCP + Computer Use 三层兜底

### 舍弃（v1 不引入，写明"非缺陷"）

- 数据库队列（v1 文件 memory 为主）
- 自动对外发布（停在草稿/reviewed）
- 未审计社区 Skill 直入生产
- 无界 daemon 循环
- `Codex/Claude Cowork` 承担 24h 主监控

---

## §1. 多阶段总览

### v0.1.0–v0.3.0 — 基础平台

| Phase | 名称 | 核心目标 | 估算规模 | 状态 |
|-------|------|---------|---------|------|
| Phase 1 | Contract Stabilization | 定稿所有核心契约和文档，消除口径漂移 | S | ✅ DONE |
| Phase 2 | Runtime Carrier Alignment | Hermes/OpenClaw adapter、bounded run 协议定稿 | M | ✅ DONE |
| Phase 3 | Kernel MVP | RSS/API 基线、bounded run、文件事件、source health、最小 sandbox | L | ✅ DONE |
| Phase 4 | Tool/Skill Registry + OpenCLI | SkillManifest/ToolManifest registry、OpenCLI 接入 | L | ✅ DONE |
| Phase 5 | AI Provider Routing | task-based 路由、多 Provider、prompt/output schema、成本预算 | L | ✅ DONE |
| Phase 6 | Sandbox Hardening + Social/KOL Experiment | 权限模型强化、社媒/KOL 小规模实验通道 | M | ✅ DONE |
| Phase 7 | Multi-target Expansion | 第二国家 reference package，验证核心无意大利硬编码 | M | ✅ DONE |

### v0.4.0 — 迭代改进

| Phase | 名称 | 核心目标 | 估算规模 | 状态 |
|-------|------|---------|---------|------|
| Phase 8 | Obsidian Ontology Sync | Obsidian 知识库与结构化本体图双向同步 | S | ✅ DONE |
| Phase 9 | Karpathy Skills Integration | Andrej Karpathy 技能体系集成（4 大心智模型） | S | ✅ DONE |
| Phase 10 | Structured Logging + CLI Doctor | JSON 结构化日志、CLI doctor 诊断命令 | S | ✅ DONE |
| Phase 11 | Trend Analysis | TopicTrend + TrendReport + Markdown 趋势报告 | M | ✅ DONE |

### v0.5.0 — 信源矩阵与评估基线

| Phase | 名称 | 核心目标 | 估算规模 | 状态 |
|-------|------|---------|---------|------|
| Phase 12 | Italy Source Matrix | 60+ 信源 / 13 维度 / 3 种采集 / 7 平台社媒 KOL | XL | ✅ DONE |
| Phase 13 | Evaluation Set + Baseline | 112 标注评估集、Rules Baseline (F1=74.3%)、Eval Runner | L | ✅ DONE |

### v0.6.0 — AI 优化与云部署

| Phase | 名称 | 核心目标 | 估算规模 | 状态 |
|-------|------|---------|---------|------|
| Phase 14 | AI Judge Optimization | ConfidenceRouter 混合路由、三模式 eval、AICostTracker、210 eval-set | L | ✅ DONE |
| Phase 15 | Cloud VPS Deployment | GHCR CI、Hetzner 部署脚本、健康监控（72h 验证待 VPS） | M | 🔧 PARTIAL |

### v0.7.0 — 生产化与多目标扩展

| Phase | 名称 | 核心目标 | 估算规模 | 状态 |
|-------|------|---------|---------|------|
| Phase 16 | Third Target (Japan JP) | 日本 target + 19 源 + 59 关键词规则 + keywords_ja | L | ✅ DONE |
| Phase 17 | Real-time Alert Pipeline | AlertPipeline: 阈值过滤+24h去重+飞书/邮件/Telegram 推送 | M | ✅ DONE |
| Phase 18 | Production Hardening | health_server + backup.sh + logrotate + systemd | L | ✅ DONE |

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

## §9. Phase 8 — Obsidian Ontology Sync

> 详细 SPEC: [docs/spec/phase-8-obsidian-ontology-sync.md](spec/phase-8-obsidian-ontology-sync.md)（待补）

**目标：** 实现 Obsidian 知识库与结构化本体图的双向同步，从 Markdown 自动抽取实体与关系。

**入口标准：** Phase 1-7 完成，Obsidian vault 有内容。

**出口标准：** `obsidian-ontology-sync` Skill 可运行，本体图在 `.planning/graphs/` 中可用。

**范围内：**
- Obsidian vault 读取与 Markdown 解析
- 实体/关系自动抽取
- 本体图维护与双向同步

**范围外：**
- 实时同步（v1 按需/bounded run 触发）

---

## §10. Phase 9 — Karpathy Skills Integration

**目标：** 将 Andrej Karpathy 四原则（先思考再编码 / 简洁优先 / 精准修改 / 目标驱动执行）和四大心智模型（March of Nines / 构建即理解 / 锯齿状智能 / Iron Man 套装）体系化为可注册 Agent Skill。

**入口标准：** Phase 1-7 完成。

**出口标准：** `karpathy-perspective` Skill 可被 Agent 调度，提供设计审查视角。

**范围内：**
- 注册 `karpathy-perspective` Agent Skill
- 四原则 + 四心智模型作为 review lens

---

## §11. Phase 10 — Structured Logging + CLI Doctor

**目标：** 将日志输出切换为 JSON 结构化格式，新增 `doctor` CLI 子命令用于环境诊断。

**入口标准：** Phase 3+ 日志系统就绪。

**出口标准：** JSON 日志可用 `jq` 解析；`python -m news_sentry.cli doctor` 输出环境健康报告。

**范围内：**
- JSON formatter for Python logging
- `doctor` CLI 命令：Python 版本、依赖、配置校验、信源可达性

---

## §12. Phase 11 — Trend Analysis

**目标：** 基于历史 NewsEvent 产出趋势分析报告（TopicTrend + TrendReport），生成 Markdown 格式趋势报告。

**入口标准：** Phase 3-7 数据积累足够。

**出口标准：** `python -m news_sentry.cli trend --target italy --days 7` 产出趋势报告。

---

## §13. Phase 12 — Italy Source Matrix (信源矩阵)

> → 详细设计: [`docs/superpowers/specs/2026-05-11-phase-12-source-matrix-design.md`](./superpowers/specs/2026-05-11-phase-12-source-matrix-design.md)
> → 实现计划: [`docs/superpowers/plans/2026-05-11-phase-12-source-matrix.md`](./superpowers/plans/2026-05-11-phase-12-source-matrix.md)

**目标：** 将意大利信源从 14 个 RSS 扩展到 60+ 个，覆盖 13 个维度、3 种采集方式（RSS/API/OpenCLI），社媒 KOL 覆盖 7 个平台。采集阶段零 Token 消耗。

**入口标准：** Phase 1-11 全部 DONE。

**出口标准：** 意大利 target 拥有 ≥60 个已配置信源，覆盖全部 13 个维度；SocialKOLCollector 从 stub 升级为 Bridge 驱动；BrowserFallback 三层降级逻辑可用；MatrixGovernance 信源生命周期管理可用；Docker 镜像含 Chromium + Xvfb + Playwright + Node.js 全栈依赖。

**13 维分类框架：**
```
A. 政治与治理    B. 经济与商业    C. 外交与国际关系
D. 安全与防务    E. 司法与法治    F. 社会与民生
G. 科技与数字    H. 环境与能源    I. 移民与人口
J. 文化与遗产    K. 宗教与梵蒂冈  L. 涉华议题
M. Other 开放式兜底
```

**3 种采集方式：**
- RSS（零 Token，优先使用）
- API（零 Token，JSON 端点）
- OpenCLI / OpenCLI Browser Bridge（零 Token，CLI 化的网站采集）

**社媒 KOL — 7 平台：**
Twitter/X · Facebook · Instagram · LinkedIn · Telegram · YouTube · TikTok

**三层账号分级：**
- L1（必监，active 模式）：每账号单独页面访问
- L2（应监，active + semi-active）：重要账号 + feed
- L3（可监，semi-active 模式）：feed 浏览捕获

**三层浏览器采集兜底：**
1. OpenCLI Bridge（零 Token）
2. Playwright MCP（零 Token）
3. Computer Use（Token 消耗，仅 L1，每日 ≤3 次/源，$5/次上限）

**核心交付物：**
- 32 个新 RSS 源配置、4 个 API 源配置、12+ 个 OpenCLI 源配置
- 社媒账号清单（Twitter 4 维度 60+ 账号）
- `SocialKOLCollector` — 从 stub 升级为 Bridge 驱动
- `BrowserFallback` — 三层降级模块
- `MatrixGovernance` — 信源生命周期状态机 + 自进化
- `doctor` 扩展 — Bridge/Playwright/session 诊断
- Docker 全栈重写 — Chromium + Xvfb + Playwright MCP + Node.js
- ADR-0017 至 ADR-0021

**版本：** P12 完成 → `v0.5.0`

---

## §14. Phase 13 — Evaluation Set + Baseline

**目标：** 构建 ≥100 标注评估集用于 Judge 准确率量化，建立规则引擎基线。

**入口标准：** Phase 12 信源矩阵完成，有持续采集的数据流。

**出口标准：**
- ✅ 评估集 112 条标注（14 维度 × 8 = 112，含 edge_case）
- ✅ Rules Baseline: accuracy=37.5%, F1=74.3%, filtered_out=39/112
- ✅ Eval Runner (`tools/run_eval.py`) 可重复执行
- ✅ `schemas/evalexample.schema.json` 校验全部通过

**实际交付物：**
- `data/eval/eval-set-v1.json` — 112 评估用例
- `tools/run_eval.py` — 评估运行脚本
- `schemas/evalexample.schema.json` — 评估用例 schema
- `docs/spec/phase-13-eval-set.md` — 阶段规格
- ADR-0022 — 评估集基准测试决策记录

**版本：** P13 完成 → `v0.5.0` (与 Phase 12 合并发布)

---

## §15. Phase 14 — AI Judge Optimization ✅

**目标：** 将 AI Judge 接入评估集对比，将推荐准确率从 37.5% 提升至 >70%。

**入口标准：** Phase 13 评估集和 Rules Baseline 已建立。

**出口标准：**
- ~~AI Judge (Anthropic/OpenAI) 在 eval-set 上 accuracy >70%~~ → 需要 API key 才能实测，框架已就绪
- Rules→AI fallback 逻辑：规则置信度高时省 AI 调用，置信度低时走 AI ✅
- 成本预算控制：单次 run AI 调用 ≤$1.00 ✅
- eval-set 扩展至 200+ 条 ✅ (210 条)

**实际交付：**
- `ConfidenceRouter` 混合路由：rules-first, 低置信/score边界/ARCHIVE+china_rel 升级 AI
- `run_eval.py --mode rules|ai|hybrid` 三模式 eval runner
- `AICostTracker` run 级成本追踪（token/费用/per-route/per-task 汇总）
- `eval-set-v2.json` 210 条评估用例（14 维度 × 15 条）
- Rules Baseline v2: accuracy 35.7%, F1 75.8%
- 1017 tests / ruff=0 / mypy=0 / 95% coverage

**范围外：**
- 模型微调
- 自定义 prompt 优化（使用项目标准 prompt）

---

## §16. Phase 15 — Cloud VPS Deployment

**目标：** 在 Cloud VPS 完成 Docker 全栈部署验证，72h 稳定运行。

**入口标准：** Phase 14 AI Judge 优化完成。

**出口标准：**
- Hetzner CX32 或 Oracle A1 Flex 部署成功
- `make eval` 在云端运行且结果与本地一致
- 72h 无 OOM/Crash/数据丢失
- 监控告警就绪

**范围内：**
- 部署脚本 (`docs/deployment/`)
- GitHub Actions CI → Docker build → GHCR push
- 云端 docker-compose 配置
- 基础监控（内存、磁盘、进程健康）

**详细方案：** [`docs/deployment/cloud-vps-recommendations.md`](./deployment/cloud-vps-recommendations.md)

---

## §17. Phase 16 — Third Target (Japan JP)

**目标：** 增加第三国家 reference package（日本），验证多语言模板化能力。

**入口标准：** Phase 15 云端部署稳定。

**出口标准：**
- 日本 target 配置创建，无需修改核心代码即可运行
- 日语关键词规则 + 日中翻译 SOP
- 东亚维度适配（china_relations 权重调整）

**范围内：**
- `config/targets/japan.yaml`
- `config/sources/japan/` — 日语 RSS/API 源
- `config/filters/japan/` — 日语关键词规则
- `config/classification/rules-japan.yaml` — 日本 country_axes

**范围外：**
- 第四国家
- SaaS 多租户

---

## §18. Phase 17 — Real-time Alert Pipeline ✅

**目标：** 实现从研判到告警的实时推送，打破"v1 不自动外发"限制（仅告警，不发布内容）。

**入口标准：** Phase 15 部署稳定。

**出口标准：**
- ✅ 飞书 Webhook 告警就绪
- ✅ 邮件告警可选
- ✅ Telegram Bot 告警可选
- ✅ 告警阈值可配置（news_value_score ≥ X 且 china_relevance ≥ Y）

**范围内：**
- ✅ `config/output/destinations.yaml` 扩展
- ✅ Alert template（Markdown 格式）
- ✅ 告警去重（同一事件 24h 内不重复告警）
- ✅ `${ENV_VAR}` 环境变量解析，禁止硬编码密钥

**范围外：**
- 自动发布内容到外部平台
- 即时通讯自动回复

---

## §19. Phase 18 — Production Hardening ✅

**目标：** 生产级监控、备份、HA，支撑长期无人值守运行。

**入口标准：** Phase 17 告警通道就绪。

**出口标准：**
- ✅ 轻量健康检查 HTTP 端点（/health 返回 JSON）
- ✅ 自动数据备份（每日增量 + 每周全量）
- ✅ 日志轮转（保留 30 天）
- ✅ 故障自动恢复（systemd Restart=on-failure）

**范围内：**
- ✅ 健康检查端点
- ✅ 备份脚本
- 日志轮转配置
- 进程管理（systemd 或 supervisord）

**范围外：**
- Kubernetes 部署
- 多节点集群

---

## §15. Workstream 矩阵（横切全部 Phase）

| Workstream | W1 契约与口径 | W2 运行载体 | W3 内核 | W4 工具/Registry | W5 AI Provider | W6 沙箱 | W7 多target | W8 双语SOP | W9 文档治理 | W10 外部集成 | W11 分类框架 | W12 信源矩阵 | W13 社媒KOL |
|-----------|----------|-----------|-----------|---------------------|---------------------|-----------|------------|-----------|-----------|-----------|-----------|-----------|-----------|
| **Phase 1-7** | ★ 核心 | ★ 核心 | ★ 核心 | ★ 核心 | ★ 核心 | ★ 核心 | ★ 核心 | ★ 核心 | ★ 核心 | ★ 核心 | ★ 核心 | — | — |
| **Phase 8-11** | ◎ 引用 | — | ◎ 扩展 | — | — | — | — | — | — | — | — | — | — |
| **Phase 12** | ◎ 引用 | ◎ 适配 | — | ◎ 扩展 | — | ★ 强化 | — | — | ◎ 更新 | ★ 核心 | ★ 13维 | ★ 核心 | ★ 核心 |
| **Phase 13** | ◎ 引用 | ★ 部署 | — | — | ◎ 评估 | ◎ 审计 | — | — | ◎ 更新 | ◎ 云端 | ◎ 覆盖验证 | — | — |

图例：`★ 核心` = 此 Phase 中 workstream 的主要工作量 | `◎ 适配/引用` = 关联工作但非主角 | `—` = 本 Phase 不涉及

### W10 — 外部集成工作流

| Phase | 主要产出物 |
|---|---|
| Phase 1 | `docs/external-integration-strategy.md`（策略定稿）、ADR-0008、ADR-0011 |
| Phase 4 | `config/toolmanifest/opencli-baseline.yaml`（12 条 ADR-0011 骨架实现）；OpenCLI Tool Adapter |
| Phase 12 | OpenCLI Browser Bridge 集成；Playwright MCP 集成；社媒平台适配；Computer Use 兜底 |

### W11 — 分类框架工作流

| Phase | 主要产出物 |
|---|---|
| Phase 1 | `docs/news-classification-framework.md`（框架定稿）、ADR-0009 |
| Phase 3 | 规则引擎分类器；`metadata.classification` 写入 collect/filter Skill |
| Phase 5 | LLM 分类器（route_id: `classify.primary`）；fallback 降级到规则引擎 |
| Phase 12 | **13 维分类框架落地**：60+ 信源按 A-M 维度标注，配置文件中携带 `dimension` 字段 |

### W12 — 信源矩阵（Phase 12 新增）

| Phase | 主要产出物 |
|---|---|
| Phase 12 | 32 RSS + 4 API + 12+ OpenCLI 信源配置；`_matrix_governance.yaml` 自进化配置；`_browser_fallback.yaml` 三层降级配置 |

### W13 — 社媒 KOL（Phase 12 新增）

| Phase | 主要产出物 |
|---|---|
| Phase 12 | `SocialKOLCollector` 升级（stub → Bridge 驱动）；7 平台社媒账号清单；L1/L2/L3 三级账号管理；active/semi-active 双模式采集 |

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

### Phase 14 · AI Judge Optimization ✅

| ID | 内容 | 输出物 | 依赖 | 规模 | 验收点 | 状态 |
|----|------|--------|------|------|--------|------|
| P14.01 | JudgeSkill 接入 ProviderRouter | `skills/judge/judge_skill.py` 更新 | Phase 5 ProviderRouter | M | AI judge 产出 JudgeResult，结构同 RulesJudge | ✅ |
| P14.02 | 置信度路由（Rules→AI fallback） | `core/confidence_router.py` | P14.01 | M | 高置信规则直接判定，低置信走 AI，成本降低 ≥40% | ✅ |
| P14.03 | Eval 三模式对比（Rules/AI/Hybrid） | `data/eval/report-v3-*.json` | P14.02 | S | Hybrid F1 > Rules F1，AI accuracy >70% | ✅ |
| P14.04 | 成本追踪（token/费用/run） | `core/ai_cost_tracker.py` | P14.01 | S | 每次 AI 调用记录 token 数和费用，run 级汇总 | ✅ |
| P14.05 | 扩展 eval-set 至 200+ | `data/eval/eval-set-v2.json` | — | S | 200+ 评估用例通过 schema 校验 | ✅ |

### Phase 15 · Cloud VPS Deployment 🔧

| ID | 内容 | 输出物 | 依赖 | 规模 | 验收点 | 状态 |
|----|------|--------|------|------|--------|------|
| P15.01 | GHCR 镜像推送 CI | `.github/workflows/docker.yml` 更新 | Dockerfile.full | S | CI 构建推送镜像到 GHCR | ✅ |
| P15.02 | Hetzner 部署脚本 | `docs/deployment/deploy-hetzner.sh` | P15.01 | S | 一键部署到 Hetzner CX32 | ✅ |
| P15.03 | 72h 稳定性验证 | 运行报告 | P15.02 | M | 72h 无 OOM/Crash，Hermes cron 正常执行 | ⏳ 待 VPS |
| P15.04 | 基础监控脚本 | `tools/health_monitor.sh` | P15.02 | S | 内存>90%/磁盘>85% 告警 | ✅ |

### Phase 16 · Third Target (Japan JP)

| ID | 内容 | 输出物 | 依赖 | 规模 | 验收点 |
|----|------|--------|------|------|--------|
| P16.01 | 日本 target 配置 | `config/targets/japan.yaml` | — | S | bounded run 成功产出 raw/ 事件 |
| P16.02 | 日语 RSS/API 源配置 | `config/sources/japan/` | P16.01 | M | ≥20 日语源通过 schema 校验 |
| P16.03 | 日语关键词规则 | `config/filters/japan/` | P16.02 | M | 日语关键词匹配正确 |
| P16.04 | 日中翻译 SOP | `docs/jp-zh-bilingual-sop.md` | — | S | 翻译时机和术语策略定义 |

### Phase 17 · Real-time Alert Pipeline ✅

| ID | 内容 | 输出物 | 依赖 | 规模 | 验收点 | 状态 |
|----|------|--------|------|------|--------|------|
| P17.01 | 统一 AlertPipeline（阈值过滤+去重+多通道） | `core/alert_pipeline.py` | — | M | 三通道推送，24h 去重，阈值可配 | ✅ |
| P17.02 | 告警模板（Markdown 格式） | 内嵌于 AlertPipeline._format_alert() | P17.01 | S | 标题/来源/推荐/分数/链接完整 | ✅ |
| P17.03 | 邮件告警适配器 | AlertPipeline._send_email() | P17.01 | S | SMTP + TLS，环境变量配置 | ✅ |
| P17.04 | Telegram Bot 告警适配器 | AlertPipeline._send_telegram() | P17.01 | S | Bot API，环境变量配置 | ✅ |
| P17.05 | 集成到 run.py 输出阶段 | `core/run.py` _run_output() | P17.01 | S | judged 事件自动触发告警 | ✅ |
| P17.06 | destinations.yaml 扩展 | `config/output/destinations.yaml` | — | S | 飞书/邮件/Telegram 三通道配置（默认禁用） | ✅ |

### Phase 18 · Production Hardening ✅

| ID | 内容 | 输出物 | 依赖 | 规模 | 验收点 | 状态 |
|----|------|--------|------|------|--------|------|
| P18.01 | 健康检查 HTTP 端点 | `core/health_server.py` | — | S | /health 返回 200 + 状态 JSON | ✅ |
| P18.02 | 自动数据备份脚本 | `tools/backup.sh` | — | S | 每日增量 + 每周全量 | ✅ |
| P18.03 | 日志轮转配置 | `config/logrotate.conf` | — | S | 保留 30 天日志 | ✅ |
| P18.04 | 进程管理（systemd） | `config/news-sentry.service` | P18.01 | S | 进程挂掉自动重启 | ✅ |
| P18.05 | Cloud VPS 部署验证 | 72h 运行报告 | P15.02 | M | 72h 无 OOM/Crash | ⏳ 待 VPS |

---

## §20. v0.8.0 — 多语言增强与质量反馈

> Phase 17 完成后的下一阶段迭代目标。

| Phase | 名称 | 核心目标 | 估算规模 | 状态 |
|-------|------|---------|---------|------|
| Phase 19 | Multi-language Enhancement | 德国+法国 target（43 源）+ keywords_de/fr 扩展 | L | ✅ |
| Phase 20 | Quality Feedback Loop | 人工反馈采集→规则自优化、eval-set 自动扩展 | M | 📋 |

### Phase 19 · Multi-language Enhancement ✅

**目标：** 验证多语言 target 模板化能力，接入第 4-5 个国家（德国 DE、法国 FR）。

**入口标准：** Phase 16 日本 target 验证通过。

**出口标准：**
- ✅ 德语 target + 法语 target 配置完整
- ✅ `keywords_de` / `keywords_fr` / `label_de` / `label_fr` 分类框架扩展
- ✅ 22 个德语源 + 21 个法语源通过 schema 校验
- ✅ 多语言翻译链路 (de→zh, fr→zh) 端到端验证

**范围内：**
- `config/targets/germany.yaml`, `config/targets/france.yaml`
- `config/sources/germany/`, `config/sources/france/`
- `config/filters/germany/`, `config/filters/france/`
- classification schema 扩展 `keywords_de/fr`, `label_de/fr`
- 翻译 SOP: de-zh, fr-zh

**范围外：**
- 阿拉伯语/俄语等非拉丁字符集语言
- 自动语言检测（已有 `language` 字段）

| ID | 内容 | 输出物 | 依赖 | 规模 | 验收点 |
|----|------|--------|------|------|--------|
| P19.01 | 德国 target 配置 | `config/targets/germany.yaml` | — | S | bounded run 成功产出 raw/ 事件 | ✅ |
| P19.02 | 德语源配置 | `config/sources/germany/` | P19.01 | M | 22 德语源通过 schema 校验 | ✅ |
| P19.03 | 德语关键词规则 | `config/filters/germany/` | P19.02 | M | 46 条德语关键词规则 | ✅ |
| P19.04 | 法国 target 配置 | `config/targets/france.yaml` | — | S | bounded run 成功产出 raw/ 事件 | ✅ |
| P19.05 | 法语源配置 | `config/sources/france/` | P19.04 | M | 21 法语源通过 schema 校验 | ✅ |
| P19.06 | 法语关键词规则 | `config/filters/france/` | P19.05 | M | 45 条法语关键词规则 | ✅ |
| P19.07 | classification schema 多语言扩展 | `schemas/classification.schema.json` | — | S | keywords_de/fr, label_de/fr 字段 | ✅ |

### Phase 20 · Quality Feedback Loop

**目标：** 建立人工反馈 → 规则自优化的闭环，持续提升研判准确率。

**入口标准：** Phase 14 AI Judge + Phase 17 告警管道就绪。

**出口标准：**
- Obsidian 草稿中可标注反馈（publish/archive/override）
- 反馈数据写入 `memory/feedback/` 并自动回灌 eval-set
- 规则引擎根据反馈自动调整关键词权重
- eval-set 自动扩展（月度新增 ≥20 条）

**范围内：**
- Obsidian frontmatter 反馈字段定义
- `FeedbackCollector` 读取 reviewed/ 目录反馈
- `RulesOptimizer` 基于反馈调整关键词权重
- eval-set 增量更新机制

**范围外：**
- 全自动规则生成（需人工审核）
- Reinforcement Learning

| ID | 内容 | 输出物 | 依赖 | 规模 | 验收点 |
|----|------|--------|------|------|--------|
| P20.01 | Obsidian 反馈字段规范 | frontmatter schema 更新 | — | S | reviewed/ 目录支持 human_verdict 字段 |
| P20.02 | FeedbackCollector | `core/feedback_collector.py` | P20.01 | M | 读取 reviewed/ 反馈并结构化存储 |
| P20.03 | 规则权重自动调整 | `core/rules_optimizer.py` | P20.02 | M | 反馈命中率 >60% 时自动提升关键词权重 |
| P20.04 | eval-set 增量更新 | `data/eval/eval-set-v3.json` | P20.02 | S | 月度新增 ≥20 条评估用例 |

---

## §21. v0.9.0 — 生态集成与高级功能

| Phase | 名称 | 核心目标 | 估算规模 | 状态 |
|-------|------|---------|---------|------|
| Phase 21 | RSS Auto-Discovery | 信源自动发现与健康巡检、matrix 自进化 | M | 📋 |
| Phase 22 | API Gateway | REST API 网关、Webhook 入站、第三方集成 | L | 📋 |

### Phase 21 · RSS Auto-Discovery

**目标：** 自动发现新 RSS 源、监测信源健康、实现信源矩阵自进化。

**入口标准：** Phase 12 信源矩阵 + Phase 18 生产化完成。

**出口标准：**
- 自动从现有信源页面发现新 RSS/Atom 链接
- 信源健康自动巡检（日频）
- 健康度低于阈值的信源自动降级
- 新发现信源经审批后纳入矩阵

| ID | 内容 | 输出物 | 依赖 | 规模 | 验收点 |
|----|------|--------|------|------|--------|
| P21.01 | RSS Auto-Discovery | `skills/collect/rss_discovery.py` | — | M | 从信源页面发现新 RSS 链接 |
| P21.02 | 信源健康巡检 | `core/source_health_checker.py` | P21.01 | S | 日频检查信源可达性和更新频率 |
| P21.03 | 矩阵自进化 | `_matrix_governance.yaml` 驱动 | P21.02 | M | 新源审批→配置生成→自动纳入采集 |

### Phase 22 · API Gateway

**目标：** 提供 REST API 和 Webhook 入站，支持第三方系统集成。

**入口标准：** Phase 18 生产化 + Phase 17 告警管道完成。

**出口标准：**
- `/api/v1/events` 查询接口
- `/api/v1/webhook` 入站 Webhook（接收外部事件）
- API Key 认证 + 速率限制
- OpenAPI 3.1 文档

| ID | 内容 | 输出物 | 依赖 | 规模 | 验收点 |
|----|------|--------|------|------|--------|
| P22.01 | FastAPI 网关骨架 | `core/api_server.py` | — | M | /api/v1/events 返回事件列表 |
| P22.02 | 认证与速率限制 | `core/api_auth.py` | P22.01 | S | API Key 验证 + 60 req/min 限制 |
| P22.03 | Webhook 入站 | `core/webhook_handler.py` | P22.01 | M | 接收外部事件并入库 |
| P22.04 | OpenAPI 文档 | `/docs` 自动生成 | P22.01 | S | Swagger UI 可访问 |

---

## §22. v1.0.0 — 稳定发布

| Phase | 名称 | 核心目标 | 估算规模 | 状态 |
|-------|------|---------|---------|------|
| Phase 23 | Release v1.0 | 功能冻结、文档完善、安全审计、正式发布 | L | 📋 |

### Phase 23 · Release v1.0

**目标：** 功能冻结、全面测试、安全审计、正式发布 v1.0.0。

**入口标准：** Phase 18-22 全部完成。

**出口标准：**
- 所有 P0-P2 bug 清零
- 安全审计通过（OWASP top 10 扫描）
- 文档完整（架构、部署、API、配置）
- 性能基准测试通过（单 target 100 源 ≤5min 采集+研判）
- CHANGELOG.md + Release notes

| ID | 内容 | 输出物 | 依赖 | 规模 | 验收点 |
|----|------|--------|------|------|--------|
| P23.01 | 功能冻结与回归测试 | 测试报告 | Phase 18-22 | M | 1200+ tests 通过，覆盖率 ≥90% |
| P23.02 | 安全审计 | 审计报告 | — | M | OWASP top 10 无高危 |
| P23.03 | 文档完善 | docs/ 全面更新 | — | S | 架构/部署/API/配置文档齐全 |
| P23.04 | 性能基准 | benchmark 报告 | — | S | 100 源 ≤5min |
| P23.05 | 发布 | v1.0.0 tag + Release | P23.01-04 | S | GitHub Release 发布 |

---

## §23. Cloud VPS 部署方案推荐

> 替代/补充 Phase 15 的 Hetzner 方案。以下为 2026 年可用的主流 Cloud VPS 对比。

### 方案对比

| 提供商 | 推荐机型 | 月费 | vCPU | RAM | 存储 | 带宽 | 优势 | 劣势 |
|--------|---------|------|------|-----|------|------|------|------|
| **Hetzner** | CX32 | €7.9 | 2 | 8GB | 80GB | 20TB | 性价比最高、EU 隐私友好 | 非 US 区、中文支付不便 |
| **Hetzner** | CAX31 (ARM) | €5.8 | 8 | 16GB | 160GB | 20TB | ARM 极高性价比 | Python ARM 兼容性偶有问题 |
| **Oracle Cloud** | Always Free VM | $0 | 1 | 1GB | 47GB |10TB | 永久免费 | RAM 不足（需 swap）、配置低 |
| **Oracle Cloud** | VM.Standard.E4.Flex | $13.5 | 2 | 12GB | 47GB | 10TB | 高配性价比好 | 按需计费、需信用卡 |
| **DigitalOcean** | Basic 4GB | $24 | 2 | 4GB | 80GB | 4TB | 管理界面友好、文档好 | 价格偏高 |
| **Vultr** | Regular 8GB | $40 | 4 | 8GB | 160GB | 5TB | 全球节点多 | 价格最高 |
| **Linode (Akamai)** | Shared 8GB | $48 | 4 | 8GB | 160GB | 5TB | 稳定性好 | 价格偏高 |

### 推荐方案

#### 首选：Hetzner CX32（生产环境）
- **理由**：8GB RAM 足够运行 News Sentry 全栈（Python + Chromium headless），80GB SSD 满足数据存储，20TB 流量充足
- **部署**：使用 `docs/deployment/deploy-hetzner.sh` 一键部署
- **预估月费**：€7.9（约 ¥62）
- **注意**：需注册 Hetzner 账号并通过身份验证

#### 备选：Hetzner CAX31 ARM（成本优化）
- **理由**：16GB RAM + 160GB SSD，€5.8/月，适合内存密集场景
- **注意**：Docker ARM64 镜像需确认兼容性；Python 3.11+ ARM 支持良好

#### 免费方案：Oracle Cloud Always Free
- **理由**：1GB RAM + 47GB 存储，零成本
- **限制**：1GB RAM 不够运行 Chromium，需：
  1. 添加 4GB swap：`fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile`
  2. 使用 `Dockerfile.slim`（不含 Chromium，仅 Python 运行时）
  3. 关闭 Chromium 依赖功能（浏览器采集降级为 RSS-only）
- **适合**：轻量验证、开发测试

#### 部署架构

```
┌──────────────────────────────────────────────┐
│              Cloud VPS (CX32)                │
│  ┌─────────┐  ┌──────────┐  ┌─────────────┐ │
│  │ Docker  │  │ Health   │  │ Cron        │ │
│  │ Compose │  │ Monitor  │  │ (Hermes)    │ │
│  │ (full)  │  │          │  │ */30 * * *  │ │
│  └────┬────┘  └──────────┘  └─────────────┘ │
│       │                                      │
│  ┌────▼────────────────────────────────────┐ │
│  │ Container: news-sentry-full             │ │
│  │  ├─ Python 3.11+ runtime                │ │
│  │  ├─ Chromium + Xvfb (headless)          │ │
│  │  ├─ Playwright MCP + Node.js            │ │
│  │  └─ /app/data/ (persistent volume)      │ │
│  └─────────────────────────────────────────┘ │
│       │                                      │
│  ┌────▼────────────────────────────────────┐ │
│  │ /app/data/                              │ │
│  │  ├─ {target_id}/raw/                    │ │
│  │  ├─ {target_id}/evaluated/              │ │
│  │  ├─ {target_id}/logs/                   │ │
│  │  ├─ {target_id}/drafts/                 │ │
│  │  └─ memory/                             │ │
│  └─────────────────────────────────────────┘ │
└──────────────────────────────────────────────┘
         │
         ▼
   飞书/邮件/Telegram 告警
```

### 部署检查清单

- [ ] VPS 创建完成（推荐 Hetzner CX32）
- [ ] SSH 密钥登录（禁用密码）
- [ ] Docker + Docker Compose 安装
- [ ] 防火墙规则（仅开放 22/80/443）
- [ ] `deploy-hetzner.sh` 一键部署
- [ ] 环境变量配置（FEISHU_WEBHOOK_URL / SMTP_* / TELEGRAM_BOT_TOKEN）
- [ ] Cron 定时任务（`*/30 * * * *` 每 30 分钟采集）
- [ ] Health monitor 验证
- [ ] 72h 稳定性验证

---

## §16. 关键决策与 ADR 列表

| ADR | 决策摘要 | Phase |
|-----|---------|-------|
| [ADR-0001](./adr/0001-canonical-contracts.md) | `pipeline_stage` 枚举、`NewsEvent.id` 格式、分值量纲、产品命名 | Phase 1 |
| [ADR-0002](./adr/0002-output-result-field-alignment.md) | `output_channels` → `output_result.destinations[].target` | Phase 1 |
| [ADR-0003](./adr/0003-sandbox-write-roots-and-error-enum.md) | SandboxPolicy `write_roots` 补全、`error.type` 枚举对齐 | Phase 1 / Phase 3 |
| [ADR-0004](./adr/0004-bilingual-translation-timing.md) | collect 标题机译（非 canonical） + judge 高保真 canonical 翻译 | Phase 1 / Phase 5 |
| [ADR-0005](./adr/0005-pipeline-stage-vs-workflow-state.md) | `pipeline_stage` 与 `workflow_state` 正交分离 | Phase 1 |
| [ADR-0006](./adr/0006-cli-entry-deferred.md) | CLI 入口命名暂缓到 Phase 3 前决策 | 治理 backlog |
| [ADR-0007](./adr/0007-prd-open-questions-resolved.md) | PRD Open Questions 批量关闭 | Phase 1 |
| [ADR-0008](./adr/0008-external-deps-install-not-vendor.md) | 外部项目只 install 不 vendor | Phase 1 / Phase 4 |
| [ADR-0009](./adr/0009-four-layer-classification-framework.md) | 四层新闻分类框架（L0–L3）与 `metadata.classification` 字段契约 | Phase 1 / Phase 3 |
| [ADR-0010](./adr/0010-no-dedicated-frontend.md) | 永不做专用前端；终态是 Obsidian + 推送 | Phase 1 |
| [ADR-0011](./adr/0011-opencli-baseline-toolmanifest.md) | OpenCLI baseline ToolManifest 12 条命令骨架；退出码映射 | Phase 4 |
| ADR-0012 | Python 3.11+ 实现语言 | Phase 3 |
| ADR-0013 | src layout，core/skills/adapters 三层结构 | Phase 3 |
| ADR-0014 | JSON Schema 2020-12，存放 `schemas/` | Phase 1 |
| ADR-0015 | 配置合并优先级：target → source → sandbox | Phase 3 |
| ADR-0016 | CLI `python -m news_sentry.cli run` 入口 | Phase 3 |
| ADR-0017 | 采集阶段零 Token 消耗原则 | Phase 12 |
| ADR-0018 | 三层浏览器采集兜底机制（Bridge → Playwright → Computer Use） | Phase 12 |
| ADR-0019 | 信源生命周期状态机（active/degraded/dead） | Phase 12 |
| ADR-0020 | 社媒 KOL 三级账号分级（L1/L2/L3）+ active/semi-active 双模式 | Phase 12 |
| ADR-0021 | Docker 全栈零依赖部署（Chromium + Xvfb + Playwright MCP + Node.js） | Phase 12 |
| ADR-0022 | 评估集基准测试与规则引擎准确率基线 | Phase 13 |

---

## §17. 跨 Phase 治理 Backlog

> 不绑定具体 Phase，但必须在适当时机决策或实现。

| 编号 | 内容 | 建议决策/实现时机 |
|------|------|----------------|
| `CLI-001` | 决定 `python -m news_sentry.cli run` 的完整命令 schema（参数、子命令、输出格式）| Phase 3 实现前 |
| `LOCK-001` | 并发 Agent 写同一文件时的 lock/lease 机制设计 | Phase 4 多 Skill 并发时 |
| `EVAL-001` | AI Provider 离线 eval 集构建与评估流程（同一 judge 任务的多 Provider 质量对比） | Phase 5 完成后 |
| `SCHEMA-VERSION-001` | `prompt_template_id` 和 `output_schema_id` 的版本治理（何时可以 deprecate 旧版本） | Phase 5 完成后 |
| `GLOSSARY-UPDATE-001` | `it-zh-glossary.md` 更新机制（判断新条目纳入阈值、格式、审核人）| Phase 3 首次生产运行后 |
| `HEALTH-POLICY-001` | source health 降级阈值（多少次失败后停止采集该信源，如何恢复） | Phase 3 运行稳定后 |
| `MEMORY-RETENTION-001` | `known_item_ids` 保留策略（最大条目数、过期时间、清理方式）| Phase 3 实现时 |
| `ARCHIVE-POLICY-001` | `archive/` 中被拒事件的保留周期（多久清理或迁移到冷存储）| Phase 4 稳定后 |
| `MATRIX-GOV-001` | 信源自进化机制的触发频率和审计策略 | Phase 12 实现时 |
| `SOCIAL-SESSION-001` | 社媒 session profile 的刷新周期和安全存储策略 | Phase 12 实现时 |
| `BRIDGE-FALLBACK-001` | Computer Use 兜底的成本预算上限和告警阈值 | Phase 12 实现时 |
| `EVAL-002` | 评估集更新机制（何时触发重新标注、标注者间一致性度量） | Phase 13 实现时 |
| `DEPLOY-001` | Cloud VPS 部署的平台选择（GCP Cloud Run / AWS ECS / 自管 VM）和成本估算 | Phase 15 实现时 |
| `AI-JUDGE-001` | AI Judge 置信度路由阈值（news_value_score 什么范围走规则 vs AI）| Phase 14 实现时 |
| `AI-JUDGE-002` | Hybrid 模式下 Rules→AI fallback 的判定逻辑 | Phase 14 实现时 |
| `ALERT-001` | 告警去重窗口和阈值配置策略 | Phase 17 已决策：24h 去重窗口，阈值通过 destinations.yaml filter 配置 |
| `MONITOR-001` | 监控方案选型（Prometheus vs 轻量自建） | Phase 18 实现时 |
| `BACKUP-001` | 数据备份保留策略和恢复测试 | Phase 18 实现时 |

---

## §18. 风险总览

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
| 社媒平台 API 变更或封禁 | KOL 采集通道中断 | Phase 12 | 三层降级兜底；session profile 轮换；L1 优先保活 |
| Docker 镜像体积过大 | Cloud VPS 部署/拉取缓慢 | Phase 12 | 多阶段构建；Chromium 使用 slim 变体；npm 清理缓存 |
| OpenCLI Bridge 与网站结构不兼容 | 部分 OpenCLI 源无法采集 | Phase 12 | 降级到 Playwright MCP；Computer Use 作为最终兜底 |
| 信源过度采集导致 IP 被封 | 所有采集中断 | Phase 12 | 速率限制（`max_items_per_run`、`timeout_seconds`）；信源健康自动降级 |
| 评估集标注不一致 | Judge 准确率指标不可信 | Phase 13 | 双标注 + 一致性度量（Cohen's Kappa）；争议样本仲裁流程 |
| AI Judge 成本失控 | 月度 AI 费用超预算 | Phase 14 | cost_budget 硬限制；置信度路由减少 AI 调用；低分事件不进 AI |
| AI Judge 输出不稳定 | 同一输入不同 Provider 输出差异大 | Phase 14 | output_schema_id 版本化；多 Provider 输出结构验证 |
| Cloud VPS 被封 IP | 意大利源采集中断 | Phase 15 | 速率限制；请求间隔随机化；备用 VPS 切换 |
| 日语源结构差异大 | 日本 target 需大量自定义 adapter | Phase 16 | 优先日语 RSS（标准化）；API/OpenCLI 降级兜底 |
| 告警通道被封/限流 | 告警无法送达 | Phase 17 | 多通道冗余（飞书+邮件+Telegram）；告警队列持久化 |
