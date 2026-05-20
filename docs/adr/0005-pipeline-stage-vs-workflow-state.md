# ADR-0005 — pipeline_stage 与 workflow_state 正交分离

> 状态: **Accepted**
> 日期: 2026-05-09
> 决策者: News Sentry 项目团队
> 覆盖文档: `docs/newsevent-schema.md §待讨论第 5 条`

---

## 背景

`newsevent-schema.md §待讨论` 第 5 条：

> **文件工作流状态** — `workflow_state/review_status` 如何与 `pipeline_stage` 严格分离并投影到 frontmatter？

两类状态目前混用的风险：

1. `pipeline_stage=outputted` 不代表"已发布"，也不代表"人工审阅通过"。
2. 一个处于 `judged` 状态的事件，可能同时处于"草稿待审"（`workflow_state=draft`）或"已退回"（`workflow_state=rejected`）状态。
3. 如果用 `pipeline_stage` 表达人审状态，会导致枚举值膨胀，且自动化阶段无法写入人审状态。

---

## 决策

**`pipeline_stage` 和 `workflow_state` 正交，服务于不同目的：**

| 维度 | 字段 | 赋值方 | 载体 | 含义 |
|------|------|--------|------|------|
| 逻辑管线状态 | `NewsEvent.pipeline_stage` | 各阶段 Skill（自动化） | `NewsEvent` JSON/YAML | 数据处理进展 |
| 编辑/人审流转 | `workflow_state` | 人工或输出 Skill（半自动） | Obsidian frontmatter | 编辑流程状态 |

### `pipeline_stage` 枚举（已定稿，见 ADR-0001）

```
collected | filtered | judged | outputted
```

### `workflow_state` 枚举（frontmatter 专用）

```
draft | under_review | approved | rejected | archived
```

**规则：**

1. `workflow_state` **不**出现在 `NewsEvent` 顶层字段，只写入 Obsidian Markdown frontmatter，或作为 `metadata.workflow.state` 存储。
2. 输出 Skill 将事件写入 `drafts/` 时，自动设置 `workflow_state=draft`。
3. 人工审阅后，更新 `workflow_state`，不修改 `pipeline_stage`。
4. `workflow_state=approved` 可以触发事件从 `drafts/` 移入 `reviewed/`，但不改变 `pipeline_stage`（仍为 `judged`）。
5. `workflow_state=archived` 对应 `archive/` 目录，用于已判断无需人工跟进的事件。

---

## 投影到 frontmatter 的格式

```yaml
---
id: ne-italy-ansa-20260509-a1b2c3d4
pipeline_stage: judged
workflow_state: draft   # 人审流转状态
# ... 其他 NewsEvent 字段
---
```

---

## 影响

- `docs/newsevent-schema.md §待讨论第 5 条`：标记为 `[RESOLVED: 见 ADR-0005]`，在 metadata 扩展场景中增加 `metadata.workflow` 示例。
- `docs/contracts-canonical.md §5.3`：`workflow_state` 分离说明已写入。
- `docs/it-zh-bilingual-sop.md §草稿模板`：frontmatter 中包含 `workflow_state`。
