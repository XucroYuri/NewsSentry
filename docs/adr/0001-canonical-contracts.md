# ADR-0001 — 口径规范基准

> 状态: **Accepted**
> 日期: 2026-05-09
> 决策者: News Sentry 项目团队
> 覆盖文档: `AGENTS.md`、`docs/contracts-canonical.md`、全部规格文档

---

## 背景

项目在规划讨论阶段（截至 2026-05-09）已积累 18 份文档。通过全量对照发现以下六类系统性口径漂移，若不在实现前统一，将在 Skill 对接、数据交接和测试验证中造成不可控的混乱：

1. `pipeline_stage` 在不同文件使用动词原形（`collect`）和过去分词（`collected`）两种形式，语义均指"当前所处环节状态"。
2. `NewsEvent.id` 在 `newsevent-schema.md`、`integration-protocol.md` 的正文说明、JSON 示例、jq 示例中出现三种不同格式。
3. `sentiment_score` 的量纲为 -1～1，与全局"0–100"原则并存，但缺少显式例外声明。
4. `output_channels`（`integration-protocol.md §5.2`）在 `newsevent-schema.md` 中没有对应的顶层字段。
5. `SandboxPolicy` YAML 的 `write_roots` 缺少 `reviewed/` 和 `published/` 目录。
6. 产品名在不同文档中使用 `News Sentry`、`news-sentry`、`NewsSentry` 等多种写法。

---

## 决策

### D1：`pipeline_stage` 枚举

**`NewsEvent.pipeline_stage` 和 `ProcessRecord.stage` 统一使用过去分词形式：**

```
collected | filtered | judged | outputted
```

`SkillManifest.pipeline_stage` 使用动词原形（`collect | filter | judge | output`）表达"该 Skill 负责哪个环节"，与 NewsEvent 状态字段形式不同，不产生歧义。

### D2：`NewsEvent.id` 格式

**统一格式为：**

```
ne-{target_id}-{source_id}-{yyyymmdd}-{hash8}
```

其中 `hash8` 由 `source_url + collected_at` 的 SHA-256 前 8 位十六进制生成。

### D3：分值量纲

**默认量纲 0–100，以下为已知例外：**

- `sentiment_score`：-1.0 ～ 1.0（正负极性语义）。
- `ValueDimension.weight`：百分比（权重，各维度之和建议为 100，非分数）。

所有规格文档中出现 `sentiment_score` 字段时，必须在旁边注明 `（-1.0 ～ 1.0，非 0–100）`。

### D4：目录 ↔ `pipeline_stage` 分离

**目录是物理位置，`pipeline_stage` 是逻辑状态，二者正交，不得相互替代。**

映射关系见 `docs/contracts-canonical.md §5`。

### D5：产品命名

- 品牌名/标题场景：`News Sentry`（两词，首字母大写）。
- 包名/CLI/代码标识符：`news-sentry`（小写连字符）。

---

## 替代方案考虑

- **不统一，各文档自行决定**：成本低但实现阶段必然造成 Skill 输出不兼容，排除。
- **强制全部使用动词原形 `collect`**：丢失了"当前所处状态"的语义，排除。
- **`id` 不包含 `target_id`**：多 target 场景下无法从 id 直接定位数据，排除。

---

## 影响

- `newsevent-schema.md`：更新 JSON 示例中的 id 格式，`sentiment_score` 旁加例外注释。
- `integration-protocol.md`：更新 jq 示例 id 格式，更新 §5.2 表格中的 `output_channels`。
- `SandboxPolicy与执行权限规格.md`：`write_roots` 补充 `reviewed/`、`published/`。
- `AGENTS.md`：引用 `contracts-canonical.md` 作为口径基准。
- 全部规格文档：产品名写法统一。

---

## 后续 ADR

- [ADR-0002](./0002-output-result-field-alignment.md)：`output_channels` 字段对齐。
- [ADR-0003](./0003-sandbox-write-roots-and-error-enum.md)：SandboxPolicy 补全。
- [ADR-0004](./0004-bilingual-translation-timing.md)：翻译时机。
- [ADR-0005](./0005-pipeline-stage-vs-workflow-state.md)：编辑流程状态分离。
