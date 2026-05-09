# News Sentry — 契约规范基准

> 版本: v1.0 | 日期: 2026-05-09
> 状态: **规范基准（Canonical）** — 本文档是所有跨文档口径争议的最终裁定来源
> 维护规则: 修改任何本文件条款必须同步创建或更新对应 ADR，并更新所有引用文件

本文档解决项目已发现的六类跨文档口径漂移，形成唯一口径基准。所有规格文档、示例代码、测试夹具在遇到歧义时以本文档为准。

---

## §1. 产品命名规范

| 场景 | 规范写法 | 禁止写法 |
|------|---------|---------|
| 品牌名/文章标题/文档标题 | `News Sentry` | `news-sentry`（标题场景）、`NewsSentry`、`newssentry` |
| 包名/CLI 命令/代码标识符 | `news-sentry` | `News-Sentry`、`NewsSentry` |
| 仓库目录/文件路径 | `news-sentry` 或 `news_sentry` | 任何大写混合 |
| CLI 入口示例 | `news-sentry run --target italy --stage collect` | 其他形式（待 ADR-0006 定稿） |

---

## §2. `pipeline_stage` 唯一形态

### 2.1 枚举值

```
collected | filtered | judged | outputted
```

**规则：**

- `NewsEvent.pipeline_stage` 字段使用上述四个值。
- `ProcessRecord.stage` 字段使用相同四个值。
- `SkillManifest.pipeline_stage` 使用对应的动词原形：`collect | filter | judge | output`（含义：该 Skill 负责哪个环节）。

**注脚：** 动词原形（`collect`、`filter`、`judge`、`output`）仅用于 `SkillManifest` 的"负责环节"声明，以及人类沟通。任何 NewsEvent 状态字段、ProcessRecord 字段和文件目录检索都使用过去分词形式（`collected`、`filtered`、`judged`、`outputted`）。

### 2.2 禁止歧义写法

| 禁止写法 | 正确替代 |
|---------|---------|
| `stage: "collect"` 用于 NewsEvent 状态 | `pipeline_stage: "collected"` |
| `stage: "evaluated"` | `pipeline_stage: "filtered"` |
| `stage: "judging"` | `pipeline_stage: "judged"` |
| `stage: "published"` | `pipeline_stage: "outputted"` |

---

## §3. `NewsEvent.id` 唯一格式规范

### 3.1 标准格式

```
ne-{target_id}-{source_id}-{yyyymmdd}-{hash8}
```

| 分段 | 说明 | 示例 |
|------|------|------|
| `ne` | 固定前缀，标识 NewsEvent | `ne` |
| `{target_id}` | 监控目标 ID，小写连字符 | `italy`、`eu-china` |
| `{source_id}` | 来源标识，小写连字符 | `ansa`、`fao-rss`、`repubblica` |
| `{yyyymmdd}` | 采集日期，UTC，8 位数字 | `20260509` |
| `{hash8}` | 内容/URL 确定性哈希，8 位十六进制 | `a1b2c3d4` |

**完整示例：**
```
ne-italy-ansa-20260509-a1b2c3d4
ne-italy-fao-rss-20260509-b5c6d7e8
ne-eu-china-corriere-20260510-f1e2d3c4
```

### 3.2 历史漂移修正说明

以下旧格式在文档中已出现，本规范发布后统一替换为标准格式：

| 旧格式 | 来源文件 | 对应标准格式 |
|--------|---------|-------------|
| `ne-2026-05-09-ansa-001` | `newsevent-schema.md` JSON 示例 | `ne-italy-ansa-20260509-{hash8}` |
| `ansa-20260509-001` | `integration-protocol.md` jq 示例 | `ne-italy-ansa-20260509-{hash8}` |
| `ne-italy-ansa-20260509-a1b2c3d4`（integrate 示例） | `integration-protocol.md` §5.2 | 此格式已符合规范，保留 |

### 3.3 生成规则

- `hash8` 由 `source_url + collected_at` 的 SHA-256 截取前 8 位十六进制生成（确定性）。
- 相同 URL 在同一天内的不同采集时间点仍生成相同 `id`，用于去重。
- 若无法获取 URL，以 `title_original + published_at` 替代哈希输入。

---

## §4. 分值口径规范

### 4.1 默认量纲：0–100 整数或浮点

适用于以下字段：

| 字段 | 量纲 | 语义 |
|------|------|------|
| `news_value_score` | 0–100 | 综合新闻价值，越高越重要 |
| `china_relevance` | 0–100 | 涉华相关性，100 为强相关 |
| `source_credibility` | 0–100 | 来源可信度，100 为最高 |
| `FilterResult.confidence` | 0–100 | 过滤置信度 |
| `ValueDimension.score` | 0–100 | 单维度评分 |
| `Entity.relevance` | 0–100 | 实体与涉华议题相关度 |
| `metadata.translation.confidence` | 0–100 | 翻译质量置信度（见 §6） |
| `PipelineContext.target_config.priority_threshold` | 0–100 | 推送阈值，默认 70 |

### 4.2 显式例外（非 0–100）

| 字段 | 实际量纲 | 原因 |
|------|---------|------|
| `sentiment_score` | -1.0 ～ 1.0（浮点） | 正负极性语义，负值代表负面情绪，0 代表中立，正值代表正面情绪 |
| `ValueDimension.weight` | 百分比，各维度之和建议为 100 | 权重语义，不是分数 |

**文档标注规则：** 所有出现 `sentiment_score` 的文档旁边必须注明 `（-1.0 ～ 1.0，非 0–100）` 以防混淆。

### 4.3 全局禁止

- 不得创建量纲为 0.0–1.0 的新置信度/相关性字段（与 `sentiment_score` 的 -1～1 以及 0–100 体系共存会造成系统性混乱）。若需此类字段，先修改本规范并创建 ADR。

---

## §5. 目录状态 ↔ `pipeline_stage` 映射

### 5.1 核心原则

> **目录是物理位置，`pipeline_stage` 是逻辑状态，二者正交。**

一个 `NewsEvent` 在同一目录可能处于不同 `pipeline_stage`；一个 `pipeline_stage` 的事件可能存在于多个目录（例如归档的 `filtered` 事件同时出现在 `archive/` 而非 `evaluated/`）。禁止用目录路径替代 `pipeline_stage` 字段判断事件状态。

### 5.2 映射参考表

| 目录 | 通常承载的 `pipeline_stage` | 语义说明 |
|------|--------------------------|---------|
| `raw/` | `collected` | 刚采集，未过滤 |
| `evaluated/` | `filtered` 或 `judged` | 过滤后保留，或已完成研判 |
| `drafts/` | `judged` → 编辑中 | 高价值事件生成的编辑草稿（含 `workflow_state`） |
| `reviewed/` | `judged` → 人审通过 | 人工或内审确认后的候选 |
| `published/` | `outputted` → 归档 | 已产出或批准的存档 |
| `archive/` | `filtered`（被拒）或 `judged`（discard）| 低价值、重复、失败样本永久保留 |
| `memory/` | 非事件 | source health、run cursors、provider stats、KOL 状态 |
| `logs/` | 非事件 | run 日志、工具审计日志、provider 使用日志 |

### 5.3 `pipeline_stage` 与 `workflow_state` 分离

`pipeline_stage` 和编辑/人审流转状态是两个维度，**彼此正交，互不替代**：

| 维度 | 字段 | 赋值方 | 含义 |
|------|------|--------|------|
| 逻辑管线状态 | `NewsEvent.pipeline_stage` | 各阶段 Skill | 数据处理进展：`collected / filtered / judged / outputted` |
| 编辑/人审流转 | `workflow_state`（可选，写入 frontmatter） | 人工或输出 Skill | 编辑流程状态：`draft / under_review / approved / rejected / archived` |

`workflow_state` 不是 `NewsEvent` 顶层字段，而是写入 Obsidian Markdown frontmatter，供人审查和编辑系统使用。

---

## §6. 双语处理字段规范

以下字段属于"双语 SOP"（见 `docs/it-zh-bilingual-sop.md`）的数据模型约定，写入 `NewsEvent.metadata.translation`，不进 schema 顶层：

```yaml
metadata:
  translation:
    title_pre:        string?   # collect 阶段低成本机译（非 canonical，仅供参考）
    confidence:       float     # 0–100，judge 阶段高保真译后填充
    engine_route:     string    # route_id，如 "translate.fast" / "translate.high"
    status:           enum      # "completed" | "skipped" | "partial"
    glossary_hit_rate: float?   # 0–100，命名实体命中术语表的比率（影响 recommendation）
```

**关键规则：**

- `title_translated` 和 `content_translated` 是 `NewsEvent` 的 canonical 翻译字段，只在 judge 阶段由高保真路由填充。
- `metadata.translation.title_pre` 是 collect 阶段的"预览机译"，**不得**写入 `title_translated`。
- `translation.status=skipped` 表示翻译未执行，**不得**用 `null` 代替（null 与 skipped 语义不同）。

---

## §7. 各文件口径修正记录

| 问题 | 旧文档位置 | 修正结论 | 相关 ADR |
|------|-----------|---------|---------|
| `pipeline_stage` 动词/分词混用 | `integration-protocol.md §3.1` vs `newsevent-schema.md` | 统一用分词形式（`collected/filtered/judged/outputted`）；`SkillManifest.pipeline_stage` 用动词原形（`collect/filter/judge/output`） | ADR-0001 |
| `NewsEvent.id` 三种格式并存 | `newsevent-schema.md`、`integration-protocol.md`、`newsevent-schema.md` JSON 示例 | 统一为 `ne-{target_id}-{source_id}-{yyyymmdd}-{hash8}` | ADR-0001 |
| `sentiment_score` 量纲例外 | `newsevent-schema.md` 字段注释与 `AGENTS.md` "0–100" 表述混用 | `-1.0 ～ 1.0`，明示例外，旁注标记 | ADR-0001 |
| `output_channels` 字段不存在于 schema 顶层 | `integration-protocol.md §5.2` 表格 | 替换为 `output_result.destinations[].channel` 和 `output_result.dispatched_at` | ADR-0002 |
| `SandboxPolicy.write_roots` 缺 `reviewed/` 和 `published/` | `SandboxPolicy与执行权限规格.md §1 YAML` | 补入 `reviewed` 和 `published` | ADR-0003 |
| `ToolRunResult.error.type` 枚举缺 `args_invalid` | `SandboxPolicy与执行权限规格.md` | 与 §5 错误类型表对齐，补充缺失枚举值 | ADR-0003 |
| `多语言翻译时机` 待讨论（`newsevent-schema.md` 待讨论第 4 条）| `newsevent-schema.md §待讨论` | 已决策：collect 阶段做预览机译写入 metadata，judge 阶段做 canonical 高保真翻译 | ADR-0004 |
| `workflow_state` 与 `pipeline_stage` 分离（待讨论第 5 条） | `newsevent-schema.md §待讨论` | 已决策：二者正交，`workflow_state` 写入 frontmatter 不进 schema 顶层 | ADR-0005 |
| 产品名大小写不一致 | `architecture-overview.md`（`news-sentry`）vs `AGENTS.md`（`News Sentry`） | 统一：口语/文章用 `News Sentry`，包名/命令用 `news-sentry` | ADR-0001 |

---

## §8. 引用本文档的方式

在其他文档中引用本文件时，使用如下短句：

> 字段口径、分值量纲、目录映射和命名规范见 [`docs/contracts-canonical.md`](./contracts-canonical.md)。

在争议出现时，用如下句式裁定：

> 依据 `contracts-canonical.md §{节号}`，正确写法为 `{正确形式}`。

---

## §9. Classification Metadata Schema

> 决策来源: [ADR-0009](./adr/0009-four-layer-classification-framework.md)
> 详细 taxonomy 定义: [`docs/news-classification-framework.md`](./news-classification-framework.md)

### 9.1 字段位置与结构

`metadata.classification` 写入 `NewsEvent.metadata.classification`，**不作为顶层字段**。

```yaml
metadata:
  classification:
    l0: string          # 必填（classify Skill 输出时）；L0 枚举值（12 类）
    l1: string[]        # 必填；至少 1 项；取值见 news-classification-framework.md §2
    l2: string[]        # 可空；枚举: actor|institution|location|instrument|event-trigger
    l3: string          # 推荐；枚举见 news-classification-framework.md §4
    country_axes:       # 可空；Italy 子轴，其他国家按需新增
      - axis: string    # 轴名: region|coalition|scope|china-italy-rel
        value: string   # 轴值，见 news-classification-framework.md §5
    confidence: integer|null  # 0–100（量纲同 §4.1）；规则引擎输出时为 null
    classifier_version: string  # 格式: {type}-v{n}，如 "rules-v1"、"llm-v1"
```

### 9.2 L0 枚举（固定，修改需新 ADR）

```
politics | economy | society | tech | culture | sports |
disaster | public-safety | health | environment |
international-relations | china-related
```

### 9.3 L3 枚举（固定，修改需新 ADR）

```
announced | proposed | passed | rejected | implemented |
suspended | leaked | under-investigation | scheduled |
cancelled | ongoing | concluded
```

### 9.4 字段规则摘要

| 规则 | 说明 |
|---|---|
| `l0` + `l1` 在 classify Skill 存在时为必填 | Phase 3 Kernel MVP 中 classify 可缺失，`metadata.classification` 整体可为 `null` |
| `confidence` 量纲 | 0–100 整数（与 `§4.1` 对齐），规则引擎时为 `null`（非 0） |
| `l0` 不允许多值 | 多域交叉时，`l0` 选主要域，`l1[]` 可包含跨域子主题 |
| `country_axes` 隔离 | 意大利子轴（`region`、`coalition`）不被第二国家配置引用 |
| `classifier_version` 迭代 | 分类器升级时更新 version，不回写历史事件（防止分类结果不一致） |

### 9.5 修正记录

| 版本 | 修改 | ADR |
|---|---|---|
| v1.0 (2026-05-09) | 新增本节，定稿 L0–L3 枚举与字段位置 | ADR-0009 |

---

## §10. JSON Schema 引用规则

> 决策来源: [ADR-0014](./adr/0014-json-schema-contract-validation.md)
> Schema 目录: [`schemas/`](../schemas/)

### 10.1 双向绑定规则

本文档与 `schemas/` 目录中的 JSON Schema 文件形成双向绑定关系：

| 方向 | 规则 |
|---|---|
| 本文档 → schemas/ | 每个章节顶部加 `> Schema: schemas/{name}.schema.json` 引用注释 |
| schemas/ → 本文档 | 每个 schema 的 `description` 字段引用 `contracts-canonical.md §N` |
| config/ → schemas/ | 每个 config YAML 头部注释 `# Schema: ../schemas/{name}.schema.json` |

任何单边修改（只改文档不改 schema，或只改 schema 不改文档）视为草稿状态，不应合并。

### 10.2 Schema 清单（12 份）

| Schema 文件 | 覆盖契约章节 | 状态 |
|---|---|---|
| `schemas/newsevent.schema.json` | §1–§8 + metadata 扩展 | Phase 1 完成 |
| `schemas/pipelinecontext.schema.json` | §2（PipelineContext） | Phase 1 完成 |
| `schemas/targetconfig.schema.json` | config/targets/ 配置结构（ADR-0015） | Phase 1 完成 |
| `schemas/sourcechannel.schema.json` | §4（采集层） | Phase 1 完成 |
| `schemas/filterrules.schema.json` | Phase 3 Filter 规则集合 | Phase 1 完成 |
| `schemas/classification.schema.json` | §9（ADR-0009） | Phase 1 完成 |
| `schemas/skillmanifest.schema.json` | §3（SkillManifest） | Phase 1 完成 |
| `schemas/toolmanifest.schema.json` | §5（ADR-0011） | Phase 1 完成 |
| `schemas/sandboxpolicy.schema.json` | §6（ADR-0003） | Phase 1 完成 |
| `schemas/providerconfig.schema.json` | §7（AI Provider，ADR-0005） | Phase 1 完成 |
| `schemas/toolrunresult.schema.json` | §5（ToolRunResult） | Phase 1 完成 |
| `schemas/outputresult.schema.json` | §8（ADR-0002） | Phase 1 完成 |

### 10.3 Schema $id 规范

所有 schema 的 `$id` 使用以下格式：

```
https://news-sentry.local/schemas/{name}.schema.json
```

`$schema` 固定为：

```
https://json-schema.org/draft/2020-12/schema
```

### 10.4 校验时机

| 阶段 | 校验位置 | 校验内容 |
|---|---|---|
| Phase 1（当前） | 人工审查 | 目测 schema 与文档一致 |
| Phase 3（Kernel MVP） | `core/config.py::ConfigLoader` | 加载 YAML 后调用 `jsonschema.validate()` |
| Phase 4+（Registry） | Skill/Tool 注册时 | SkillManifest / ToolManifest 校验 |

### 10.5 修正记录

| 版本 | 修改 | ADR |
|---|---|---|
| v1.0 (2026-05-09) | 新增本节，定稿 schema 双向绑定规则与清单 | ADR-0014 |
