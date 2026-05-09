# 多 Agent 开发工具准备说明

> 日期: 2026-05-09
> 范围: Codex、opencode、Claude Code、Cursor 等开发工具的项目级协作准备；Hermes/OpenClaw 生产运行载体优先级说明

## 1. 目标

本项目后续会同时使用 Codex、opencode、Claude Code、Cursor 等 Agent 化开发工具，但这些工具不等同于生产运行载体。生产运行优先采用 Hermes Agent 作为主编排，OpenClaw/OpenClaw Skills/ClawHub 作为 Skill 生态与兼容运行载体；Codex Automations 和 Claude Desktop Cowork Scheduled Tasks 只作为备用自动化方案。准备工作的核心不是为每个工具维护一套不同规则，而是建立一个共享工程上下文，让不同工具进入仓库后都能理解同一组架构边界、开发阶段和安全约束。

本次准备采用以下结构：

| 文件 | 作用 | 面向工具 |
|------|------|----------|
| `AGENTS.md` | 项目级共享 Agent 指令入口 | Codex、opencode、Cursor，以及其他支持 `AGENTS.md` 的工具 |
| `CLAUDE.md` | Claude Code 项目记忆入口，导入 `AGENTS.md` | Claude Code |
| `.cursor/rules/news-sentry-core.mdc` | Cursor 项目规则，引用共享入口和关键架构文档 | Cursor |
| `opencode.json` | opencode 项目配置，加载补充说明和 Cursor 规则 | opencode |
| 本文档 | 人类可读的工具准备说明和后续扩展建议 | 全部开发者和 Agent |

## 2. 设计原则

1. 共享事实只维护一份：`AGENTS.md` 是跨工具的项目规则入口。
2. 工具差异做薄适配：Claude Code 用 `CLAUDE.md` 导入，Cursor 用 `.cursor/rules/*.mdc` 引用，opencode 用 `opencode.json` 追加上下文。
3. 项目规则不替代架构文档：架构、协议、schema、sandbox、Provider 路由仍以 `docs/` 下文档为 source of truth。
4. 本地隐私不进入仓库：个人偏好、API key、cookie、token、浏览器 profile、临时 session note 不写入共享规则。
5. 开发工具不改变项目路线：先完成 Contract Stabilization 与 Runtime Carrier Alignment，再进入 Kernel MVP；不提前把 OpenCLI、社媒登录态、复杂 Provider 或数据库队列拉进 v1。

## 3. 生产运行载体与开发工具分工

| 类别 | 首选载体 | 项目角色 |
|------|----------|----------|
| 生产主编排 | Hermes Agent | 长期 cron/gateway 调度、记忆、自主决策、24 小时监控主链路 |
| Skill runtime | OpenClaw / OpenClaw Skills / ClawHub | `SKILL.md` 包装、workspace skills、社区 Skill 发现与兼容运行 |
| 备用自动化 | Codex Automations | repo 巡检、开发计划、状态汇总、文档一致性检查 |
| 备用自动化 | Claude Cowork Scheduled Tasks | 桌面侧研究、资料整理、人工可审阅简报 |
| 开发工具 | Cursor / Codex / opencode / Claude Code | 代码和文档编辑、实现辅助、审查、调试 |

Codex 或 Claude Cowork 不承担 24 小时新闻监控主调度。Claude Cowork Scheduled Tasks 还受 Claude Desktop 打开和电脑唤醒影响，因此只能作为桌面侧补充自动化。

## 4. 工具适配策略

### Codex

Codex 使用仓库根目录的 `AGENTS.md` 作为项目级指令。后续如果出现子目录级实现，例如 `src/`、`skills/`、`adapters/`，可以在子目录新增更具体的 `AGENTS.md` 或 `AGENTS.override.md`，但必须避免与根目录规则冲突。

建议用法：

```bash
codex "根据 docs/brainstorming/通用内核与平台化架构PRD.md 生成 Phase 1 implementation plan"
```

### opencode

opencode 会读取 `AGENTS.md`，同时本项目通过 `opencode.json` 加载补充说明和 Cursor 规则，便于复用同一组上下文。`opencode.json` 只保存项目级配置，不写入个人模型偏好、私有 API key 或本机路径。

建议用法：

```bash
opencode
```

进入会话后先让工具概述已加载的项目规则，再分配具体实现任务。

### Claude Code

Claude Code 使用 `CLAUDE.md`。本项目的 `CLAUDE.md` 通过 `@AGENTS.md` 导入共享规则，再补充 Claude Code 专用注意事项。私有机器偏好应写入 `CLAUDE.local.md`，该文件已在 `.gitignore` 中排除。

建议用法：

```bash
claude
```

如果需要让 Claude Code 记住项目级规则，应修改 `AGENTS.md` 或 `CLAUDE.md`；如果只是个人偏好，使用 `CLAUDE.local.md` 或用户级 memory。

### Cursor

Cursor 使用 `.cursor/rules/news-sentry-core.mdc` 作为始终应用的项目规则，并引用 `AGENTS.md` 与关键架构文档。项目只提交 `.cursor/rules/`，不提交 Cursor 本地状态或缓存。

建议用法：

1. 在 Cursor 中打开仓库根目录。
2. 确认 `news-sentry-core` 规则处于启用状态。
3. 对实现任务要求 Cursor 先读取 `AGENTS.md` 和相关 `docs/` 文档，再修改代码。

## 5. 后续开发任务模板

后续给任一开发工具分配任务时，建议统一使用这个结构：

```text
目标:
实现 Phase 1 Kernel MVP 的某一个明确切片。

必须先读:
- AGENTS.md
- docs/architecture-overview.md
- docs/integration-protocol.md
- docs/newsevent-schema.md
- 与任务相关的 brainstorming 规格

边界:
- 不引入 OpenCLI/社媒登录态/复杂 Provider/数据库队列，除非任务明确要求。
- 不把 Codex Automations 或 Claude Cowork 当作生产主调度。
- 不改变 NewsEvent canonical 字段。
- 不把 token/cookie/API key 写入仓库。

交付:
- 代码或文档变更
- 最小验证命令
- 变更摘要
```

## 6. 需要避免的漂移

| 漂移类型 | 风险 | 处理 |
|----------|------|------|
| 每个工具各写一套规则 | Codex、Claude Code、Cursor 得到不同项目事实 | 统一从 `AGENTS.md` 派生 |
| 开发工具变成生产载体 | 24 小时监控依赖桌面状态或临时会话 | Hermes 主编排，OpenClaw Skill runtime，Codex/Claude 备用 |
| 过早实现高风险采集 | 登录态、封禁、合规风险提前进入主线 | 社媒/KOL 只留实验通道 |
| Provider 直连 | 模型切换和成本控制困难 | 通过 task-based route 调用 |
| SourceChannel 执行 shell | 绕过 ToolManifest 和 sandbox | 使用 `tool_ref + binding_id + validated_args` |
| 目录状态替代 schema | 多 Agent 交接时字段语义混乱 | 目录状态和 `pipeline_stage` 分离 |
| 本地状态入库 | 泄露凭据或污染协作上下文 | `.gitignore` 排除本地文件 |

## 7. 参考依据

- Hermes 官方仓库和 Skills 文档：Hermes 用于主编排、cron/gateway、skills 和 memory。
- OpenClaw Skills 与 ClawHub 文档：OpenClaw 用于 `SKILL.md` 生态、workspace skills 和社区 Skill 发现。
- Codex 官方文档: `AGENTS.md` 用于项目级自定义指令。
- opencode 官方文档: 支持 `AGENTS.md`，并可通过 `opencode.json` 的 `instructions` 字段加载额外指令文件。
- Claude Code 官方文档: Claude Code 读取 `CLAUDE.md`，可用 `@AGENTS.md` 导入共享规则。
- Cursor 官方文档: 推荐使用 `.cursor/rules/*.mdc` 作为项目规则，`.cursorrules` 为 legacy 方案。

## 8. 验收标准

1. 任一工具进入仓库后，都能找到共享项目规则。
2. 工具规则不会覆盖或改写核心架构文档的 source of truth 地位。
3. 本地敏感配置和个人偏好不会被 Git 跟踪。
4. 后续 Runtime Carrier Alignment 和 Kernel MVP 实现任务可以直接引用这些入口文件，而不需要重新解释项目边界。
5. 任一开发工具都不会把 Codex/Claude fallback automation 误当作生产主监控。
