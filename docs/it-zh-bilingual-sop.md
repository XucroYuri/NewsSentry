# 意大利语→中文双语处理 SOP

> 版本: v1.0 | 日期: 2026-05-09
> 状态: **规范（Canonical）**
> 面向读者: 中文母语者阅读、处理、审阅意大利语原文新闻事件的完整工作流
> 关联决策: [ADR-0004](./adr/0004-bilingual-translation-timing.md)（翻译时机）| [ADR-0005](./adr/0005-pipeline-stage-vs-workflow-state.md)（编辑流程分离）
> 字段规范: [contracts-canonical.md §6](./contracts-canonical.md)（`metadata.translation` 字段）

---

## §1. 概述与定位

News Sentry 的一线读者是**中文母语者**（记者、编辑、研究员），但监控的主要信源是**意大利语**（及部分英语）。双语处理不是翻译工具的问题，而是一套贯穿 pipeline 四个环节的**工作流 SOP**，解决以下问题：

1. **什么时候翻译**：不是所有事件都值得全文翻译，但所有进入判断的事件都需要最少一级中文标题。
2. **翻译到什么粒度**：标题→摘要→全文三层，按事件价值动态分配算力。
3. **专有名词如何处理**：人名、政党、机构、地名需要有统一中文对照，不能每次翻译随机输出。
4. **草稿给中文读者看什么**：不是原文的机械翻译，而是 30 秒可读的决策辅助材料。
5. **质量如何追踪**：`translation_confidence` 和 `glossary_hit_rate` 两个可量化指标。
6. **合规边界在哪里**：内部使用与对外引用的不同要求，社媒内容的额外限制。

---

## §2. 翻译时机决策（依 ADR-0004）

### 2.1 流程图

```
[collect 阶段]
  language != "zh" 的事件
      ↓
  轻量语种检测 → 写入 NewsEvent.language
      ↓
  标题机译（translate.fast）
      ↓
  写入 metadata.translation.title_pre（⚠️ 非 canonical）
  metadata.translation.status = "partial"
      ↓
[filter 阶段]
  可选：读取 title_pre 辅助中文关键词匹配
  （不强制依赖，filter 主要以意语/英语规则运行）
      ↓
[judge 阶段]  ← canonical 翻译在此发生
  高保真翻译（translate.high 或 judge.primary 内置）
      ↓
  写入 title_translated（canonical）
  写入 content_translated（视粒度策略，见 §3）
  填充 metadata.translation.confidence（0–100）
  填充 metadata.translation.engine_route
  metadata.translation.status = "completed"
      ↓
[output 阶段]
  草稿使用 title_translated 和 content_translated
  frontmatter 写入 translation_confidence
```

### 2.2 翻译失败回退

任何阶段翻译失败时：

- `metadata.translation.status = "skipped"`（不得用 `null` 代替，语义不同）
- canonical 翻译字段（`title_translated`、`content_translated`）保持 `null`
- **不阻断** pipeline，继续处理
- 在 run log 中记录翻译失败的 `route_id`、错误类型和 `NewsEvent.id`
- 草稿输出时若 `title_translated` 为空，使用原文标题并加注 `[翻译失败，见原文]`

---

## §3. 三层翻译粒度策略

依 `news_value_score` 和 `breaking_news_level` 自动分级：

| 粒度 | 触发条件 | 写入字段 | Provider Route | 备注 |
|------|---------|---------|---------------|------|
| **标题层**（轻量机译） | 所有非中文事件（collect 阶段） | `metadata.translation.title_pre` | `translate.fast` | 非 canonical，随时可被 judge 覆盖 |
| **摘要层**（标准翻译） | 进入 `evaluated/` 的事件（judge 阶段） | `title_translated` + `JudgeResult.summary`（中文） | `translate.high` 或 `judge.primary` | canonical，是草稿的最低翻译要求 |
| **全文层**（高保真翻译） | `news_value_score ≥ 70` 或 `breaking_news_level = "breaking"` | `title_translated` + `content_translated` | `translate.high` | 全文翻译；注意成本，按信源配额限制 |

### 3.1 粒度配置参数

在 `TargetConfig` 或 `ProviderConfig` 中可覆盖以下默认值：

```yaml
bilingual:
  full_text_threshold: 70       # news_value_score 达到此值触发全文翻译
  breaking_full_text: true      # breaking_news_level="breaking" 时强制全文
  title_pre_enabled: true       # collect 阶段是否做标题机译（可关闭节省成本）
  translate_fast_route: "translate.fast"
  translate_high_route: "translate.high"
```

---

## §4. 意中术语对照规范

### 4.1 术语命中流程

```
[judge 阶段翻译时]
  提取命名实体（人名、机构名、政党、地名等）
      ↓
  查询 docs/it-zh-glossary.md 术语表
      ↓
  命中 → 使用术语表规范译名
  未命中 → 保留意大利原文 + 括注初译 + 标记 [待人审]
      ↓
  计算 glossary_hit_rate（命中实体数 / 总实体数 × 100）
  写入 metadata.translation.glossary_hit_rate
      ↓
  如 glossary_hit_rate < 50：
    JudgeResult.recommendation 降为 "monitor"（不升 "recommend"）
    在 JudgeResult.reasoning 中注明"术语命中率低，建议人工核实译名"
```

### 4.2 未命中实体的草稿标注格式

```markdown
意大利总理 Giorgia Meloni（梅洛尼，[待人审]）于今日...
```

**规则：**
- 中文初译用括号附注在原文后
- `[待人审]` 标签表示该译名未经术语表确认
- 审阅者确认后，将正式译名更新到 `docs/it-zh-glossary.md`

### 4.3 术语表维护策略

- 术语表种子文件：`docs/it-zh-glossary.md`
- 更新频率：每次人工审阅发现新的重要专有名词时更新
- 更新格式：向术语表对应分类追加新条目，标注信源和日期
- 不自动写入：`judge` Skill 不自动修改术语表，只读取

---

## §5. 面向中文母语者的草稿模板

`drafts/` 目录中的 Markdown 文件使用以下标准结构：

### 5.1 Frontmatter 规范

```yaml
---
id: ne-italy-ansa-20260509-a1b2c3d4
pipeline_stage: judged
workflow_state: draft                    # 人审流转状态（ADR-0005）
title_zh: "梅洛尼强调中意合作新框架"      # 中文标题（canonical）
title_it: "Meloni: cooperation with China..."  # 意大利原文标题
one_line_summary_zh: "意总理梅洛尼于今日会晤中方代表，强调中意经贸合作..."
source_name: "ANSA"
source_url: "https://www.ansa.it/..."
published_at: "2026-05-09T14:30:00Z"
source_credibility: 90                  # 0–100
news_value_score: 82                    # 0–100
china_relevance: 85                     # 0–100
breaking_news_level: "significant"
translation_confidence: 88              # 0–100，metadata.translation.confidence 的草稿投影
glossary_hit_rate: 75                   # 0–100，术语命中率
compliance_note: "内部参考，未经核实，禁止对外引用原文内容"
---
```

### 5.2 正文骨架

```markdown
## ⚡ 30 秒摘要

{LLM 生成的中文摘要，200 字以内，直接回答"发生了什么/谁说了什么/有何影响"}

---

## 关键事实表

| 要素 | 内容 |
|------|------|
| 事件 | {一句话描述核心事件} |
| 时间 | {发生时间，精确到日} |
| 人物 | {主要涉事人物，含官职} |
| 地点 | {事发地或相关地} |
| 关键数字 | {如有：金额、人数、比例等} |
| 来源 | [{来源名}]({来源URL}) |

---

## 中国/华人相关性提示

{仅当 china_relevance ≥ 30 时显示此节}

- 相关性分值：{china_relevance}/100
- 涉华角度：{LLM 分析意大利事件与中国利益/政策/企业/人员的具体关联}
- 国内关注度预估：{metadata.italy_china_context.国内共鸣度预估（若有）}

---

## 不确定性与核实状态

- 来源可信度：{source_credibility}/100（{来源级别描述，如"权威通讯社"/"单一社交媒体帖子"}）
- 多源核实：{是否已有其他信源报道，如无则标注"单一来源，建议核实"}
- 矛盾信息：{如有不同报道角度，简述分歧}
- 翻译置信度：{translation_confidence}/100（{如有特殊说明，如"含多个未确认专有名词"}）

---

## 深度分析

{LLM 生成的深度研判文本，300–500 字}

---

## 原文锚点与参考

- **原文标题**：{title_it}
- **原文链接**：{source_url}
- **采集时间**：{collected_at}
- **译者**：机器翻译（route: {metadata.translation.engine_route}）
- **研判 Skill**：{judge_result.judge_skill_id}
- **研判模型**：{judge_result.judge_model}

{仅当 glossary_hit_rate < 50 时显示}
> ⚠️ **术语警告**：本草稿含 {100 - glossary_hit_rate}% 的实体名称未在术语表中找到标准对照，请人工核实关键专有名词的中文译名。
```

---

## §6. 合规与免责声明模板

### 6.1 标准内部使用声明

所有草稿文件 frontmatter 必须包含：

```yaml
compliance_note: "内部参考，未经核实，禁止对外引用原文内容"
```

正文末尾固定附加（可配置是否显示）：

```
---
*本文件为 News Sentry 自动生成的内部参考草稿。内容来源于公开信息，经机器翻译和 AI 研判处理，未经人工编辑核实。禁止将本草稿内容直接对外发布或作为正式报道依据。如需引用原文，请通过上方原文链接访问来源。*
```

### 6.2 社媒来源额外声明

当 `source_id` 含社媒平台标识（`twitter`、`facebook`、`reddit`、`telegram` 等），或 `content_type = "social_post"` 时，额外加注：

```
*来源为社交媒体帖子，内容未经官方核实，可能存在信息失真、断章取义或蓄意误导的风险。请以官方来源作为最终参考依据。*
```

### 6.3 GDPR 与平台条款红线

- **禁止**在草稿中保留社媒用户的个人身份信息（PII），包括非公众人物的账号、邮件等。
- **禁止**将抓取到的私信、非公开帖子内容写入任何文件。
- **禁止**对外发布含有未经授权的版权内容的大段摘录（可摘录关键句，注明来源）。
- 上述限制已在 `SandboxPolicy与执行权限规格.md §6` 中通过技术层面约束。

---

## §7. 双语处理质量追踪

### 7.1 可量化指标

| 指标 | 字段路径 | 量纲 | 说明 |
|------|---------|------|------|
| 翻译置信度 | `metadata.translation.confidence` | 0–100 | LLM 对自身翻译质量的自评 |
| 术语命中率 | `metadata.translation.glossary_hit_rate` | 0–100 | 命名实体命中术语表的比率 |
| 翻译状态 | `metadata.translation.status` | 枚举 | `completed / partial / skipped` |
| 使用的路由 | `metadata.translation.engine_route` | 字符串 | 如 `translate.fast / translate.high` |

### 7.2 质量门控规则

| 条件 | 触发行为 |
|------|---------|
| `translation.status = "skipped"` | 草稿标题显示原文 + `[翻译失败]` |
| `glossary_hit_rate < 50` | `JudgeResult.recommendation` 不超过 `"monitor"` |
| `translation.confidence < 60` | 草稿末尾加 `⚠️ 低置信度翻译` 警告 |
| `breaking_news_level = "breaking"` AND `translation.status = "skipped"` | 在 run log 中写入告警，建议人工即时翻译 |

### 7.3 质量数据的 Obsidian 查询示例

在 Obsidian Dataview 中追踪翻译质量：

```dataview
TABLE translation_confidence, glossary_hit_rate, workflow_state
FROM "evaluated"
WHERE translation_confidence < 70
SORT translation_confidence ASC
```

---

## §8. 快速参考卡（给草稿审阅者）

```
✅ 看到 [待人审] → 核实该专有名词，更新 it-zh-glossary.md
⚠️ 看到 ⚠️ 低置信度翻译 → 逐句核对原文，重点检查数字、时间、人名
🔴 看到 [翻译失败] → 查看原文，若重要则手动翻译更新草稿
📋 glossary_hit_rate < 50 → 标记为 monitor，不升 recommend，先核实再决策
📵 社媒来源 → 必须找到权威二次引用才可升级可信度
```
