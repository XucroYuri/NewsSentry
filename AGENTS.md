# News Sentry Agent Instructions

## Project Mission

News Sentry is a framework-neutral Agent Skill Pack platform for continuous news monitoring. The first reference target is Italy, but core code and contracts must stay reusable for other countries, regions, and domains.

The production runtime priority is Hermes Agent first, OpenClaw/OpenClaw Skills/ClawHub second as the main Skill runtime and ecosystem compatibility layer. Codex Automations and Claude Desktop Cowork Scheduled Tasks are fallback automation surfaces for project maintenance, research reports, and human-reviewable summaries, not the 24-hour production monitoring backbone. A host should trigger bounded runs; the Skill Pack itself must not implement an unbounded daemon loop.

## Architecture Source Of Truth

Read these files before changing architecture, schemas, pipeline behavior, permissions, provider routing, or tool execution:

- `docs/contracts-canonical.md` — **口径规范基准**：字段命名、分值量纲、目录映射、pipeline_stage 枚举、产品命名、classification metadata schema 的唯一权威来源
- `docs/architecture.md` — **架构总览**：系统架构、数据流、目录结构
- `docs/external-integration-strategy.md` — **外部项目接入策略**：OpenCLI 接入原则、三原则、ToolManifest 骨架意图、舍弃清单
- `schemas/` — **14 份 JSON Schema 2020-12**：机器可读契约，与 contracts-canonical.md 双向绑定（ADR-0014）
- `config/` — **运行时配置骨架**：意大利参数封装在 config/targets/italy.yaml，其他国家复制 _template.yaml（ADR-0015）
- `src/news_sentry/` — **Python 3.11+ / Pydantic v2 实现**（ADR-0012、ADR-0013）

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
- **采集阶段零 Token 消耗**：RSS/API/OpenCLI/Playwright MCP 四种采集方式均不消耗 AI token；Computer Use 仅作为 L1 账号的最终兜底，用量受严格限制。详见 Phase 12 设计文档。
- **13 维新闻分类框架**：A-政治与治理 / B-经济与商业 / C-外交与国际关系 / D-安全与防务 / E-司法与法治 / F-社会与民生 / G-科技与数字 / H-环境与能源 / I-移民与人口 / J-文化与遗产 / K-宗教与梵蒂冈 / L-涉华议题 / M-Other 开放式兜底。详见 `docs/superpowers/specs/2026-05-11-phase-12-source-matrix-design.md`。
- **信源生命周期管理**：active → degraded（3 次失败）→ dead（10 次失败）→ archive；内置自进化机制（健康审计、热点信源发现、KOL 清单自动扩展）。
- **三层浏览器采集兜底**：Layer 1 OpenCLI Bridge（零 Token）→ Layer 2 Playwright MCP（零 Token）→ Layer 3 Computer Use（限 L1 账号，每日 ≤3 次/源，$5/次上限）。
- **通知通道不硬编码**：所有告警/通知走 Hermes Agent 配置的信息通道，不做飞书/钉钉/企微等具体平台假设。

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

**v1.0.0 — 全部 23 个 Phase 已完成。**

1. Contract Stabilization ✅
2. Runtime Carrier Alignment ✅
3. Kernel MVP ✅
4. Tool/Skill Registry + OpenCLI ✅
5. AI Provider Routing ✅
6. Sandbox Hardening + Social/KOL Experiment ✅
7. Multi-target Expansion ✅
8. Obsidian Ontology Sync ✅
9. Karpathy Skills Integration ✅
10. Structured Logging + CLI Doctor ✅
11. Trend Analysis ✅
12. Italy Source Matrix ✅
13. Evaluation Set ✅
14. AI Judge Optimization ✅
15. Cloud VPS Deployment 🔧
16. Third Target (Japan) ✅
17. Real-time Alert Pipeline ✅
18. Production Hardening ✅
19. Multi-language Enhancement ✅
20. Quality Feedback Loop ✅
21. RSS Auto-Discovery ✅
22. API Gateway ✅
23. Release v1.0 ✅

## File Event Protocol

Use the v1 directory protocol consistently:

- `raw/`: collected events
- `evaluated/`: filtered and judged events
- `drafts/`: editorial drafts
- `reviewed/`: human or internal-review candidates
- `published/`: approved archive or publish-ready files
- `archive/`: rejected, duplicate, low-value, or failed samples
- `memory/`: known IDs, source health, cursors, provider stats, KOL state, matrix governance state
- `logs/`: bounded run logs, tool audit logs, provider usage logs
- `session-profiles/`: browser session profiles for social/KOL collection (gitignored)
- `chrome-data/`: Chromium user data directory for OpenCLI Bridge (gitignored)

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
