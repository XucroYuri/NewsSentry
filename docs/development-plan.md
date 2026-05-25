# News Sentry — 开发计划

> 版本: v2.9 | 日期: 2026-05-22
> 状态: **路线图主权文档** — 本文档是多阶段开发计划与 TODO 矩阵的唯一权威来源
> 当前版本: **v1.7.0** | 下一版本: **v2.0.0**
> Phase 25-29 性能优化: ✅ 全部完成
> Phase 30 多语言 NLP: ✅ 全部完成
> Phase 31 NLP API: ✅ 全部完成
> Phase 32 Entity Tracking: ✅ 全部完成
> Phase 33 Web UI NLP: ✅ 全部完成
> Phase 34 运维仪表盘: ✅ 全部完成
> Phase 35 事件追踪链: ✅ 全部完成
> Phase 36 时间线叙事: ✅ 全部完成
> Phase 37 量化趋势分析: ✅ 全部完成
> Phase 38 智能告警 2.0: ✅ 全部完成
> Phase 39 Dashboard 增强: ✅ 全部完成
> Phase 40 治理积压清理: ✅ 全部完成
> Phase 41 反馈闭环 + 告警管理: ✅ 全部完成
> Phase 42 配置编辑: ✅ 全部完成
> Phase 43 文档同步: ✅ 全部完成
> Phase 44 评估集扩展: ✅ 全部完成
> Phase 45 CI/CD 整合: ✅ 全部完成
> Phase 46 治理 backlog 收尾: ✅ 全部完成
> Phase 49.5 应用产品化: ✅ 全部完成
> Phase 50 本地客户端 v1: ✅ 全部完成
> Phase 51 serve 生产加固: ✅ 全部完成
> Phase 52 本地客户端 v2: ✅ 全部完成
> Phase 53 Windows 安装支持: ✅ 全部完成 (安装脚本 + kill 命令跨平台 + 代码清理)
> Phase 54 质量加固: ✅ 全部完成 (Store 同步初始化修复 + markdown_writer 100% 覆盖 + AGENTS.md 同步)
> Phase 55 桌面壳: ✅ 全部完成 (pywebview 6.x API 适配 + 系统托盘 + 配置持久化 + SSE/PWA + Gtk macOS 窗口 + 6 US PRD)
> Phase 56 技术债清理: ✅ 全部完成 (测试修复 + 端点降级 + 静默异常加日志 + 日志级别 + 清理工件)
> Phase 57 桌面壳跨平台: ✅ 全部完成 (跨平台适配 + PyInstaller 打包 + 开机自启 + 通知统一 + 更新检测)
> Phase 58 本地客户端体验打磨: ✅ 全部完成 (测试挂起修复 + SSE 重连 + 快捷键确认 + PWA offline + 在线检测)
> Phase 59 前端模块化重构 + 代码质量: ✅ 全部完成 (CSS 目录索引 + 开发计划更新)
> Phase 60 CI 修复 + PyPI 发布: ✅ 全部完成 (mypy CI 兼容 + release workflow + Trusted Publisher)
> Phase 61 本地客户端发布准备: ✅ 全部完成 (v1.7.1 patch release)
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
| Phase 20 | Quality Feedback Loop | 人工反馈采集→规则自优化、eval-set 自动扩展 | M | ✅ |

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
| P20.01 | Obsidian 反馈字段规范 | frontmatter schema 更新 | — | S | reviewed/ 目录支持 human_verdict 字段 | ✅ |
| P20.02 | FeedbackCollector | `core/feedback_collector.py` | P20.01 | M | 读取 reviewed/ 反馈并结构化存储 | ✅ |
| P20.03 | 规则权重自动调整 | `core/rules_optimizer.py` | P20.02 | M | 反馈命中率 >60% 时自动提升关键词权重 | ✅ |
| P20.04 | eval-set 增量更新 | `data/eval/eval-set-v3.json` | P20.02 | S | 月度新增 ≥20 条评估用例 | 📋 |

---

## §21. v0.9.0 — 生态集成与高级功能

| Phase | 名称 | 核心目标 | 估算规模 | 状态 |
|-------|------|---------|---------|------|
| Phase 21 | RSS Auto-Discovery | 信源自动发现与健康巡检、matrix 自进化 | M | ✅ |
| Phase 22 | API Gateway | REST API 网关、Webhook 入站、第三方集成 | L | ✅ |

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
| P21.01 | RSS Auto-Discovery | `skills/collect/rss_discovery.py` | — | M | 从信源页面发现新 RSS 链接 | ✅ |
| P21.02 | 信源健康巡检 | `core/source_health_checker.py` | P21.01 | S | 日频检查信源可达性和更新频率 | ✅ |
| P21.03 | 矩阵自进化 | `_matrix_governance.yaml` 驱动 | P21.02 | M | 新源审批→配置生成→自动纳入采集 | ✅ |

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
| P22.01 | FastAPI 网关骨架 | `core/api_server.py` | — | M | /api/v1/events 返回事件列表 | ✅ |
| P22.02 | 认证与速率限制 | `core/api_auth.py` | P22.01 | S | API Key 验证 + 60 req/min 限制 | ✅ |
| P22.03 | Webhook 入站 | `core/webhook_handler.py` | P22.01 | M | 接收外部事件并入库 | ✅ |
| P22.04 | OpenAPI 文档 | `/docs` 自动生成 | P22.01 | S | Swagger UI 可访问 | ✅ |

---

## §22. v1.0.0 — 稳定发布

| Phase | 名称 | 核心目标 | 估算规模 | 状态 |
|-------|------|---------|---------|------|
| Phase 23 | Release v1.0 | 功能冻结、文档完善、安全审计、正式发布 | L | ✅ |

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
| P23.01 | 功能冻结与回归测试 | 测试报告 | Phase 18-22 | M | 1200+ tests 通过，覆盖率 ≥90% | ✅ |
| P23.02 | 安全审计 | 审计报告 | — | M | OWASP top 10 无高危 | ✅ |
| P23.03 | 文档完善 | docs/ 全面更新 | — | S | 架构/部署/API/配置文档齐全 | ✅ |
| P23.04 | 性能基准 | benchmark 报告 | — | S | 100 源 ≤5min | ✅ |
| P23.05 | 发布 | v1.0.0 tag + Release | P23.01-04 | S | GitHub Release 发布 | ✅ |

---

## §23. v1.1.0 — 实时突发新闻推送

> 产品定位升级：从「定期批量分析」转向「实时突发新闻雷达 + 分级推送」。
> 目标用户：一线记者（抢突发）、编辑（快速研判）、分析师（深度跟踪）。

| Phase | 名称 | 核心目标 | 估算规模 | 状态 |
|-------|------|---------|---------|------|
| Phase 24 | Real-time Breaking News Radar | 分钟级轮询 + 分级推送 + 本国相关性泛化 | L | ✅ |

### Phase 24 · Real-time Breaking News Radar

**目标：** 将 News Sentry 从 cron 定期批量工具升级为实时突发新闻雷达，支持分钟级发现→研判→分级推送。

**入口标准：** v1.0.0 发布完成，所有质量门通过。

**出口标准：**
- 分钟级 bounded_run 可通过 systemd timer 或 crontab 稳定调度
- 三级推送策略（L1 原文 / L2 翻译 / L3 稿件）在 AlertPipeline 中实现
- `china_relevance` 泛化为 `home_relevance`（本国相关性），每个 target 自定义关键词
- 推送渠道扩展（WhatsApp Phase 25 预留）

**核心设计决策：**

1. **保持 bounded_run + 外部调度**：不引入常驻 daemon，用 systemd timer 或 crontab 缩短到分钟级（1-5 分钟）
2. **三级推送策略**：
   - L1 原文快报（`news_value_score >= 60`）：标题+链接+评分 → Telegram
   - L2 翻译快报（`news_value_score >= 80`）：L1 + 自动中文翻译 → Telegram
   - L3 突发稿件（`news_value_score >= 90 && breaking`）：L2 + AI 报道方案草稿 → Telegram + 飞书
3. **本国相关性泛化**：`china_relevance` → `home_relevance`，关键词从 target 配置读取而非硬编码
4. **渠道扩展推迟到 Phase 25**：本项目聚焦架构和策略，WhatsApp 等新通道下一轮

**范围内（IN SCOPE）：**
- `home_relevance` 计算：每个 target 配置自己的 `home_relevance_keywords`，替代硬编码 `_CHINA_KEYWORDS`
- 三级推送策略：扩展 `destinations.yaml` 的 filter 支持 tier（L1/L2/L3）和自动翻译触发
- AlertPipeline 增强：支持 tier 分级，L2 自动触发翻译，L3 自动触发稿件生成
- 分钟级调度配置：systemd timer 模板 + crontab 模板
- `rules_judge.py` / `rules_provider.py` 的 `_CHINA_KEYWORDS` 改为从配置读取
- NewsEvent 字段：`china_relevance` 保留（向后兼容），新增 `home_relevance` 别名

**范围外（OUT OF SCOPE）：**
- WhatsApp 推送通道（Phase 25）
- 常驻 daemon 模式（保持 bounded_run）
- 移动 App 推送（Phase 25+）
- 自动对外发布（v1 约束不变）

**验收清单：**

- [x] 每个target配置含 `home_relevance_keywords`，`rules_judge.py` 从配置读取而非硬编码
- [x] `destinations.yaml` 支持 `tier: L1/L2/L3` 字段
- [x] L2 推送自动触发翻译（复用 ProviderRouter translate 路由）
- [x] L3 推送自动生成报道方案草稿（AI prompt）
- [x] systemd timer 模板支持 1-5 分钟间隔
- [x] 所有现有测试通过，新增 tier/home_relevance 测试
- [x] `china_relevance` 字段保留向后兼容

| ID | 内容 | 输出物 | 依赖 | 规模 | 验收点 |
|----|------|--------|------|------|--------|
| P24.01 | home_relevance 配置化 | targetconfig.schema.json + 5 个 target YAML | — | M | 每个 target 含 home_relevance_keywords，rules_judge 从配置读取 |
| P24.02 | 三级推送策略配置 | destinations.yaml tier 字段 + schema | P24.01 | S | L1/L2/L3 三级 filter 可配 |
| P24.03 | AlertPipeline tier 分发 | alert_pipeline.py 增强 | P24.02 | M | L1 推原文，L2 触发翻译，L3 触发稿件 |
| P24.04 | 翻译自动触发 | ProviderRouter translate 集成 | P24.03 | S | L2 推送自动附加中文翻译 |
| P24.05 | 报道方案草稿生成 | AI prompt 模板 + JudgeSkill 集成 | P24.04 | M | L3 推送含 AI 生成报道方案 |
| P24.06 | 分钟级调度模板 | systemd timer + crontab 模板 | — | S | 1-5 分钟可配置，systemd timer/crontab 二选一 |
| P24.07 | 向后兼容与测试 | 测试补全 + china_relevance 兼容层 | P24.01-05 | M | 现有测试全通过，新增 ≥30 测试 |

## §24. v1.2.0 — 性能优化

> 性能设计文档: [`docs/performance-overhaul-design.md`](./performance-overhaul-design.md)
> 1467 tests / ruff=0 / mypy=0 / 92% coverage

| Phase | 名称 | 核心目标 | 估算规模 | 状态 |
|-------|------|---------|---------|------|
| Phase 25 | Async Pipeline Core | 异步采集+过滤+研判 pipeline，httpx.AsyncClient 共享连接池 | L | ✅ |
| Phase 26 | SQLite Storage | SQLite 异步存储引擎，替代文件扫描查询 | M | ✅ |
| Phase 27 | AI Batch & Cache | AI 调用批处理 + LRU 缓存 + 分级路由 | L | ✅ |
| Phase 28 | API Server SQLite | API 端点 SQLite 查询 + ConfigCache TTL + reload | M | ✅ |
| Phase 29 | Multi-target Concurrency | FairScheduler + --target all + --interval loop | L | ✅ |

### Phase 25 · Async Pipeline Core ✅

**目标：** 将同步 pipeline 转为异步架构，httpx.AsyncClient 共享连接池，提升 I/O 密集型操作吞吐量。

**核心交付：**
- `async_run.py` — 异步 bounded_run 入口 (`bounded_run_async`)
- `_run_collect_async` / `_run_filter_async` / `_run_judge_async` / `_run_output_async` 异步阶段
- `AsyncStore` 异步 SQLite 存储骨架
- 共享 `httpx.AsyncClient` 连接池
- 1332 tests → 1402 tests

| ID | 内容 | 输出物 | 依赖 | 规模 | 验收点 | 状态 |
|----|------|--------|------|------|--------|------|
| P25.01 | AsyncStore 异步存储引擎 | `core/async_store.py` | — | M | 异步写入/查询事件索引 | ✅ |
| P25.02 | 异步 bounded_run 入口 | `core/async_run.py` | P25.01 | L | 单 target 异步 pipeline 端到端跑通 | ✅ |
| P25.03 | httpx.AsyncClient 共享连接池 | 集成到 async_run | P25.02 | S | 采集阶段复用连接池，减少 TCP 握手 | ✅ |
| P25.04 | 异步 filter/judge/output | async_run 各阶段 | P25.02 | M | 各阶段异步化，维持数据一致性 | ✅ |

### Phase 26 · SQLite Storage ✅

**目标：** SQLite 作为事件索引存储引擎，替代全文件扫描，支持分页查询和聚合统计。

**核心交付：**
- `AsyncStore` 完整实现：`query_events`、`get_stats`、`upsert_event`
- 事件索引：event_id / source_id / classification / news_value_score 索引字段
- 异步写入：`aiosqlite` 驱动

| ID | 内容 | 输出物 | 依赖 | 规模 | 验收点 | 状态 |
|----|------|--------|------|------|--------|------|
| P26.01 | AsyncStore 完整查询 | `core/async_store.py` 扩展 | Phase 25 | M | 分页查询+聚合统计+按源/分类过滤 | ✅ |
| P26.02 | pipeline 集成写入 | `core/async_run.py` 集成 | P26.01 | S | 每个 pipeline 阶段结束后写入事件索引 | ✅ |

### Phase 27 · AI Batch & Cache ✅

**目标：** AI 调用性能优化：批处理合并请求、LRU 缓存避免重复调用、分级路由减少大模型开销。

**核心交付：**
- `ai_batch.py` — AI 请求批处理队列（合并同类 prompt）
- `ai_cache.py` — LRU 缓存（prompt hash → AI 响应，TTL 可配）
- `TieredConfidenceRouter` — 基于 confidence 分级选择模型（高置信→跳过，中→小模型，低→大模型）
- 1402 tests → 1402 tests（+质量改进）

| ID | 内容 | 输出物 | 依赖 | 规模 | 验收点 | 状态 |
|----|------|--------|------|------|--------|------|
| P27.01 | AI 批处理队列 | `core/ai_batch.py` | — | M | 同类 prompt 合并，减少 API 调用次数 | ✅ |
| P27.02 | AI LRU 缓存 | `core/ai_cache.py` | — | S | 重复 prompt 命中缓存，跳过 API 调用 | ✅ |
| P27.03 | 分级置信度路由 | `confidence_router.py` TieredConfidenceRouter | P27.01 | M | confidence ≥0.85 跳过 LLM，0.5-0.85 小模型，<0.5 大模型 | ✅ |
| P27.04 | 集成到 pipeline | `async_run.py` 集成 | P27.01-03 | S | 批处理+缓存+分级路由端到端验证 | ✅ |

### Phase 28 · API Server SQLite ✅

**目标：** API Server 从全文件扫描重构为 SQLite 查询，ConfigCache TTL 避免重复 YAML 读取。

**核心交付：**
- `AsyncStore.query_events_paginated` / `get_stats_aggregated` / `get_event_file_path`
- `ConfigCache` — `cachetools.TTLCache` 封装 YAML 读取（60s TTL）
- API 端点 SQLite-first + 文件扫描 fallback（优雅降级）
- `POST /api/v1/config/reload` 热重载端点
- 1402 tests → 1426 tests

| ID | 内容 | 输出物 | 依赖 | 规模 | 验收点 | 状态 |
|----|------|--------|------|------|--------|------|
| P28.01 | AsyncStore 事件索引查询 | `async_store.py` 新方法 | Phase 26 | S | 分页查询+聚合统计+文件路径查找 | ✅ |
| P28.02 | ConfigCache TTL | `core/config_cache.py` | — | S | YAML 读取 60s TTL 缓存 + reload 清除 | ✅ |
| P28.03 | API 端点 SQLite 集成 | `api_server.py` 重构 | P28.01-02 | M | get_stats/list_events/get_event SQLite-first | ✅ |
| P28.04 | Config reload 端点 | `POST /api/v1/config/reload` | P28.02 | S | 调用后缓存清除，下次请求读取最新配置 | ✅ |
| P28.05 | SQLite 查询测试 | `test_api_server.py` 扩展 | P28.03 | S | SQLite 模式下各端点正确返回 | ✅ |
| P28.06 | async_run event_index 写入 | `async_run.py` 输出阶段集成 | P28.01 | S | pipeline 完成后写入事件索引 | ✅ |

### Phase 29 · Multi-target Concurrency ✅

**目标：** 多目标并发调度，FairScheduler 保证资源公平分配，CLI 支持批量运行和循环模式。

**核心交付：**
- `scheduler.py` — FairScheduler（两级 Semaphore：per-target + global）
- `--target all` 批量运行所有 target
- `--target italy,china-watch-en` 逗号分隔多目标
- `--interval N` 循环运行模式（分钟级）
- `run_loop_async` 无限循环 + max_iterations 限制
- 1426 tests → 1467 tests

| ID | 内容 | 输出物 | 依赖 | 规模 | 验收点 | 状态 |
|----|------|--------|------|------|--------|------|
| P29.01 | FairScheduler | `core/scheduler.py` | — | M | 两级并发控制，无饥饿，资源公平分配 | ✅ |
| P29.02 | 多目标并发运行 | `async_run.py` bounded_run_multi_async | P29.01 | L | asyncio.gather 并发多 target，共享 httpx client | ✅ |
| P29.03 | CLI --target 扩展 | `cli/__init__.py` | P29.02 | S | --target all / 逗号分隔 / 单目标三模式 | ✅ |
| P29.04 | CLI --interval 循环模式 | `cli/__init__.py` --interval | P29.03 | S | N 分钟间隔循环运行，max_iterations 限制 | ✅ |
| P29.05 | 多目标测试 | `test_multi_target.py` | P29.02 | M | 并发调度 + FairScheduler + 资源隔离验证 | ✅ |
| P29.06 | CLI 多目标测试 | `test_cli_multi_target.py` | P29.03-04 | S | CLI 参数解析 + 调度逻辑验证 | ✅ |

---

## §26. v1.3.0 — 多语言 NLP 深度分析

| Phase | 名称 | 核心交付 | 规模 | 状态 |
|-------|------|---------|------|------|
| Phase 30 | Multi-language NLP Analysis | NLPAnalysis 模型 + 规则引擎 + AI 升级 + async_run 集成 | L | ✅ |

### Phase 30 · Multi-language NLP Analysis ✅

**目标：** 在 JudgeResult 基础上扩展 4 个 NLP 维度（情感/实体/主题标签/事件关联），规则引擎零成本基线 + AI 按需升级。

**核心交付：**
- `NLPAnalysis` 模型 — Sentiment 枚举 + NLPEntity + topic_tags + event_relations
- `NLPRulesAnalyzer` — 情感词典词频 + 实体词典匹配 + classification 主题标签
- `NLPAIAnalyzer` — ProviderRouter task_type="nlp" LLM 升级
- `NLPAnalyzer` 编排器 — 规则→升级检查→AI，stats 追踪
- 5 种语言情感/实体词典（it/en/ja/de/fr）
- sentiment_score 不再硬编码 0.0，由 NLP 分析器写入
- 1467 tests → 1504 tests, 92% coverage

| ID | 内容 | 输出物 | 依赖 | 规模 | 验收点 | 状态 |
|----|------|--------|------|------|--------|------|
| P30.01 | NLP 模型扩展 | `models/newsevent.py` Sentiment/NLPEntity/NLPAnalysis | — | S | 10 模型测试通过 | ✅ |
| P30.02 | NLP 配置文件 | `config/nlp/sentiment/*.yaml` + `entities/*.yaml` | — | M | 5 语言 × 2 类型 = 10 YAML | ✅ |
| P30.03 | NLPRulesAnalyzer | `core/nlp_rules.py` | P30.01, P30.02 | M | 13 规则引擎测试通过 | ✅ |
| P30.04 | NLPAIAnalyzer | `core/nlp_ai.py` | P30.01 | M | 7 AI 升级测试通过 | ✅ |
| P30.05 | NLPAnalyzer 编排器 | `core/nlp_analyzer.py` | P30.03, P30.04 | M | 7 编排器测试通过 | ✅ |
| P30.06 | 集成 + 路由 + 修复 | `async_run.py` + `routes.yaml` + `rules_judge.py` + schema | P30.05 | S | 全量 1504 tests 通过 | ✅ |
| P30.07 | 验证与清理 | development-plan.md 更新 | P30.06 | S | ruff=0, mypy=0, 92% coverage | ✅ |

### Phase 31 · NLP API + SQLite 索引增强 ✅

**目标：** 打通 frontmatter → SQLite → API 三层，让 Phase 30 产出的 NLP 数据完全可查询可消费。

**核心交付：**
- Frontmatter 写入完整 NLPAnalysis（sentiment/nlp_entities/topic_tags/event_relations）
- SQLite event_index 增加 sentiment/entity_names/topic_tags 窄列 + migration + 索引
- API `/api/v1/events` 支持 sentiment/entity/topic_tag 过滤参数
- API `/api/v1/stats` 返回 sentiment_breakdown 分布
- 1504 tests → 1511 tests, 92% coverage

| ID | 内容 | 输出物 | 依赖 | 规模 | 验收点 | 状态 |
|----|------|--------|------|------|--------|------|
| P31.01 | Frontmatter NLP 写入 | `markdown_writer.py` | P30 | S | 3 frontmatter 测试通过 | ✅ |
| P31.02 | SQLite 加列 + Migration | `async_store.py` DDL + migration + upsert | P30 | M | ruff=0, mypy=0, 零破坏 | ✅ |
| P31.03 | SQLite 查询扩展 | `async_store.py` 过滤 + stats | P31.02 | M | NLP 过滤 + sentiment_breakdown | ✅ |
| P31.04 | API Server 扩展 | `api_server.py` 过滤参数 + stats | P31.03 | M | 4 API 测试通过 | ✅ |
| P31.05 | 验证与清理 | development-plan.md 更新 | P31.04 | S | 1511 tests, ruff=0, mypy=0, 92% | ✅ |

---

### Phase 32 · Entity Tracking & Cross-Reference ✅

**目标：** 将 NLP 实体从一次性提取升级为跨 run 持久化追踪，支持累计统计和 API 查询。

**核心交付：**
- SQLite 新增 `entities` 表（UNIQUE 去重 + mention_count 累计）
- `upsert_entity()` 原子操作：INSERT ON CONFLICT DO UPDATE
- `query_entities()` + `query_entity_detail()` 支持过滤/排序
- API `GET /entities` + `GET /entities/{id}` + `stats.top_entities`
- async_run 集成：NLP 增强后自动持久化实体
- 1511 tests → 1527 tests, 92% coverage

| ID | 内容 | 输出物 | 依赖 | 规模 | 验收点 | 状态 |
|----|------|--------|------|------|--------|------|
| P32.01 | entities 表 + upsert_entity | `async_store.py` DDL + 方法 | P31 | M | 5 entity tests, ON CONFLICT 去重 | ✅ |
| P32.02 | entity 查询方法 | `async_store.py` query + stats | P32.01 | M | 5 query tests, top_entities | ✅ |
| P32.03 | API entity 端点 | `api_server.py` 2 新端点 + StatsResponse | P32.02 | M | 5 API tests | ✅ |
| P32.04 | async_run 集成 | `async_run.py` store 参数 + 持久化 | P32.01 | S | 1 集成 test | ✅ |
| P32.05 | 验证与清理 | development-plan.md 更新 | P32.03, P32.04 | S | 1527 tests, ruff=0, mypy=0, 92% | ✅ |

### Phase 33 · Web UI NLP + Entity 可视化 ✅

**目标：** 将 Phase 30-32 的 NLP/Entity 数据接入 Web UI，让用户可通过浏览器直接消费。

**核心交付：**
- ES Modules 拆分：1131 行 app.js → api.js + pages/dashboard.js + pages/events.js + pages/config.js + app.js 入口
- Dashboard 增强：sentiment_breakdown 条形图 + top_entities 高频实体列表
- 事件列表 NLP 筛选：sentiment 下拉 + entity 搜索 + topic_tag 搜索
- 事件卡片/详情增强：sentiment 色标点 + entity chips + NLP 分析区域
- Entity 浏览页：#/entities 列表（筛选+分页）+ #/entities/{id} 详情（关联事件）
- 1527 tests, ruff=0, mypy=0, 92% coverage

| ID | 内容 | 输出物 | 依赖 | 规模 | 验收点 | 状态 |
|----|------|--------|------|------|--------|------|
| P33.01 | ES Modules 拆分 | api.js + pages/*.js + app.js 入口 | P32 | M | 1527 tests, 零功能变化 | ✅ |
| P33.02 | Dashboard + Events NLP | dashboard.js + events.js + style.css | P33.01 | L | 情感图/实体列表/筛选/卡片增强/详情NLP | ✅ |
| P33.03 | Entity 浏览页 | entities.js + index.html + app.js + style.css | P33.01 | M | 列表筛选 + 详情关联事件 | ✅ |
| P33.04 | 验证与清理 | development-plan.md 更新 | P33.02, P33.03 | S | 1527 tests, ruff=0, mypy=0, 92% | ✅ |

### Phase 34 · 运维仪表盘 + Pipeline 控制 ✅

**目标：** 将 RunLog、信源健康等运维数据通过 API 暴露，在 Web UI 中可视化，支持从 UI 手动触发采集。

**核心交付：**
- AsyncStore 批量信源健康查询 `get_all_source_health()`
- 5 个新 API 端点：运行历史列表、运行详情、活跃运行心跳、信源健康、Pipeline 触发
- Web UI 运维总览页（#/ops）：运行历史 + 信源健康 + 触发/重载操作
- Web UI 运行详情页（#/ops/{run_id}）：阶段执行 + 汇总 + 错误
- 1527 tests → 1535 tests, ruff=0, mypy=0, 92% coverage

| ID | 内容 | 输出物 | 依赖 | 规模 | 验收点 | 状态 |
|----|------|--------|------|------|--------|------|
| P34.01 | 批量信源健康查询 | async_store.py + 测试 | P33 | S | 2 新测试, 1529 tests | ✅ |
| P34.02 | API 运维端点 | api_server.py 5 端点 + 测试 | P34.01 | M | 6 新测试, 1535 tests | ✅ |
| P34.03 | 前端运维页面 | ops.js + app.js + index.html + style.css | P34.02 | M | 运维总览 + 运行详情 | ✅ |
| P34.04 | 验证与清理 | development-plan.md 更新 | P34.03 | S | 1535 tests, ruff=0, mypy=0, 92% | ✅ |

### Phase 35 · 事件追踪链 ✅

**目标：** 自动发现事件间关联关系，支持追踪链浏览和时间线展示。

**核心交付：**
- AsyncStore event_links 表 + 4 个关联查询方法
- _link_events 协程集成到 async_run pipeline
- 3 个新 API 端点：事件关联 /events/{id}/links、追踪链 /events/{id}/chain、链列表 /chains
- Web UI 追踪链页面（#/chains + #/chains/{id}）+ 事件详情关联卡片
- 时间线 CSS 组件 + 链列表表格

| ID | 内容 | 输出物 | 依赖 | 规模 | 验收点 | 状态 |
|----|------|--------|------|------|--------|------|
| P35.01 | event_links 表 | async_store.py + 测试 | P34 | M | 新表 + 4 查询方法 | ✅ |
| P35.02 | Pipeline 集成 | async_run.py _link_events | P35.01 | S | judge 后自动关联 | ✅ |
| P35.03 | API 端点 | api_server.py 3 端点 + 测试 | P35.01 | M | links/chain/chains | ✅ |
| P35.04 | 前端页面 | chains.js + events.js + style.css + index.html + app.js | P35.03 | M | 追踪链列表 + 详情 + 关联卡片 | ✅ |

### Phase 36 · AI 叙述引擎 ✅

**目标：** 基于追踪链事件序列，由 AI 自动生成连贯的事件叙述文本，支持前端展示与一键重新生成。

**核心交付：**
- AsyncStore chain_narratives 表 + narrative CRUD 方法
- _generate_narrative 协程集成到 async_run pipeline
- 2 个新 API 端点：GET/POST /chains/{id}/narrative
- Web UI 叙述卡片（链详情页）+ 链列表叙述摘要列
- 叙述卡片 CSS 样式

| ID | 内容 | 输出物 | 依赖 | 规模 | 验收点 | 状态 |
|----|------|--------|------|------|--------|------|
| P36.01 | chain_narratives 表 | async_store.py + 测试 | P35 | M | 新表 + narrative 方法 | ✅ |
| P36.02 | Pipeline 集成 | async_run.py _generate_narrative | P36.01 | S | chain 完成后自动生成叙述 | ✅ |
| P36.03 | API 端点 | api_server.py 2 端点 + 测试 | P36.01 | M | GET/POST narrative | ✅ |
| P36.04 | 前端叙述展示 | chains.js + style.css | P36.03 | M | 叙述卡片 + 链列表摘要 | ✅ |

### Phase 37 · 量化趋势分析 ✅

> 设计: docs/plan-phase-37-trends.md | 实现: docs/plan-phase-37-impl.md

**目标：** Dashboard 缺乏趋势维度，用户无法感知"主题热度上升/下降""情感波动"。引入按天聚合查询 + Chart.js 趋势可视化。

**核心交付：**
- AsyncStore 3 个聚合方法：get_sentiment_daily_counts、get_topic_daily_counts、get_top_topics
- TrendAnalyzer 新增 compute_topic_trends()：分割 current/prev 区间，计算 rising/stable/falling 方向和 hotness
- 2 个新 API：GET /trends/topics、GET /trends/sentiment
- Web UI trends.js 页面（Chart.js 折线图 + 主题排行榜）+ 导航入口
- Chart.js CDN 集成 + trends 页面 CSS 样式

| ID | 内容 | 输出物 | 依赖 | 规模 | 验收点 | 状态 |
|----|------|--------|------|------|--------|------|
| P37.01 | 数据层 + 趋势计算 | async_store.py + trend_analyzer.py + 测试 | P36 | M | 3 聚合方法 + compute_topic_trends | ✅ |
| P37.02 | API 端点 | api_server.py 2 端点 + 测试 | P37.01 | M | GET /trends/topics & /trends/sentiment | ✅ |
| P37.03 | 前端趋势页 | trends.js + style.css + app.js + index.html | P37.02 | M | Chart.js 折线/面积图 + 主题排行 | ✅ |

### Phase 38 · 智能告警 2.0 ✅

> 设计: docs/plan-phase-38-smart-alerts.md | 实现: docs/plan-phase-38-impl.md

**目标：** 原有告警仅基于阈值触发，无法感知"链更新""趋势变化""实体突增"等复合信号。引入 3 类智能告警 + N+1 查询修复。

**核心交付：**
- AsyncStore get_recent_links + get_entity_daily_mentions + 6 个 SQLite 索引
- AlertPipeline.check_smart_alerts()：chain_update、trend_rising、entity_spike
- async_run _run_judge_async 集成智能告警检查（非阻塞 try/except）
- GET /api/v1/alerts/smart REST 端点
- chains.js N+1 修复（narrative_summary 内嵌替代逐链 API 调用）
- 运维详情页智能告警卡片

| ID | 内容 | 输出物 | 依赖 | 规模 | 验收点 | 状态 |
|----|------|--------|------|------|--------|------|
| P38.01 | 数据层 + 索引 | async_store.py 2 方法 + 6 索引 + 测试 | P37 | M | 3 告警查询方法 | ✅ |
| P38.02 | 告警逻辑 + Pipeline 集成 | alert_pipeline.py + async_run.py + 测试 | P38.01 | M | check_smart_alerts + pipeline 集成 | ✅ |
| P38.03 | API + 前端 | api_server.py + chains.js + ops.js + 测试 | P38.02 | M | GET /alerts/smart + 告警卡片 + N+1 Fix | ✅ |

### Phase 39 · Dashboard 增强 ✅

> 设计: docs/plan-phase-39-dashboard.md

**目标：** Dashboard 仅展示全时间聚合，缺少时间维度。增加今日/昨日对比、近期高价值事件 Top5、趋势概览。

**核心交付：**
- AsyncStore get_today_stats()（今日 vs 昨日）+ get_top_events()（7 天分数降序）
- 2 个新 API：GET /stats/today、GET /events/top
- dashboard.js 新增今日对比卡片行（含涨跌箭头）+ Top5 事件表 + 趋势概览 badges
- 今日对比卡片 CSS 样式

| ID | 内容 | 输出物 | 依赖 | 规模 | 验收点 | 状态 |
|----|------|--------|------|------|--------|------|
| P39.01 | 后端 | async_store.py + api_server.py + 测试 | P38 | M | 2 数据库方法 + 2 API | ✅ |
| P39.02 | 前端 | dashboard.js + style.css | P39.01 | S | 今日对比 + Top5 + 趋势概览 | ✅ |

### Phase 40 · 治理积压清理 ✅

> 设计: docs/plan-phase-40-governance.md

**目标：** 数据保留清理、source health 自动降级、SQLite 自动备份——治理 backlog 中最紧迫的 3 项。

**核心交付：**
- AsyncStore prune_old_data()（级联删除过期事件 + 孤儿 links + 旧 known_ids）
- AsyncStore backup_db()（VACUUM INTO 一致性备份，保留最近 7 份）
- SourceHealthChecker _degradation_policy()（3 次→degraded，7+次→unreachable）
- 2 个 maintenance API：POST /maintenance/prune、POST /maintenance/backup
- async_run 每 10 次 run 自动触发 prune（try/except 非阻塞）

| ID | 内容 | 输出物 | 依赖 | 规模 | 验收点 | 状态 |
|----|------|--------|------|------|--------|------|
| P40.01 | 后端全栈 | async_store.py + source_health_checker.py + api_server.py + async_run.py + 测试 | P39 | M | prune + backup + 降级 + 2 API | ✅ |

### Phase 41 · 反馈闭环 + 告警管理 ✅

> 设计: docs/plan-phase-41-feedback-alerts.md

**目标：** Phase 20 的 FeedbackCollector + RulesOptimizer 无 API 暴露、无 UI 入口。Phase 38 的智能告警无独立管理页。实现反馈闭环（事件详情提交→规则优化）和独立告警管理页。

**核心交付：**
- AsyncStore feedback 表 + alert_history 表 + 5 个 CRUD 方法
- AlertPipeline.check_smart_alerts 自动写入 alert_history 持久化
- 5 个 REST API：POST/GET /feedback、GET /feedback/stats、POST /rules/optimize、GET /alerts/history
- Web UI alerts.js（活跃告警 + 历史告警 + 统计）+ feedback.js（统计 + 反馈列表 + 规则优化预览/应用）
- 事件详情页反馈按钮（推荐发布/归档/评论）
- 导航栏新增「告警中心」「反馈管理」两项

| ID | 内容 | 输出物 | 依赖 | 规模 | 验收点 | 状态 |
|----|------|--------|------|------|--------|------|
| P41.01 | 后端 | async_store.py + alert_pipeline.py + api_server.py + 测试 | P40 | M | 2 表 + 6 方法 + 5 API + 11 tests | ✅ |
| P41.02 | 前端 | alerts.js + feedback.js + events.js + app.js + index.html + style.css | P41.01 | M | 3 页面/功能 | ✅ |

### Phase 42 · 配置编辑 ✅

> 设计: docs/plan-phase-42-config-edit.md

**目标：** 5 个配置页面（Target/Source/Filter/Output/Provider）全部只读——用户在 UI 查看配置后仍需 SSH 手动编辑 YAML。实现 Web UI 配置编辑闭环。

**核心交付：**
- 5 个 config write 端点（PUT /config/targets/{id}、PATCH /config/.../sources/{id}、PATCH /config/.../filters、PATCH /config/output/destinations/{id}、PATCH /config/provider/routes/{id}）
- deep_merge + atomic_write_yaml（UUID tmp + os.replace）工具函数
- api.js 新增 apiPut/apiPatch/showSuccess
- 5 个配置页全部转为可编辑表单（input/select/toggle/关键词增删）+ 保存按钮
- 编辑表单 CSS 样式

| ID | 内容 | 输出物 | 依赖 | 规模 | 验收点 | 状态 |
|----|------|--------|------|------|--------|------|
| P42.01 | 后端 | api_server.py 5 端点 + deep_merge + atomic_write + 测试 | P41 | M | 5 写入端点 + 6 tests | ✅ |
| P42.02 | 前端 | api.js + config.js + style.css | P42.01 | L | 5 可编辑配置页 | ✅ |

---

### Phase 53 · Windows 安装支持 ✅

**目标：** 实现 Windows 平台安装支持，包括 install/uninstall 命令 PowerShell 脚本、kill 命令跨平台适配、代码清理。

**核心交付：**
- 32fc8f3 Windows 安装脚本 (`install.ps1` + `install.sh` --windows 模式)
- kill 命令提取复用代码（减少 39 行重复）
- 遗留 `scripts/` 目录清理
- P2 通知设置 JSON → SQLite 迁移
- P3 AI prompt 消毒 + conftest 共享 fixtures + Docker HEALTHCHECK + logrotate
- P2 Token 持久化 + run.py/async_run.py 共享初始化提取
- P0/P1 架构缺陷批量修复 + ADR 目录纳入版本追踪
- api_server.py 57 个 mypy 类型错误修复 (dict → dict[str, Any])

| ID | 内容 | 输出物 | 规模 | 状态 |
|----|------|--------|------|------|
| P53.01 | Windows install 脚本 | `install.ps1` + `install.sh` 扩展 | M | ✅ |
| P53.02 | kill 命令跨平台 | kill.py 去重 + 39 行精简 | S | ✅ |
| P53.03 | 遗留 scripts/ 清理 | 目录删除 | S | ✅ |
| P53.04 | 通知设置 JSON→SQLite | 数据迁移 | M | ✅ |
| P53.05 | AI prompt 消毒 + 共享 fixtures | conftest.py 重构 | M | ✅ |
| P53.06 | Docker HEALTHCHECK + logrotate | 容器监控 | S | ✅ |
| P53.07 | Token 持久化 | run.py/async_run.py 共享初始化 | M | ✅ |
| P53.08 | P0/P1 架构缺陷批量修复 | ADR 目录追踪 | L | ✅ |
| P53.09 | mypy 类型修复 | 57 errors → 0 | M | ✅ |

### Phase 54 · 质量加固 ✅

**目标：** 集中修复 Store 初始化问题、同步 AGENTS.md 架构文档、提升 markdown_writer 测试覆盖率至 100%。

**核心交付：**
- `create_app()` 同步初始化兜底（Store None → 503 降级）
- 只读数据端点 store 不可用时返回空结果而非 503
- AGENTS.md 全面翻新 + Mermaid 架构图
- markdown_writer 100% 测试覆盖
- 文档自然语言重写第一阶段

| ID | 内容 | 输出物 | 规模 | 状态 |
|----|------|--------|------|------|
| P54.01 | Store 初始化修复 | `api_server.py` create_app 同步兜底 | M | ✅ |
| P54.02 | 端点优雅降级 | 503 → [] 空结果返回 | M | ✅ |
| P54.03 | AGENTS.md 翻新 + Mermaid | 架构图重绘 | L | ✅ |
| P54.04 | markdown_writer 100% 覆盖 | 测试扩展 | M | ✅ |

### Phase 55 · 桌面壳 (pywebview + PWA + SSE) ✅

**目标：** 将 Web UI 封装为桌面原生窗口应用，支持 PWA 离线访问、SSE 实时推送，提供接近原生桌面应用的体验。

**核心交付：**
- `news-sentry desktop` 命令 — pywebview 6.x API 封装 Web UI
- 系统托盘图标 + 菜单（显示/隐藏/退出）
- 窗口配置持久化（位置/大小/是否最大化）
- PWA 支持：`manifest.json` + Service Worker + 离线缓存 + 桌面图标
- SSE 实时事件推送：`GET /api/v1/events/stream`
- 前端 EventSource 连接 + 实时事件卡片
- 浏览器桌面通知（SSE 事件 → Notification API）
- Gtk macOS 窗口适配
- mypy 零错误贯穿

| ID | 内容 | 输出物 | 规模 | 状态 |
|----|------|--------|------|------|
| P55.01 | pywebview 桌面壳 | `cli/desktop.py` + `core/desktop_app.py` | L | ✅ |
| P55.02 | 系统托盘 | 窗口隐藏/显示 + 退出 | M | ✅ |
| P55.03 | 窗口配置持久化 | JSON 保存/恢复 | S | ✅ |
| P55.04 | PWA 支持 | manifest.json + sw.js + 离线缓存 | M | ✅ |
| P55.05 | SSE 端点 | `GET /api/v1/events/stream` | M | ✅ |
| P55.06 | 前端 SSE 连接 | EventSource + 实时卡片 + 桌面通知 | M | ✅ |
| P55.07 | Gtk macOS 适配 | 窗口标题 + 最小大小 | S | ✅ |
| P55.08 | mypy 零错误 | 全类型检查通过 | M | ✅ |
| P55.09 | PRD 完成 | 全部 6 US + 质量审查 | M | ✅ |

### Phase 56 · 技术债清理 Sprint ✅

**目标：** 集中清理 known-issues.md 中积累的技术债，使 CI 全绿、端点优雅降级、日志可观测。

**核心交付：**
- test_async_run.py 2 个持久失败修复（patch 目标 `async_run`→`run`）
- 5 个读端点 503 → 优雅降级（趋势×2、智能告警、用户列表、API Key 查询）
- 9 处静默 `except: pass` → logger.warning/debug
- `--log-level` 补齐 ERROR/CRITICAL
- 前端注释清理 + prd.json/progress.txt 入 .gitignore
- OpenClaw 枚举加注释说明
- known-issues.md 全部更新
- 1612 tests ✅, ruff=0

| ID | 内容 | 输出物 | 规模 | 状态 |
|----|------|--------|------|------|
| P56.01 | 静默异常加日志 | health_server + rss_collector + judge_skill | S | ✅ |
| P56.02 | 读端点优雅降级 | api_server.py 5 端点 | M | ✅ |
| P56.03 | 日志级别补齐 | cli/__init__.py | S | ✅ |
| P56.04 | 清理工件 | .gitignore + ops.js | S | ✅ |
| P56.05 | OpenClaw 枚举注释 | manifests.py | S | ✅ |
| P56.06 | known-issues 更新 | known-issues.md | S | ✅ |

### Phase 57 · 桌面壳跨平台适配 ✅

**目标：** 将 pywebview 桌面壳从 macOS-only 扩展为 macOS/Linux/Windows 三平台可用，并支持 PyInstaller 打包、开机自启动、原生通知、自动更新检测。

**核心交付：**
- Linux 桌面适配：`_os_info()` 跨平台信息 + 统一 `os._exit()` 退出 + xdg-open 已覆盖
- Windows 系统托盘验证：`_on_quit` 加 `_stop_tray()` 清理 + `pywin32` 依赖
- Pillow 显式依赖加入 desktop extras
- PyInstaller 打包：`news-sentry.spec` onefile 配置，27MB arm64 macOS 构建成功
- 开机自启动：`desktop --autostart/--no-autostart`，macOS LaunchAgent + Linux XDG autostart + Windows 注册表
- 桌面通知统一：pywebview JS bridge `_NativeNotifyApi` + 前端 Notification API 降级
- 自动更新检测：GitHub Releases API 检查新版本 + CLI 提示 + 前端更新横幅

| ID | 内容 | 输出物 | 规模 | 状态 |
|----|------|--------|------|------|
| P57.01 | Linux 桌面适配 | desktop.py `_os_info()` + 统一退出 | M | ✅ |
| P57.02 | Windows 系统托盘验证 | desktop.py `_on_quit` 清理 + pywin32 依赖 | M | ✅ |
| P57.03 | PyInstaller 打包 | news-sentry.spec onefile | L | ✅ |
| P57.04 | 开机自启动配置 | desktop --autostart 三平台 | M | ✅ |
| P57.05 | 桌面通知统一 | JS bridge 原生通知 + 前端降级 | M | ✅ |
| P57.06 | 自动更新检测 | GitHub Releases + 横幅 | S | ✅ |

### Phase 58 · 本地客户端体验打磨 ✅

**目标：** 根据 ADR-0026 Phase 1 路线，继续打磨 pywebview 桌面客户端到「本地完全体」，聚焦前端交互增强 + 桌面体验闭环 + 测试覆盖提升。

**核心交付：**
- test_api_server 挂起修复：aiosqlite 跨 event loop 根因 + async/AsyncClient 统一 + skip_lifespan 参数
- SSE 断线重连：指数退避手动重连 + 连接状态指示器（顶部 3px 横条）
- 桌面快捷键绑定：全局导航 + 页面内操作
- PWA offline 增强：缓存策略 + 离线提示
- 前端代码拆分：app.js / style.css 模块化

| ID | 内容 | 输出物 | 规模 | 状态 |
|----|------|--------|------|------|
| P58.01 | 修复 test_api_server 挂起 | async/AsyncClient 统一 + skip_lifespan | L | ✅ |
| P58.02 | SSE 断线重连 + 状态指示器 | 指数退避 + 顶部状态条 | M | ✅ |
| P58.03 | 桌面快捷键绑定 | 全局导航 + 页面内操作 | M | ✅ (已有完整实现) |
| P58.04 | PWA offline 增强 | 缓存策略 + 离线提示 | M | ✅ |
| P58.05 | 前端代码拆分 | app.js/style.css 模块化 | L | ⬜ |


### Phase 59 · 前端模块化重构 + 代码质量 ✅

**目标：** CSS 目录索引 + 开发计划状态同步更新。

**核心交付：**
- CSS 目录索引：`style.css` 添加 TOC 目录注释，便于大型 CSS 文件导航
- 开发计划 v2.9 状态同步更新

| ID | 内容 | 输出物 | 规模 | 状态 |
|----|------|--------|------|------|
| P59.01 | CSS 目录索引 | style.css TOC 注释 | S | ✅ |

### Phase 60 · CI 修复 + PyPI 发布工作流 ✅

**目标：** 修复 CI 环境下 mypy 类型检查失败，并建立 tag 驱动的自动 PyPI 发布流程。

**核心交付：**
- CI mypy `--ignore-missing-imports` — 匹配本地开发配置，解决 CI 无 pywebview/pystray 时的 import 错误
- GitHub Actions release workflow — tag 发布自动构建 + PyPI publish (Trusted Publisher)
- desktop.py type: ignore 兼容 CI（通用 suppress）
- pyproject.toml mypy 禁用 `warn_unused_ignores`

| ID | 内容 | 输出物 | 规模 | 状态 |
|----|------|--------|------|------|
| P60.01 | CI mypy 兼容修复 | ci.yml + pyproject.toml + desktop.py | M | ✅ |
| P60.02 | PyPI 发布工作流 | .github/workflows/release.yml | M | ✅ |

### Phase 61 · 本地客户端发布准备 🔧

**目标：** 打磨本地客户端到可分发状态，完成 CI 多平台构建 + GitHub Release 分发。

**核心交付：**
- CI 多平台构建: macOS arm64 + Windows x64 + Linux x64 PyInstaller onefile
- doctor --target 硬编码消除
- create_app() 退出挂起修复（aiosqlite daemon thread）
- GitHub Release 自动上传构建产物

| ID | 内容 | 输出物 | 规模 | 状态 |
|----|------|--------|------|------|
| P61.01 | CI 多平台 PyInstaller 构建 | release.yml 扩展 | M | ✅ |
| P61.02 | doctor --target 默认值修复 | cli/__init__.py | S | ✅ |
| P61.03 | create_app 退出挂起修复 | async_store.py monkey-patch | M | ✅ |
| P61.04 | lifespan shutdown store.close() | api_server.py | S | ✅ |

### Phase 62 · 桌面客户端体验完善 ✅

**目标：** 新用户首次启动体验 + 桌面应用图标 + 基础引导。

| ID | 内容 | 输出物 | 规模 | 状态 |
|----|------|--------|------|------|
| P62.01 | 应用图标 (.ico/.icns/.svg) | static/icons/ | S | ✅ |
| P62.02 | PyInstaller spec 引用图标 | news-sentry.spec | S | ✅ |
| P62.03 | 首次启动引导（创建管理员账户） | 前端引导页 | M | ⬜ |
| P62.04 | dark mode 支持 | style.css + CSS 变量 | L | ✅ |
| P62.05 | desktop.py 测试覆盖提升 (17%→60%+) | test_desktop.py | L | ⬜ |

### Phase 63 · 自动更新与分发 ✅

**目标：** 实现桌面应用自动更新机制。

| ID | 内容 | 输出物 | 规模 | 状态 |
|----|------|--------|------|------|
| P63.01 | 更新清单文件 (update manifest) | update.json on GitHub | S | ✅ |
| P63.02 | 桌面应用自动下载更新 | desktop.py 更新逻辑 | L | ✅ |
| P63.03 | Windows 代码签名（可选） | signtool | M | ⬜ |
| P63.04 | macOS 公证（可选） | notarytool | M | ⬜ |

### Phase 64 · 前端功能补齐 ✅

**目标：** 补齐前端缺失功能入口。

| ID | 内容 | 输出物 | 规模 | 状态 |
|----|------|--------|------|------|
| P64.01 | 数据备份/恢复 UI | settings.js | M | ✅ |
| P64.02 | api_server.py 覆盖率提升 (73%→85%+) | test_api_server.py | L | ⬜ |
| P64.03 | 系统通知偏好设置 UI | settings.js | M | ⬜ |

### Phase 65 · v2.0 规划与 Tauri 原型 ✅

**目标：** 评估 Tauri 技术方案，制作最小原型验证可行性。

| ID | 内容 | 输出物 | 规模 | 状态 |
|
### Phase 66 · 质量打磨 + v1.8.0 发布 ✅

**目标：** 收尾 Phase 62-65 遗留项，提升测试覆盖，打磨发布质量，发布 v1.8.0。

**核心交付：**
- desktop.py 测试覆盖 17%→60%（桌面核心逻辑可验证）
- api_server.py 测试覆盖 73%→85%（备份/恢复/SSE/新端点）
- 首次启动引导页（创建管理员 → 进入主界面）
- Tauri vs pywebview 性能基准对比报告
- 版本 bump v1.8.0 + CHANGELOG + tag + release

| ID | 内容 | 输出物 | 依赖 | 规模 | 状态 |
|----|------|--------|------|------|------|
| P66.01 | desktop.py 测试覆盖提升 (17%→60%) | tests/unit/test_desktop.py | — | L | ⬜ |
| P66.02 | api_server.py 测试覆盖提升 (73%→85%) | tests/unit/test_api_server.py | — | L | ⬜ |
| P66.03 | 首次启动引导 | static/pages/setup.js + app.js 路由 | P66.01 | M | ⬜ |
| P66.04 | Tauri vs pywebview 性能基准 | docs/benchmark-tauri-vs-pywebview.md | P65 | S | ✅ |
| P66.05 | v1.8.0 发布 | pyproject.toml + CHANGELOG + tag + release | P66.01-04 | M | ✅ |


----|------|--------|------|------|
| P65.01 | Tauri + Rust 环境搭建 | Cargo.toml + tauri.conf.json | M | ✅ |
| P65.02 | 前端迁移验证 | 现有 SPA 在 Tauri webview 中运行 | M | ✅ |
| P65.03 | 原生 API 调用验证 | Tauri commands (系统托盘/通知/自启) | L | ✅ |
| P65.04 | 性能基准对比 | 启动时间/内存占用对比 pywebview | S | ⬜ |

---

## §25. Cloud VPS 部署方案推荐

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
| ADR-0023 | 内置 Web UI 随 Phase 31-42 演进为操作界面（嵌入 SPA 替代纯 Obsidian+推送终态）| Phase 31+ |
| ADR-0024 | Schema 版本治理策略 | Phase 47 |
| ADR-0025 | API Server 嵌入式 SPA 架构 (FastAPI + Vanilla JS) | Phase 50+ |
| ADR-0026 | 三阶段客户端架构演进路线 (pywebiew → Tauri → 云端集群+分布式) | Phase 56 |

---

## §17. 跨 Phase 治理 Backlog

> 不绑定具体 Phase，但必须在适当时机决策或实现。

| 编号 | 内容 | 建议决策/实现时机 |
|------|------|----------------|
| `CLI-001` | 决定 `python -m news_sentry.cli run` 的完整命令 schema（参数、子命令、输出格式）| ✅ Phase 47 已解决：Click 实现 5 子命令 (run/skill/tool/validate/doctor)，完整参数与退出码 |
| `LOCK-001` | 并发 Agent 写同一文件时的 lock/lease 机制设计 | ✅ Phase 47 关闭：SQLite WAL + asyncio.Lock 已覆盖，无需文件锁 |
| `EVAL-001` | AI Provider 离线 eval 集构建与评估流程（同一 judge 任务的多 Provider 质量对比） | ✅ Phase 47 已解决：run_eval.py 三种 mode (rules/ai/hybrid) 支持多轮对比 |
| `SCHEMA-VERSION-001` | `prompt_template_id` 和 `output_schema_id` 的版本治理（何时可以 deprecate 旧版本） | ✅ Phase 47 已解决：18 schema 均已有 $id/$schema，ADR-0024 记录版本策略 |
| `GLOSSARY-UPDATE-001` | `it-zh-glossary.md` 更新机制（判断新条目纳入阈值、格式、审核人）| ✅ Phase 47 已解决：doctor 命令新增术语表覆盖率检查 (69% eval coverage)，人工更新流程不变 |
| `HEALTH-POLICY-001` | source health 降级阈值（多少次失败后停止采集该信源，如何恢复） | Phase 40 已解决：>=3 degraded, >=7 unreachable |
| `MEMORY-RETENTION-001` | `known_item_ids` 保留策略（最大条目数、过期时间、清理方式）| Phase 40 已解决：prune_old_data 级联清理 |
| `ARCHIVE-POLICY-001` | `archive/` 中被拒事件的保留周期（多久清理或迁移到冷存储）| Phase 40 已解决：prune_old_data + max_age_days 参数 |
| `MATRIX-GOV-001` | 信源自进化机制的触发频率和审计策略 | Phase 46 已解决：JSONL 审计日志 + rss_discovery_cooldown_hours=168 (7d) |
| `SOCIAL-SESSION-001` | 社媒 session profile 的刷新周期和安全存储策略 | Phase 46 已解决：expires_at 90d TTL + is_expired/needs_review + load 自动跳过过期 |
| `BRIDGE-FALLBACK-001` | Computer Use 兜底的成本预算上限和告警阈值 | ✅ Phase 47 已解决：三层降级 + AI CostTracker 全局预算 + 每日次数上限 |
| `EVAL-002` | 评估集更新机制（何时触发重新标注、标注者间一致性度量） | ✅ Phase 47 已解决：手动 v1→v2→v3 流程已就位，按需扩展 |
| `DEPLOY-001` | Cloud VPS 部署的平台选择（GCP Cloud Run / AWS ECS / 自管 VM）和成本估算 | Phase 15 已决策：Hetzner CX32 |
| `AI-JUDGE-001` | AI Judge 置信度路由阈值（news_value_score 什么范围走规则 vs AI）| ✅ Phase 47 已解决：ConfidenceRouter (threshold=60) + TieredConfidenceRouter (0.85/0.5 三级) |
| `AI-JUDGE-002` | Hybrid 模式下 Rules→AI fallback 的判定逻辑 | ✅ Phase 47 已解决：_should_escalate 多条件升级 + AI 失败保留规则结果 |
| `ALERT-001` | 告警去重窗口和阈值配置策略 | Phase 17 已决策：24h 去重窗口，阈值通过 destinations.yaml filter 配置 |
| `MONITOR-001` | 监控方案选型（Prometheus vs 轻量自建） | Phase 34 已解决：自建运维仪表盘 |
| `BACKUP-001` | 数据备份保留策略和恢复测试 | Phase 40 已解决：VACUUM INTO + 保留最近 7 份 |

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
