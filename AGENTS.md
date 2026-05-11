# News Sentry Agent Instructions

## Project Mission

News Sentry is a framework-neutral Agent Skill Pack platform for continuous news monitoring. The first reference target is Italy, but core code and contracts must stay reusable for other countries, regions, and domains.

The production runtime priority is Hermes Agent first, OpenClaw/OpenClaw Skills/ClawHub second as the main Skill runtime and ecosystem compatibility layer. Codex Automations and Claude Desktop Cowork Scheduled Tasks are fallback automation surfaces for project maintenance, research reports, and human-reviewable summaries, not the 24-hour production monitoring backbone. A host should trigger bounded runs; the Skill Pack itself must not implement an unbounded daemon loop.

## Architecture Source Of Truth

Read these files before changing architecture, schemas, pipeline behavior, permissions, provider routing, or tool execution:

- `docs/contracts-canonical.md` — **口径规范基准**：字段命名、分值量纲、目录映射、pipeline_stage 枚举、产品命名、classification metadata schema 的唯一权威来源
- `docs/adr/` — 架构决策记录（ADR-0001 至 ADR-0016）
- `docs/spec/README.md` — **7 份 Phase SPEC 索引**：横切组件矩阵 + 演进图，每份 SPEC 是对应阶段实现的规格基准
- `docs/development-plan.md` — 七阶段开发计划与 TODO 矩阵（含 W10/W11 工作流）
- `schemas/` — **13 份 JSON Schema 2020-12**：机器可读契约，与 contracts-canonical.md 双向绑定（ADR-0014）
- `config/` — **运行时配置骨架**：意大利参数封装在 config/targets/italy.yaml，其他国家复制 _template.yaml（ADR-0015）
- `src/news_sentry/` — **Python 3.11+ stub 骨架**（ADR-0012、ADR-0013）
- `docs/external-integration-strategy.md` — **外部项目接入策略**：OpenCLI 接入原则、三原则、12 条 ToolManifest 骨架意图、舍弃清单
- `docs/reference-projects-insights.md` — **参考项目价值提取**：8 个外部项目的启发点与落地指针
- `docs/news-classification-framework.md` — **新闻分类框架**：L0–L3 taxonomy、Italy 子轴、metadata.classification 完整 schema
- `docs/datasets-catalog-italy.md` — **意大利数据集目录**：ISTAT/Eurostat/GDELT 等公开数据集的接入建议
- `docs/architecture-overview.md`
- `docs/integration-protocol.md`
- `docs/newsevent-schema.md`
- `docs/brainstorming/通用内核与平台化架构PRD.md`
- `docs/brainstorming/ToolManifest与工具适配层规格.md`
- `docs/brainstorming/AIProvider与模型路由规格.md`
- `docs/brainstorming/SandboxPolicy与执行权限规格.md`
- `docs/brainstorming/Hermes与OpenClaw运行载体规格.md`

## Core Decisions

- Keep the kernel framework-neutral. Hermes and OpenClaw integrations belong in runtime adapters or Skill wrappers, not in domain contracts; Codex, Claude Cowork, opencode, and Cursor belong to fallback automation or developer tooling.
- Treat Hermes as the primary orchestrator for long-running cron/gateway monitoring. Treat OpenClaw as the primary Skill runtime and ClawHub ecosystem compatibility surface.
- Do not treat Codex Automations or Claude Cowork Scheduled Tasks as production schedulers for 24-hour news monitoring.
- Use Obsidian/Git-friendly Markdown files with YAML frontmatter as the v1 storage surface.
- Use `NewsEvent` as the cross-agent data object. Do not introduce competing event schemas.
- Use deterministic `NewsEvent.id` for item identity and `run_id` for bounded execution identity. Use `cluster_id` or `story_id` for cross-source aggregation.
- Use 0-100 scores for `news_value_score`, `china_relevance`, confidence, source credibility, and value dimensions unless a documented field explicitly says otherwise. Note: `sentiment_score` is an explicit exception (-1.0 to 1.0); `ValueDimension.weight` is a percentage weight, not a score. See `docs/contracts-canonical.md §4`.
- Keep `judge_result.recommendation` inside `judge_result`; do not duplicate it as a top-level field.
- Keep static source configuration free of arbitrary shell commands. CLI/OpenCLI execution must go through `ToolManifest`, `tool_ref`, `binding_id`, `validated_args`, and sandbox checks.
- Do not store cookies, tokens, passwords, browser profile internals, API keys, or private-message content in `NewsEvent`, frontmatter, logs, or docs.
- v1 stops at drafts, reviewed files, and publish-ready archives. Do not implement automatic external publishing without an explicit new decision.
- For Italian-Chinese bilingual processing (意大利语→中文 SOP), see `docs/it-zh-bilingual-sop.md` and `docs/it-zh-glossary.md`. Canonical translated fields (`title_translated`, `content_translated`) are filled only at the judge stage; collect-stage pre-translations go into `metadata.translation.title_pre` only.
- **外部项目只 install 不 vendor**：OpenCLI 及所有外部项目通过系统包管理器安装，不 fork、不 vendor、不 Git submodule 引入本仓库。详见 `docs/external-integration-strategy.md` 和 ADR-0008。
- **永不做专用前端**：News Sentry 终态是 CLI / Skill Pack；可视化通过 Obsidian Markdown 渲染 + 飞书/邮件/推送承担。禁止引入 React/Vue/Tauri/FastAPI。详见 ADR-0010。
- **新闻分类走 metadata.classification，不做顶层字段**：L0–L3 taxonomy 结果写入 `NewsEvent.metadata.classification`，不进 schema 顶层。详见 `docs/news-classification-framework.md` 和 ADR-0009。
- **实现语言是 Python 3.11+**：`src/news_sentry/` 目录下所有模块使用 Python 3.11+，pydantic v2 作为数据模型层。详见 ADR-0012。
- **任务配置走 config/，禁止硬编码意大利参数到 src/**：所有与意大利相关的参数（语言、时区、源列表、关键词）封装在 `config/targets/italy.yaml`，切换国家只需复制 `config/targets/_template.yaml`，不改代码。详见 ADR-0015。
- **CLI 入口格式固定**：`python -m news_sentry.cli run --target {id} --stage {collect|filter|judge|output|all} --profile {profile_id}`；console script `news-sentry` 可用时等价，但开源文档优先使用 `python -m news_sentry.cli ...` 避免依赖本机 PATH。详见 ADR-0016。ADR-0006 的 CLI backlog（CLI-001）已关闭。
- **JSON Schema 是契约校验载体**：`schemas/` 下 13 份 JSON Schema 2020-12 与 `docs/contracts-canonical.md` 双向绑定，config YAML 文件头部注释 `# Schema:` 指向对应 schema。详见 ADR-0014。

## AI 辅助设计原则

以下原则源自 Karpathy 的"锯齿状智能"和"Iron Man 套装"心智模型，约束所有涉及 AI 组件的设计决策。

### 锯齿状智能应对

- LLM 能力分布非均匀：任何基于 LLM 的管道步骤必须识别已知凹陷点（数字/日期提取、跨语言实体对齐、极端情感判断），并为凹陷点加规则兜底
- 凹陷点不靠更大的模型解决，靠更窄的规则补丁
- 每个 AI 管道组件必须附带一份"已知失败模式"清单

### Iron Man 套装原则

- News Sentry 是"增强人工研判的套装"，不是"替代人工的机器人"
- 所有关键判断（news_value_score >= 80、publish gate）保留人工介入点
- Agent 编排中的角色：人是监督者，Agent 是执行者
- 完全自主能力（自动发布、自动封禁）不在 v1 范围

## 质量门槛

以下门槛源自 Karpathy 的"March of Nines"工程现实主义，任何 AI 管道组件上线前必须满足：

1. **尾部行为评估**：在最差 5% 输入场景下，组件输出不得产生静默错误
2. **置信度对齐**：`judge_result.confidence` 与实际准确率的偏差不超过 10%
3. **数据飞轮检查**：该组件是否持续积累反馈数据以自我改进？如否，需说明原因
4. **demo ≠ 部署**：任何基于单次 LLM 调用验证的"看起来能工作"不等于可部署

## Decision Checklist

每次重大技术决策（新增依赖、架构变更、管道设计、Agent 编排模式选择）前必须过：

1. [March of Nines] 这个方案在最差 5% 场景下会怎样？
2. [构建即理解] 我们能向新人解释清楚这个方案的核心原理吗？
3. [锯齿状智能] 我们依赖的 AI 能力在哪些维度可能有凹陷？
4. [Iron Man 套装] 关键决策点是否保留了人工介入？
5. [简洁优先] 资深工程师会认为这个方案过度复杂吗？

出现 ≥2 个 NO 时，方案必须重新设计。

## Phase Order

All seven phases (Phase 1-7) are complete. See docs/spec/README.md for detailed status.

1. Contract Stabilization ✅
2. Runtime Carrier Alignment ✅
3. Kernel MVP ✅
4. Tool/Skill Registry + OpenCLI ✅
5. AI Provider Routing ✅
6. Sandbox Hardening + Social/KOL Experiment ✅
7. Multi-target Expansion ✅

## File Event Protocol

Use the v1 directory protocol consistently:

- `raw/`: collected events
- `evaluated/`: filtered and judged events
- `drafts/`: editorial drafts
- `reviewed/`: human or internal-review candidates
- `published/`: approved archive or publish-ready files
- `archive/`: rejected, duplicate, low-value, or failed samples
- `memory/`: known IDs, source health, cursors, provider stats, KOL state
- `logs/`: bounded run logs, tool audit logs, provider usage logs

Directory state does not replace `NewsEvent.pipeline_stage`. Preserve `processing_history` when moving or enriching events. For the precise directory ↔ `pipeline_stage` mapping and the separation of `pipeline_stage` from `workflow_state` (editorial review flow), see `docs/contracts-canonical.md §5`.

## Development Workflow

- Inspect existing docs and contracts before implementing.
- Keep edits scoped to the current milestone.
- Prefer structured parsing and schema validation over ad hoc string handling.
- Do not introduce a database queue in v1 unless the user explicitly changes the milestone.
- When creating runtime code later, add focused tests around contract validation, file event transitions, sandbox decisions, and provider output schemas.
- If a change creates or updates user-visible behavior, update the relevant docs in the same commit.

## Verification Expectations

Before committing implementation work, run the narrowest meaningful checks available for the files touched. For documentation-only changes, check for internal consistency, stale field names, score scale drift, and sensitive-data leakage.

Do not commit `.DS_Store`, `.env*`, local Claude settings, local Cursor state, tokens, cookies, browser profile files, or generated logs.
