# ADR-0006 — CLI 入口命名暂缓决策

> 状态: **Superseded by ADR-0016**
> 日期: 2026-05-09
> 决策者: News Sentry 项目团队
> 覆盖文档: `docs/brainstorming/通用内核与平台化架构PRD.md §10 Open Questions 第 6 条`

---

## 背景

PRD Open Questions 第 6 条：

> Skill Pack 的最小 CLI 入口如何命名，是否需要统一为 `python -m news_sentry.cli run --target italy --stage collect --profile local-workstation`？

此问题影响：
- 开发者与 Hermes/OpenClaw 的调用契约。
- Codex Automations 和 Claude Cowork 的 fallback 触发方式。
- 运行载体的 `RuntimeHostAdapter` 设计。

---

## 决策

**暂缓到 Kernel MVP（Phase 3）实现前决策，当前进入治理 backlog。**

原因：
1. v1 内核 MVP 之前，CLI 具体形状依赖 `RuntimeHostAdapter` 和 `run lifecycle` 设计，这两者在 Phase 3 才实现。
2. 当前文档阶段无需绑定 CLI 命名，配置加载方式和触发协议更重要。
3. 过早定名可能导致实现阶段为了迁就命名调整接口，增加摩擦。

**暂定形式（可在 Phase 3 前调整）：**

```
python -m news_sentry.cli run --target <target_id> --stage <stage> --profile <profile_id>
```

**治理 backlog 条目：** `CLI-001 — 决定 python -m news_sentry.cli run 的完整命令 schema`，在 `docs/development-plan.md §跨 phase 治理 backlog` 中追踪。

---

## 影响

- `docs/brainstorming/通用内核与平台化架构PRD.md §10 第 6 条`：标记为 `[DEFERRED: 见 ADR-0006，进入治理 backlog CLI-001]`。
- `docs/development-plan.md §治理 backlog`：增加 `CLI-001` 条目。
