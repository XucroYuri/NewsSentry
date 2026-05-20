# ADR-0004 — 双语翻译时机：collect 预览 vs judge 高保真 canonical

> 状态: **Accepted**
> 日期: 2026-05-09
> 决策者: News Sentry 项目团队
> 覆盖文档: `docs/newsevent-schema.md §待讨论第 4 条`、`docs/it-zh-bilingual-sop.md`

---

## 背景

`newsevent-schema.md §待讨论` 第 4 条：

> **多语言翻译时机** — 翻译是在 judge 环节统一做，还是在 collect 环节就做（成本更高）？

collect 阶段翻译的优点是 filter 阶段可用中文标题判断，缺点是：大量低价值事件（filter 后被丢弃的）产生无用翻译成本；且 collect 阶段 LLM 调用越多，bounded run 预算消耗越快。

judge 阶段翻译的优点是：只翻译过滤后的高价值事件；缺点是：filter 规则无法利用中文标题，需改用意大利语关键词或语义桥。

---

## 决策

**采用分阶段翻译策略：**

### collect 阶段（低成本机译，非 canonical）

- 对所有 `language != "zh"` 的事件，调用 `translate.fast` route 做标题机译。
- 结果写入 `metadata.translation.title_pre`，**不写入** `title_translated`（canonical 字段）。
- `metadata.translation.status = "partial"`，表示仅有标题预览。
- 用途：filter 规则可选择性读取 `title_pre` 辅助中文关键词匹配，但不强制依赖。

### judge 阶段（高保真 canonical）

- 对所有进入 judge 的事件，调用 `translate.high` 或 `judge.primary` 的内置翻译能力，产出：
  - `title_translated`（中文，canonical）
  - `content_translated`（中文，canonical，视 `news_value_score` 阈值决定是否全文翻）
- `metadata.translation.confidence`（0–100，LLM 自评）
- `metadata.translation.engine_route = "translate.high"`
- `metadata.translation.status = "completed"`

### 失败回退

- 任何阶段翻译失败时：
  - 不静默假装翻译成功。
  - `metadata.translation.status = "skipped"`。
  - canonical 翻译字段保持 `null`。
  - 不阻断 pipeline，继续处理。

---

## 三层翻译粒度

| 粒度 | 触发条件 | 写入字段 | Route |
|------|---------|---------|-------|
| 标题层（轻量） | 所有非中文事件（collect 阶段） | `metadata.translation.title_pre` | `translate.fast` |
| 摘要层（标准） | 进入 `evaluated/` 的事件（judge 阶段） | `title_translated` + JudgeResult.summary | `translate.high` 或 `judge.primary` 内置 |
| 全文层（高保真） | `news_value_score ≥ 70` 或 `breaking_news_level=breaking` | `title_translated` + `content_translated` | `translate.high` |

---

## 替代方案考虑

- **全部在 collect 做**：成本高，大量被 filter 丢弃的事件浪费翻译预算，排除。
- **全部在 judge 做**：filter 阶段失去中文辅助，但可接受（filter 主要用意语关键词），可以作为最简实现。本决策增加 `title_pre` 是对其的加强，可按配置关闭。
- **只做标题不做全文**：可通过配置 `news_value_score` 阈值为 101 实现，已涵盖。

---

## 影响

- `docs/newsevent-schema.md §待讨论第 4 条`：标记为 `[RESOLVED: 见 ADR-0004]`，正文补充 `metadata.translation` 字段说明。
- `docs/it-zh-bilingual-sop.md §翻译时机`：依本决策编写。
- `docs/contracts-canonical.md §6`：`metadata.translation` 字段规范依本决策定义。
