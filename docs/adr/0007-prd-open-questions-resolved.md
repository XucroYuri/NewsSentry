# ADR-0007 — PRD Open Questions 关闭记录

> 状态: **Accepted**
> 日期: 2026-05-09
> 决策者: News Sentry 项目团队
> 覆盖文档: `docs/brainstorming/通用内核与平台化架构PRD.md §10 Open Questions`

---

## 背景

PRD §10 列出 7 条 Open Questions。截至 2026-05-09，各子规格文档已给出明确回答，但 PRD 原文中这些 Questions 仍保持"开放"状态，造成规格效力层级不清晰。本 ADR 正式关闭已被回答的条目。

---

## 逐条处置

### Q1：ToolManifest 是否单独成文，还是并入 SkillManifest？

**状态：RESOLVED（已有专门文档回答）**

`docs/brainstorming/ToolManifest与工具适配层规格.md` 已将 `ToolManifest` 作为独立规格展开，字段、适配流程、错误类型表均完整。结论：**`ToolManifest` 独立成文，与 `SkillManifest` 分工明确**（`SkillManifest` 描述业务能力，`ToolManifest` 描述执行工具能力）。

PRD §10 Q1：标记 `[RESOLVED → ToolManifest与工具适配层规格.md]`。

---

### Q2：sandbox v1 是配置约束还是需要实际执行隔离？

**状态：RESOLVED（已有专门文档回答）**

`docs/brainstorming/SandboxPolicy与执行权限规格.md §0` 明确写：

> v1 不要求完整容器平台，但必须有最小可执行 enforcer，不能只停留在文档约束。

结论：**v1 做最小 enforcer**（命令白名单、文件边界、网络 host 预校验与记录、预算限制、审计日志），不做容器隔离。

PRD §10 Q2：标记 `[RESOLVED → SandboxPolicy与执行权限规格.md §0]`。

---

### Q3：AI Provider 是否需要统一 prompt registry？

**状态：RESOLVED（已有专门文档回答）**

`docs/brainstorming/AIProvider与模型路由规格.md` 已定义 `output_schema_id` 和 `prompt_template_id` 的 route 绑定机制。每条 `route_id` 必须绑定 `output_schema_id`；Skill 只消费 `structured_result`，不直接处理原始文本。

结论：**有 prompt/output schema 注册机制，通过 `route_id + output_schema_id + prompt_template_id` 绑定**，版本治理进入跨 phase 治理 backlog。

PRD §10 Q3：标记 `[RESOLVED → AIProvider与模型路由规格.md]`。

---

### Q4：并发 Agent 下是否需要 lock/lease 机制？

**状态：DEFERRED（进入治理 backlog）**

当前 v1 内核 MVP 以单进程 bounded run 为基础，不涉及并发 Agent 写同一文件的情况。lock/lease 在 Phase 4+ 的多 Agent 场景才有必要。

PRD §10 Q4：标记 `[DEFERRED → 治理 backlog LOCK-001，Phase 4+ 讨论]`。

---

### Q5：长期 memory 是否引入 SQLite？

**状态：RESOLVED（v1 范围明确）**

`AGENTS.md` Core Decisions 明确：

> 不在 v1 引入数据库队列。

`通用内核PRD §8 Out of Scope` 也明确：

> 强数据库依赖：文件事件和 memory 优先，数据库作为后续检索和任务队列增强。

结论：**v1 使用 Markdown/YAML 文件**，`memory/` 目录存储 source health、known ids、provider stats、KOL 状态。SQLite 是 v2+ 增强选项。

PRD §10 Q5：标记 `[RESOLVED: v1 使用文件 memory，SQLite 推迟到 v2+]`。

---

### Q6：CLI 入口命名？

**状态：DEFERRED（见 ADR-0006）**

PRD §10 Q6：标记 `[DEFERRED → ADR-0006，治理 backlog CLI-001]`。

---

### Q7：Provider 成本和质量评估，是否需要离线 eval 集？

**状态：DEFERRED（Phase 5 AI Provider 路由阶段讨论）**

`docs/brainstorming/AIProvider与模型路由规格.md` 提及 `audit` 和 `human_gate` 字段，但 eval 集构建属于 Phase 5 的工作。

PRD §10 Q7：标记 `[DEFERRED → 治理 backlog EVAL-001，Phase 5 讨论]`。

---

## 新增治理 backlog 条目

| 编号 | 内容 | 阶段 |
|------|------|------|
| `CLI-001` | 决定 `python -m news_sentry.cli run` 的完整命令 schema | Phase 3 前 |
| `LOCK-001` | 并发 Agent 的文件 lock/lease 机制设计 | Phase 4+ |
| `EVAL-001` | AI Provider 离线 eval 集构建与评估流程 | Phase 5 |
| `SCHEMA-VERSION-001` | `prompt_template_id` 和 `output_schema_id` 的版本治理机制 | Phase 5 |

---

## 影响

- `docs/brainstorming/通用内核与平台化架构PRD.md §10`：逐条更新状态标记。
- `docs/roadmap/development-plan.md §治理 backlog`：新增上述四条。
