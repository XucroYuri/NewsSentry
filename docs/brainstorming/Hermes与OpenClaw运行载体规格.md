# Hermes 与 OpenClaw 运行载体规格

> 版本: v0.1-draft | 日期: 2026-05-09
> 状态: 开发前运行载体规格
> 上级文档: [架构总览](../architecture-overview.md) | [通用内核与平台化架构 PRD](./通用内核与平台化架构PRD.md) | [Agent Skill Pack 总纲](./AgentSkillPack开发总纲与多Agent生产线路线图.md)

---

## 0. 定位

News Sentry 的生产运行优先级调整为：

1. **Hermes Agent** 是第一主编排运行载体，负责长期调度、cron/gateway 触发、上下文记忆、自主决策和 Skill 自进化建议。
2. **OpenClaw / OpenClaw Skills / ClawHub** 是主要 Skill 生态与兼容运行载体，负责复用 AgentSkills-compatible `SKILL.md`、workspace skills 和社区 Skill 发现能力。
3. **Codex Automations** 与 **Claude Desktop Cowork Scheduled Tasks** 是备用自动化方案，只用于项目维护、研究报告、文档巡检、人工可审阅简报等补充任务，不承担 24 小时新闻监控主链路。

这个调整不改变 News Sentry 的核心原则：内核仍然框架无关，宿主框架只负责唤醒和任务外壳，News Sentry 每次只执行一个 bounded run，完成后退出。

---

## 1. 运行载体分层

| 层级 | 首选载体 | 职责 | 不承担 |
|------|----------|------|--------|
| `primary_orchestrator` | Hermes Agent | 长期运行、cron/gateway 触发、记忆、子任务协调、自进化建议 | 直接绕过 NewsEvent、ToolManifest 或 SandboxPolicy |
| `skill_runtime` | OpenClaw / OpenClaw Skills | Skill 包装、ClawHub 生态复用、workspace skill 分发、兼容运行 | 未审计社区 Skill 直接进入生产 |
| `fallback_automation` | Codex Automations | repo 巡检、开发计划、状态汇总、文档一致性检查 | 生产主监控、登录态采集、自动发布 |
| `fallback_automation` | Claude Cowork Scheduled Tasks | 桌面侧研究、人工可审阅简报、资料整理 | 24 小时关键监控、无人值守生产调度 |

分层含义：

1. Hermes 是生产监控链路的主调度者。
2. OpenClaw 是 Skill 生态和兼容执行的重要载体。
3. Codex 和 Claude Cowork 保留为开发和桌面自动化后备方案。
4. 所有载体都必须通过同一文件事件协议、NewsEvent schema 和 sandbox 边界交接。

---

## 2. 部署 Profile

News Sentry v1 同时设计两套一等部署 profile。二者共享同一 `RuntimeHostAdapter` 契约，不分裂业务逻辑。

### 2.1 `cloud-vps`

适用场景：24 小时生产监控、驻外新闻值守、低人工干预运行。

| 项目 | 约定 |
|------|------|
| 主载体 | Hermes Agent |
| 触发方式 | Hermes cron 或 gateway 触发 |
| 工作目录 | 固定 Git workspace，例如 `/opt/news-sentry/workspace` |
| 状态存储 | Git/Obsidian 文件、`memory/`、`logs/` |
| 凭据管理 | 宿主环境注入，不写入仓库 |
| 失败恢复 | 下一次 bounded run 读取 memory 和 source health 恢复 |
| 人工入口 | Telegram/Discord/Slack/CLI gateway 或 Git review |

`cloud-vps` 是生产推荐 profile。它更适合长期运行和远程通知，但必须把社区 Skill、登录态、Provider key 和命令权限限制在 sandbox 策略内。

### 2.2 `local-workstation`

适用场景：开发调试、编辑桌面工作流、人工审阅、低频研究。

| 项目 | 约定 |
|------|------|
| 主载体 | Hermes Agent 本地运行或 OpenClaw workspace skill |
| 触发方式 | 手动、Hermes 本地 cron、OpenClaw skill command |
| 工作目录 | 本地 Git workspace |
| 状态存储 | 同一文件事件协议和本地 Git |
| 凭据管理 | 本机用户环境，禁止写入共享文档或 logs |
| 失败恢复 | 保留 run log，人工可直接检查文件 |
| 人工入口 | 本地 CLI、桌面编辑器、Claude Cowork/Codex fallback |

`local-workstation` 不应被默认视为 24 小时主监控依赖，因为它受电脑唤醒、网络、电源和桌面应用状态影响。

---

## 3. RuntimeHostAdapter v1

运行载体适配层的最小约定如下。它是后续实现参考，本阶段不写代码。

```yaml
host_kind: hermes | openclaw | codex_automation | claude_cowork
host_role: primary_orchestrator | skill_runtime | fallback_automation
trigger_mode: cron | gateway | skill_command | manual | scheduled_task
deployment_profile: cloud-vps | local-workstation
entrypoint: string
workspace_root: string
target_config_ref: string
run_contract:
  bounded_run: true
  max_run_seconds: number
  writes_file_events: true
  updates_memory: true
capabilities:
  skills: boolean
  memory: boolean
  cron: boolean
  subagents: boolean
  messaging_gateway: boolean
  scheduled_desktop_task: boolean
security:
  secrets_in_repo_allowed: false
  community_skill_default: quarantined
  auto_publish_allowed: false
```

适配器必须保证：

1. 宿主框架负责调度、唤醒、上下文注入和任务外壳。
2. News Sentry 内核只执行一次 bounded run，完成后退出。
3. 输出仍写入 `raw/`、`evaluated/`、`drafts/`、`reviewed/`、`published/`、`archive/`、`memory/`、`logs/`。
4. 目录状态不替代 `NewsEvent.pipeline_stage`。
5. `run_id` 表示一次 bounded run，`NewsEvent.id` 表示确定性新闻条目身份。

---

## 4. Hermes 主编排契约

Hermes 适合承担生产主编排，原因是它提供长期运行、cron scheduling、gateway、skills、memory、自进化和多环境运行能力。News Sentry 对 Hermes 的使用边界如下：

### 4.1 Hermes 可以做

1. 按 cron 或 gateway 指令触发 `news-sentry run` 类型的 bounded run。
2. 维护长期对话和运行记忆，但持久业务状态仍以 `memory/` 和文件事件为准。
3. 通过 Skill 形式调用采集、评估、草稿、内审等 Agent 角色。
4. 将复杂成功流程沉淀为候选 Skill。
5. 使用远程 VPS、Docker、SSH 或本地环境运行。
6. 通过消息平台通知人工审阅，但通知内容必须可追溯到本地文件。

### 4.2 Hermes 不可以做

1. 自动把自进化 Skill 直接提升为生产 Skill。
2. 绕过 ToolManifest 执行任意命令。
3. 绕过 SandboxPolicy 使用登录态、浏览器 profile 或 API key。
4. 把 cookie、token、密码、浏览器 profile 内部数据写入 NewsEvent、frontmatter、logs 或 docs。
5. 自动对外发布新闻稿、社交媒体帖文或正式通稿。

### 4.3 Skill 自进化治理

Hermes 生成或改写的 Skill 进入以下流程：

```text
candidate skill
  -> write to proposals or drafts
  -> manual/security review
  -> contract check against NewsEvent/ToolManifest/SandboxPolicy
  -> quarantine run
  -> promote to active workspace skill
```

生产路径只允许使用已审阅的 workspace skill 或 vetted external skill。自进化产物默认是建议，不是可执行生产变更。

---

## 5. OpenClaw Skill Runtime 契约

OpenClaw 的重点是 Skill 生态、ClawHub、AgentSkills-compatible `SKILL.md` 和 workspace-level 分发。News Sentry 使用 OpenClaw 时遵循以下规则：

### 5.1 OpenClaw 可以做

1. 将 News Sentry 子能力包装成 `SKILL.md`，例如 RSS/API 采集、OpenCLI 采集、新闻价值研判、草稿生成。
2. 从 ClawHub 或现有 OpenClaw skill 生态中发现可复用能力。
3. 在 workspace 级别运行 Skill，输出仍映射为 NewsEvent 或文件事件。
4. 使用 OpenClaw 的 Skill 安装和发现能力辅助能力评估。

### 5.2 OpenClaw 不可以做

1. 未经审计安装并运行社区 Skill。
2. 让社区 Skill 直接读写生产目录或凭据。
3. 让 Skill 自行定义与 NewsEvent 冲突的数据结构。
4. 让 `SourceChannel` 保存可执行 shell 命令。
5. 绕过 `ToolManifest` 和 sandbox 执行 OpenCLI、浏览器或 MCP 工具。

### 5.3 社区 Skill 隔离

ClawHub 或其他社区来源的 Skill 默认状态为 `quarantined`。进入生产前必须满足：

1. 来源、版本、作者和安装来源可记录。
2. 安全扫描状态或人工审查结论可记录。
3. 所需权限可映射到 SandboxPolicy。
4. 输入输出可映射到 NewsEvent、ToolRunResult 或 ProviderResult。
5. dry-run 或隔离运行通过。

---

## 6. 备用自动化边界

### 6.1 Codex Automations

Codex Automations 适合：

1. 定期检查仓库文档一致性。
2. 生成开发周报、状态摘要、下一步实现计划。
3. 检查近期 Git 变更和待办。
4. 对非生产数据做人工可审阅研究。

Codex Automations 不适合：

1. 作为 24 小时新闻监控主调度。
2. 运行登录态采集或高风险 OpenCLI 自动修复。
3. 自动发布外部内容。
4. 绕过生产 runtime profile 写入业务事件。

### 6.2 Claude Cowork Scheduled Tasks

Claude Cowork Scheduled Tasks 适合：

1. 桌面侧资料整理和研究报告。
2. 人工可审阅的简报草稿。
3. 与本地文件夹和连接器相关的非关键自动化。

Claude Cowork Scheduled Tasks 不适合：

1. 生产主监控，因为任务依赖 Claude Desktop 打开和电脑唤醒。
2. 长期无人值守采集。
3. 社媒登录态生产轮询。
4. 无人工确认的发布动作。

---

## 7. 调用流程样板

### 7.1 Hermes cloud-vps 生产样板

```text
Hermes cron/gateway trigger
  -> load News Sentry workspace instructions
  -> invoke RuntimeHostAdapter(host_kind=hermes, deployment_profile=cloud-vps)
  -> run one bounded News Sentry cycle
  -> write file events, memory, logs
  -> summarize result to gateway or review channel
  -> exit
```

验收点：

1. 一条意大利 RSS/API 事件可以进入 `raw/`。
2. 过滤和研判后可以进入 `evaluated/` 或 `archive/`。
3. 高价值事件可以进入 `drafts/`。
4. run log 记录触发来源、run_id、文件写入和错误。

### 7.2 OpenClaw workspace skill 样板

```text
OpenClaw skill command
  -> load News Sentry SKILL.md wrapper
  -> validate runtime input
  -> call same bounded run entrypoint
  -> map output to NewsEvent files
  -> return summary to OpenClaw session
```

验收点：

1. OpenClaw 不需要理解内部 pipeline。
2. Skill wrapper 只暴露必要入口。
3. 输出路径和 schema 与 Hermes 运行一致。

### 7.3 fallback automation 样板

```text
Codex or Claude scheduled task
  -> inspect repo or selected folder
  -> generate reviewable report or maintenance suggestion
  -> never act as production collector
```

验收点：

1. 结果是文档、报告或开发维护建议。
2. 不写生产 `raw/` 或 `evaluated/`，除非任务明确是离线演练。
3. 不使用登录态和自动发布能力。

---

## 8. 开发顺序影响

运行载体对齐应插入在 Contract Stabilization 与 Kernel MVP 之间：

1. **Contract Stabilization** — 定稿数据、配置、文件事件和 sandbox 最小边界。
2. **Runtime Carrier Alignment** — 定稿 Hermes/OpenClaw profile、RuntimeHostAdapter、Skill wrapper 边界和 fallback 自动化边界。
3. **Kernel MVP** — 实现 bounded run、配置加载、RSS/API baseline、文件事件写入、run log、memory、source health 和最小 sandbox enforcer。
4. **Tool/Skill Registry + OpenCLI** — 接入 OpenCLI、SkillManifest、ToolManifest 和 registry。
5. **AI Provider Routing** — 接入任务路由、模型预算和结构化输出。
6. **Sandbox Hardening + Social/KOL Experiment** — 强化高风险能力治理。
7. **Multi-target Expansion** — 增加第二国家 reference package。

---

## 9. 验收标准

1. 文档不再把 Codex 或 Claude Cowork 描述为生产主调度。
2. Hermes 和 OpenClaw 的优先职责清晰：Hermes 主编排，OpenClaw Skill runtime 和生态兼容。
3. `cloud-vps` 与 `local-workstation` 都能用同一 bounded run 契约运行。
4. fallback automation 不能绕过 `ToolManifest`、`SandboxPolicy`、`NewsEvent` 和文件事件协议。
5. 社区 Skill 默认 quarantine。
6. Hermes 自进化 Skill 只能进入建议、草稿、隔离验证和人工审查流程。
7. 自动化边界仍停在草稿、reviewed 和 publish-ready 文件，不自动对外发布。

---

## 10. 参考依据

- [Hermes Agent GitHub](https://github.com/NousResearch/hermes-agent)
- [Hermes Skills Docs](https://hermes-agent.nousresearch.com/docs/guides/work-with-skills)
- [OpenClaw Skills Docs](https://github.com/openclaw/openclaw/blob/main/docs/tools/skills.md)
- [ClawHub GitHub](https://github.com/openclaw/clawhub)
- [Codex Automations](https://openai.com/academy/codex-automations/)
- [Claude Cowork Scheduled Tasks](https://support.claude.com/en/articles/13854387-schedule-recurring-tasks-in-claude-cowork)
